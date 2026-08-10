from __future__ import annotations

import hashlib
import html
import json
import re
from dataclasses import replace
from datetime import UTC, datetime
from urllib.parse import urljoin, urlparse, urlunparse

import requests
from bs4 import BeautifulSoup, NavigableString

from feedsmith.core.cleanup import compact_text, normalized_text, remove_text_blocks
from feedsmith.core.http import ConditionalFetcher, HttpCache, NullHttpCache
from feedsmith.core.models import Article
from feedsmith.sources.base import SourceAdapter

OMNI_ORIGIN = "https://omni.se"
ARTICLE_PATH = re.compile(r"/a/[A-Za-z0-9_-]+/?$")
PROMOTION_BLOCKS = (
    "Fortsätt läsa – testa gratis i 1 månad Få tillgång till hela artikeln och allt vårt bästa material i Omni Mer.",
    "Gå förbi betalväggar! Omni Mer låser upp en mängd artiklar. En smidig lösning när du vill fördjupa dig.",
)
CONTACT_EDITORIAL = "Kontakta redaktionen"
MER_BENEFITS_CARD = re.compile(
    r"fortsätt\s+läsa\s*[-–—]\s*testa\s+gratis\s+i\s+1\s+månad.*?"
    r"läs\s+utan\s+annonser.*?dela\s+med\s+en\s+vän.*?"
    r"avsluta\s+när\s+du\s+vill.*?(?:link\s+)?prova\s+gratis",
    flags=re.IGNORECASE | re.DOTALL,
)
CONTACT_INFORMATION = re.compile(
    r"omni\s+är\s+politiskt\s+obundna\s+och\s+oberoende\.\s*"
    r"vi\s+strävar\s+efter\s+att\s+ge\s+fler\s+perspektiv\s+på\s+nyheterna\.\s*"
    r"har\s+du\s+frågor\s+eller\s+synpunkter\s+kring\s+vår\s+rapportering\?\s*"
    r"kontakta\s+redaktionen",
    flags=re.IGNORECASE | re.DOTALL,
)


class OmniSource(SourceAdapter):
    """Omni adapter: public metadata plus free-article public bodies only."""

    name = "omni"

    def __init__(self, *, timeout: int, delay: float, user_agent: str, cache: HttpCache | None = None) -> None:
        self.fetcher = ConditionalFetcher(source=self.name, cache=cache or NullHttpCache(), timeout=timeout, delay=delay, user_agent=user_agent)

    def discover(self, urls: tuple[str, ...], limit_per_url: int) -> list[Article]:
        links: list[str] = []
        for url in urls:
            page = self._get(url)
            if page is None:
                continue
            for link in extract_article_links(page, url)[:limit_per_url]:
                if link not in links:
                    links.append(link)
        articles: list[Article] = []
        for link in links:
            try:
                page = self._get(link)
                if page is not None:
                    articles.append(parse_article(page, link))
            except (ValueError, requests.RequestException) as error:
                print(f"source=omni event=article_skipped url={link!r} error={error}")
        return articles

    def normalize_for_feed(self, article: Article) -> Article:
        return replace(article, description=(clean_teaser(article.description) or None) if article.description else None)

    def fetch_article(self, url: str) -> Article:
        # Backfills request the current public page even when a prior discovery
        # cached validators before a newly supported field was introduced.
        page = self._get(url, conditional=False)
        if page is None:
            raise ValueError("article is unchanged")
        return parse_article(page, url)

    def _get(self, url: str, *, conditional: bool = True) -> str | None:
        return self.fetcher.get(url, conditional=conditional)


SOURCE_ADAPTER = OmniSource


def extract_article_links(html: str, base_url: str = OMNI_ORIGIN) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    found: list[str] = []
    for anchor in soup.find_all("a", href=True):
        candidate = canonicalize_url(urljoin(base_url, anchor["href"]))
        parsed = urlparse(candidate)
        if parsed.scheme == "https" and parsed.netloc == "omni.se" and ARTICLE_PATH.search(parsed.path):
            if candidate not in found:
                found.append(candidate)
    return found


