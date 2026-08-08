from __future__ import annotations

import hashlib
import json
import re
import time
from datetime import UTC, datetime
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from .models import Article

OMNI_ORIGIN = "https://omni.se"
ARTICLE_PATH = re.compile(r"/a/[A-Za-z0-9_-]+/?$")


class OmniScraper:
    def __init__(self, *, timeout: int, delay: float, user_agent: str) -> None:
        self.timeout = timeout
        self.delay = delay
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": user_agent, "Accept-Language": "sv-SE,sv;q=0.9,en;q=0.5"})

    def discover(self, source_urls: tuple[str, ...], limit_per_source: int) -> list[Article]:
        links: list[str] = []
        for source in source_urls:
            html = self._get(source)
            # Apply the cap to each configured landing page, so one busy page
            # cannot crowd out a separately configured category page.
            for link in extract_article_links(html, source)[:limit_per_source]:
                if link not in links:
                    links.append(link)
        articles: list[Article] = []
        for link in links:
            try:
                articles.append(parse_article(self._get(link), link, source_url=link))
            except (ValueError, requests.RequestException) as error:
                # A single changed or removed story must not prevent a feed update.
                print(f"Skipping {link}: {error}")
            if len(articles) >= len(source_urls) * limit_per_source:
                break
        return articles

    def _get(self, url: str) -> str:
        response = self.session.get(url, timeout=self.timeout)
        response.raise_for_status()
        time.sleep(self.delay)
        return response.text


def extract_article_links(html: str, base_url: str = OMNI_ORIGIN) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    found: list[str] = []
    for anchor in soup.find_all("a", href=True):
        candidate = urljoin(base_url, anchor["href"]).split("#", 1)[0]
        parsed = urlparse(candidate)
        if parsed.scheme == "https" and parsed.netloc.endswith("omni.se") and ARTICLE_PATH.search(parsed.path):
            normalized = f"https://omni.se{parsed.path.rstrip('/')}"
            if normalized not in found:
                found.append(normalized)
    return found


def parse_article(html: str, link: str, *, source_url: str) -> Article:
    soup = BeautifulSoup(html, "html.parser")
    data = _first_news_article(soup)
    title = _value(data, "headline") or _meta(soup, "og:title") or _text(soup.select_one("h1"))
    summary = _value(data, "description") or _meta(soup, "og:description") or _meta(soup, "description")
    if not title or not summary:
        raise ValueError("missing title or summary")
    image = _image_url(_value(data, "image") or _meta(soup, "og:image"))
    category = _value(data, "articleSection") or _meta(soup, "article:section")
    published = _parse_datetime(_value(data, "datePublished") or _meta(soup, "article:published_time"))
    canonical = _meta(soup, "og:url") or link
    canonical = urljoin(OMNI_ORIGIN, canonical)
    guid = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return Article(
        guid=guid, link=canonical, title=_clean(title), summary=_clean(summary), image_url=image,
        category=_clean(category) if category else None, published_at=published, source_url=source_url,
    )


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
        for key in ("url", "contentUrl"):
            nested = value.get(key)
            if isinstance(nested, str):
                return nested
    return None


def _meta(soup: BeautifulSoup, name: str) -> str | None:
    tag = soup.find("meta", attrs={"property": name}) or soup.find("meta", attrs={"name": name})
    return tag.get("content") if tag and tag.get("content") else None


def _text(tag) -> str | None:
    return tag.get_text(" ", strip=True) if tag else None


def _clean(value: str) -> str:
    return " ".join(value.split())


def _parse_datetime(value: str | None) -> datetime:
    if not value:
        return datetime.now(UTC)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return datetime.now(UTC)
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def _image_url(value: str | None) -> str | None:
    if not value:
        return None
    parsed = urlparse(urljoin(OMNI_ORIGIN, value))
    # Only hotlink Omni-hosted images; never download, proxy, or republish them.
    if parsed.scheme == "https" and parsed.netloc.endswith("omni.se"):
        return parsed.geturl()
    return None
