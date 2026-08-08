from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Article:
    guid: str
    link: str
    title: str
    summary: str
    image_url: str | None
    category: str | None
    published_at: datetime
    source_url: str