def parse_article(html: str, discovered_url: str) -> Article:
    soup = BeautifulSoup(html, "html.parser")
    data = _first_news_article(soup)
    title = _value(data, "headline") or _meta(soup, "og:title") or _text(soup.select_one("h1"))
    if not title:
        raise ValueError("missing title")
    description = _value(data, "description") or _meta(soup, "og:description") or _meta(soup, "description")
    canonical = canonicalize_url(_meta(soup, "og:url") or _link_rel(soup, "canonical") or discovered_url)
    image = _best_image(soup, _value(data, "image") or _meta(soup, "og:image"))
    section = _value(data, "articleSection") or _meta(soup, "article:section")
    author = _author(data)
    tags = _tags(data)
    premium = _is_premium(soup, data)
    return Article(
        source="omni", external_id=hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        canonical_url=canonical, title=compact_text(title), description=(clean_teaser(description) or None) if description else None,
        content_html=None if premium else _public_article_html(soup),
        image_url=image, section=compact_text(section) if section else None,
        author=(compact_text(author) or None) if author else None, published_at=_parse_datetime(_value(data, "datePublished") or _meta(soup, "article:published_time")),
        updated_at=_parse_datetime(_value(data, "dateModified") or _meta(soup, "article:modified_time")),
        is_premium=premium, tags=tags, image_caption=_image_caption(soup, image),
    )


def _public_article_html(soup: BeautifulSoup) -> str | None:
    """Return public article text only; never traverse paywall or page UI components."""
    container = soup.select_one("article [class*='Text-module'][class*='textContainer']")
    if not container:
        return None
    blocks: list[str] = []
    for element in container.find_all(["p", "h2", "h3", "blockquote", "li"]):
        if element.find_parent(["p", "li", "blockquote"]) is not None:
            continue
        text = compact_text(element.get_text(" ", strip=True))
        if not text:
            continue
        tag = element.name if element.name in {"h2", "h3", "blockquote", "li"} else "p"
        blocks.append(f"<{tag}>{html.escape(text)}</{tag}>")
    return "".join(blocks) or None


def clean_teaser(value: str) -> str:
    """Remove known Omni UI/promotional fragments, keeping public editorial teaser text."""
    soup = BeautifulSoup(value, "html.parser")
    # Remove complete, source-specific UI components before collecting text. The
    # module-name prefix is stable while the generated suffix changes per build.
    for component in soup.select("[class*='SalesPosterContainer'], [class*='contactInformation']"):
        component.decompose()
    for anchor in soup.find_all("a"):
        if normalized_text(anchor.get_text(" ", strip=True)) == normalized_text(CONTACT_EDITORIAL):
            anchor.decompose()
    for text in list(soup.find_all(string=True)):
        if isinstance(text, NavigableString) and normalized_text(str(text)) == normalized_text(CONTACT_EDITORIAL):
            text.extract()
    text = soup.get_text(" ", strip=True)
    # This expanded Omni Mer card may contain image alt text between its benefit
    # labels. Remove it only when the complete, distinctive sequence is present.
    text = MER_BENEFITS_CARD.sub(" ", text)
    text = CONTACT_INFORMATION.sub(" ", text)
    return remove_text_blocks(text, PROMOTION_BLOCKS + (CONTACT_EDITORIAL,))


def canonicalize_url(value: str) -> str:
    parsed = urlparse(urljoin(OMNI_ORIGIN, value))
    if parsed.netloc == "omni.se" or parsed.netloc.endswith(".omni.se"):
        parsed = parsed._replace(scheme="https", netloc="omni.se", path=parsed.path.rstrip("/"))
    # Canonical article identity is the path. Image URLs preserve their own query
    # parameters elsewhere, but no article query parameter may create a duplicate.
    return urlunparse(parsed._replace(query="", fragment=""))


def _first_news_article(soup: BeautifulSoup) -> dict[str, object]:
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            payload = json.loads(script.get_text())
        except json.JSONDecodeError:
            continue
        for node in _walk_json(payload):
            kind = node.get("@type")
            types = kind if isinstance(kind, list) else [kind]
            if any(value in {"NewsArticle", "Article"} for value in types):
                return node
    return {}


