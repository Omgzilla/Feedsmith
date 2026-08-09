from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Article:
    """Public metadata for one article; article bodies are intentionally absent."""

    source: str
    external_id: str
    canonical_url: str
    title: str
    description: str | None
    image_url: str | None
    section: str | None
    author: str | None
    published_at: datetime | None
    updated_at: datetime | None
    is_premium: bool
    content_html: str | None = None
    tags: tuple[str, ...] = ()


@dataclass(frozen=True)
class FeedFilter:
    name: str
    premium: bool | None = None
    section: str | None = None
