from __future__ import annotations

import html
from datetime import UTC, datetime
from email.utils import format_datetime
from xml.etree import ElementTree as ET

from .models import Article

MEDIA = "http://search.yahoo.com/mrss/"
ATOM = "http://www.w3.org/2005/Atom"
CONTENT = "http://purl.org/rss/1.0/modules/content/"
ET.register_namespace("media", MEDIA)
ET.register_namespace("atom", ATOM)
ET.register_namespace("content", CONTENT)


def rss_bytes(articles: list[Article], *, feed_url: str, source_title: str, source_url: str) -> bytes:
    root = ET.Element("rss", {"version": "2.0"})
    channel = ET.SubElement(root, "channel")
    _element(channel, "title", source_title)
    _element(channel, "link", source_url)
    _element(channel, "description", f"Senaste publika metadata från {source_title}.")
    _element(channel, "language", "sv")
    _element(channel, "generator", "feedsmith")
    ET.SubElement(channel, f"{{{ATOM}}}link", {"href": feed_url, "rel": "self", "type": "application/rss+xml"})
    for article in articles:
        item = ET.SubElement(channel, "item")
        _element(item, "title", article.title)
        _element(item, "link", article.canonical_url)
        _element(item, "guid", article.canonical_url, {"isPermaLink": "true"})
        _element(item, "pubDate", format_datetime(_article_time(article).astimezone(UTC), usegmt=True))
        for category in _categories(article):
            _element(item, "category", category)
        _element(item, "description", _html_description(article))
        _element(item, "encoded", _article_html(article), namespace=CONTENT)
        if article.image_url:
            mime = _image_type(article.image_url)
            ET.SubElement(item, "enclosure", {"url": article.image_url, "type": mime})
            ET.SubElement(item, f"{{{MEDIA}}}thumbnail", {"url": article.image_url})
            ET.SubElement(item, f"{{{MEDIA}}}content", {"url": article.image_url, "medium": "image", "type": mime})
    return _xml(root)


def atom_bytes(articles: list[Article], *, feed_url: str, source_title: str, source_url: str) -> bytes:
    feed = ET.Element(f"{{{ATOM}}}feed")
    _element(feed, "title", source_title, namespace=ATOM)
    _element(feed, "id", feed_url, namespace=ATOM)
    _element(feed, "updated", _atom_time(max((_article_time(a) for a in articles), default=datetime.now(UTC))), namespace=ATOM)
    ET.SubElement(feed, f"{{{ATOM}}}link", {"href": feed_url, "rel": "self", "type": "application/atom+xml"})
    ET.SubElement(feed, f"{{{ATOM}}}link", {"href": source_url, "rel": "alternate", "type": "text/html"})
    for article in articles:
        entry = ET.SubElement(feed, f"{{{ATOM}}}entry")
        _element(entry, "title", article.title, namespace=ATOM)
        _element(entry, "id", article.canonical_url, namespace=ATOM)
        _element(entry, "updated", _atom_time(article.updated_at or _article_time(article)), namespace=ATOM)
        _element(entry, "published", _atom_time(_article_time(article)), namespace=ATOM)
        ET.SubElement(entry, f"{{{ATOM}}}link", {"href": article.canonical_url, "rel": "alternate", "type": "text/html"})
        for category in _categories(article):
            ET.SubElement(entry, f"{{{ATOM}}}category", {"term": category})
        _element(entry, "summary", _html_description(article), {"type": "html"}, namespace=ATOM)
        _element(entry, "content", _article_html(article), {"type": "html"}, namespace=ATOM)
        if article.image_url:
            ET.SubElement(entry, f"{{{ATOM}}}link", {"href": article.image_url, "rel": "enclosure", "type": _image_type(article.image_url)})
    return _xml(feed)


def _categories(article: Article) -> tuple[str, ...]:
    values = (("Premium",) if article.is_premium else ()) + ((article.section,) if article.section else ()) + article.tags
    return tuple(dict.fromkeys(value for value in values if value))


def _article_time(article: Article) -> datetime:
    return article.published_at or article.updated_at or datetime.now(UTC)


def _atom_time(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _element(parent: ET.Element, name: str, text: str, attributes: dict[str, str] | None = None, namespace: str | None = None) -> ET.Element:
    element = ET.SubElement(parent, f"{{{namespace}}}{name}" if namespace else name, attributes or {})
    element.text = text
    return element


def _html_description(article: Article) -> str:
    image = f'<img src="{html.escape(article.image_url, quote=True)}" alt="" loading="lazy" />' if article.image_url else ""
    text = html.escape(article.description or "")
    return f"{image}<p>{text}</p>" if text else image


def _article_html(article: Article) -> str:
    image = f'<img src="{html.escape(article.image_url, quote=True)}" alt="" loading="lazy" />' if article.image_url else ""
    return f"{image}{article.content_html}" if article.content_html else _html_description(article)


def _image_type(url: str) -> str:
    suffix = url.split("?", 1)[0].lower().rsplit(".", 1)[-1]
    return {"png": "image/png", "webp": "image/webp", "gif": "image/gif"}.get(suffix, "image/jpeg")


def _xml(root: ET.Element) -> bytes:
    ET.indent(root, space="  ")
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)