def _walk_json(value: object):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk_json(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_json(child)


def _value(data: dict[str, object], key: str) -> str | None:
    value = data.get(key)
    if isinstance(value, str):
        return value
    if isinstance(value, list) and value and isinstance(value[0], str):
        return value[0]
    if isinstance(value, dict):
        for nested_key in ("url", "contentUrl", "name"):
            nested = value.get(nested_key)
            if isinstance(nested, str):
                return nested
    return None


def _author(data: dict[str, object]) -> str | None:
    author = data.get("author")
    if isinstance(author, str):
        return author
    if isinstance(author, dict) and isinstance(author.get("name"), str):
        return author["name"]
    if isinstance(author, list):
        names = [item.get("name") for item in author if isinstance(item, dict) and isinstance(item.get("name"), str)]
        return ", ".join(names) if names else None
    return None


def _tags(data: dict[str, object]) -> tuple[str, ...]:
    value = data.get("keywords")
    if isinstance(value, str):
        values = re.split(r"\s*,\s*", value)
    elif isinstance(value, list):
        values = [item for item in value if isinstance(item, str)]
    else:
        values = []
    return tuple(dict.fromkeys(compact_text(item) for item in values if compact_text(item)))


def _meta(soup: BeautifulSoup, name: str) -> str | None:
    tag = soup.find("meta", attrs={"property": name}) or soup.find("meta", attrs={"name": name})
    return tag.get("content") if tag and tag.get("content") else None


def _link_rel(soup: BeautifulSoup, rel: str) -> str | None:
    tag = soup.find("link", attrs={"rel": rel})
    return tag.get("href") if tag and tag.get("href") else None


def _text(tag) -> str | None:
    return tag.get_text(" ", strip=True) if tag else None


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def _best_image(soup: BeautifulSoup, fallback: str | None) -> str | None:
    image = soup.select_one("meta[property='og:image']")
    candidate = image.get("content") if image else fallback
    # A source-provided srcset may provide a higher-quality image than og:image.
    for tag in soup.select("img[srcset]"):
        candidates = _srcset_candidates(tag.get("srcset", ""))
        if candidates:
            candidate = candidates[-1][0]
            break
    return _omni_image_url(candidate)


def _image_caption(soup: BeautifulSoup, image_url: str | None) -> str | None:
    """Return the visible caption for the selected lead image, if Omni provides one."""
    if not image_url:
        return None
    target = _image_identity(image_url)
    if not target:
        return None
    for figure in soup.select("figure"):
        image = figure.find("img")
        if not image or _image_identity(_tag_image_url(image)) != target:
            continue
        caption = figure.find("figcaption")
        if caption:
            value = compact_text(caption.get_text(" ", strip=True))
            return value or None
    return None


def _tag_image_url(tag) -> str | None:
    candidates = _srcset_candidates(tag.get("srcset", ""))
    return _omni_image_url(candidates[-1][0] if candidates else tag.get("src"))


def _image_identity(value: str | None) -> tuple[str, str] | None:
    url = _omni_image_url(value)
    if not url:
        return None
    parsed = urlparse(url)
    return parsed.netloc, parsed.path


def _srcset_candidates(value: str) -> list[tuple[str, int]]:
    result: list[tuple[str, int]] = []
    for item in value.split(","):
        parts = item.strip().split()
        if not parts:
            continue
        width = int(parts[-1][:-1]) if len(parts) > 1 and parts[-1].endswith("w") and parts[-1][:-1].isdigit() else 0
        result.append((parts[0], width))
    return sorted(result, key=lambda item: item[1])


def _omni_image_url(value: str | None) -> str | None:
    if not value:
        return None
    parsed = urlparse(urljoin(OMNI_ORIGIN, value))
    return parsed.geturl() if parsed.scheme == "https" and (parsed.netloc == "omni.se" or parsed.netloc.endswith(".omni.se")) else None


def _is_premium(soup: BeautifulSoup, data: dict[str, object]) -> bool:
    value = data.get("isAccessibleForFree")
    if value is False or (isinstance(value, str) and value.casefold() == "false"):
        return True
    # A site-wide Omni Mer promotion is not evidence that this particular story
    # is premium.  Only source metadata or a story-level premium marker may set it.
    return bool(soup.select_one("article [data-premium='true'], article [data-is-premium='true'], main [data-premium='true'], main [data-is-premium='true']"))
