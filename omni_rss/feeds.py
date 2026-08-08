from __future__ import annotations

import html
from datetime import UTC, datetime
from email.utils import format_datetime
from xml.etree import ElementTree as ET

from .models import Article

MEDIA = "http://search.yahoo.com/mrss/"
ATOM = "http://www.w3.org/2005/Atom"
ET.register_namespace("media", MEDIA)
ET.register_namespace("atom", ATOM)


def rss_bytes(articles: list[Article], *, feed_base_url: str) -> bytes:
    root = ET.Element("rss", {"version": "2.0"})
    channel = ET.SubElement(root, "channel")
    _element(channel, "title", "Omni – senaste nyheterna (inofficiell RSS)")
    _element(channel, "link", "https://omni.se/senaste")
    _element(channel, "description", "Senaste artiklar från Omni.se. Bilder hotlänkas från Omni.")
    _element(channel, "language", "sv")
    _element(channel, "generator", "omni-rss")
    ET.SubElement(channel, f"{{{ATOM}}}link", {"href": f"{feed_base_url}/rss.xml", "rel": "self", "type": "application/rss+xml"})
    for article in articles:
        item = ET.SubElement(channel, "item")
        _element(item, "title", article.title)
        _element(item, "link", article.link)
        _element(item, "guid", article.link, {"isPermaLink": "true"})
        _element(item, "pubDate", format_datetime(article.published_at.astimezone(UTC), usegmt=True))
        if article.category:
            _element(item, "category", article.category)
        _element(item, "description", _html_description(article))
        if article.image_url:
            ET.SubElement(item, f"{{{MEDIA}}}thumbnail", {"url": article.image_url})
            ET.SubElement(item, f"{{{MEDIA}}}content", {"url": article.image_url, "medium": "image", "type": _image_type(article.image_url)})
    return _xml(root)


def atom_bytes(articles: list[Article], *, feed_base_url: str) -> bytes:
    feed = ET.Element(f"{{{ATOM}}}feed")
    _element(feed, "title", "Omni – senaste nyheterna (inofficiell RSS)", namespace=ATOM)
    _element(feed, "id", f"{feed_base_url}/atom.xml", namespace=ATOM)
    _element(feed, "updated", _updated(articles), namespace=ATOM)
    ET.SubElement(feed, f"{{{ATOM}}}link", {"href": f"{feed_base_url}/atom.xml", "rel": "self", "type": "application/atom+xml"})
    ET.SubElement(feed, f"{{{ATOM}}}link", {"href": "https://omni.se/senaste", "rel": "alternate", "type": "text/html"})
    for article in articles:
        entry = ET.SubElement(feed, f"{{{ATOM}}}entry")
        _element(entry, "title", article.title, namespace=ATOM)
        _element(entry, "id", article.link, namespace=ATOM)
        _element(entry, "updated", article.published_at.astimezone(UTC).isoformat().replace("+00:00", "Z"), namespace=ATOM)
        _element(entry, "published", article.published_at.astimezone(UTC).isoformat().replace("+00:00", "Z"), namespace=ATOM)
        ET.SubElement(entry, f"{{{ATOM}}}link", {"href": article.link, "rel": "alternate", "type": "text/html"})
        if article.category:
            ET.SubElement(entry, f"{{{ATOM}}}category", {"term": article.category})
        summary = _element(entry, "summary", _html_description(article), {"type": "html"}, namespace=ATOM)
        if article.image_url:
            ET.SubElement(entry, f"{{{ATOM}}}link", {"href": article.image_url, "rel": "enclosure", "type": _image_type(article.image_url)})
    return _xml(feed)


def _element(parent: ET.Element, name: str, text: str, attributes: dict[str, str] | None = None, namespace: str | None = None) -> ET.Element:
    element = ET.SubElement(parent, f"{{{namespace}}}{name}" if namespace else name, attributes or {})
    element.text = text
    return element


def _html_description(article: Article) -> str:
    image = f'<img src="{html.escape(article.image_url, quote=True)}" alt="" loading="lazy" />' if article.image_url else ""
    return f"{image}<p>{html.escape(article.summary)}</p>"


def _image_type(url: str) -> str:
    suffix = url.split("?", 1)[0].lower().rsplit(".", 1)[-1]
    return {"png": "image/png", "webp": "image/webp", "gif": "image/gif"}.get(suffix, "image/jpeg")


def _updated(articles: list[Article]) -> str:
    timestamp = max((item.published_at for item in articles), default=None) or datetime.now(UTC)
    return timestamp.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _xml(root: ET.Element) -> bytes:
    ET.indent(root, space="  ")
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)
