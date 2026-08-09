from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import replace

from feedsmith.core.models import Article


class SourceAdapter(ABC):
    """A site-specific discovery and public-metadata parser."""

    name: str

    @abstractmethod
    def discover(self, urls: tuple[str, ...], limit_per_url: int) -> list[Article]:
        """Return publicly available article metadata from configured landing pages."""

    def normalize_for_feed(self, article: Article) -> Article:
        """Apply source-specific presentation cleanup to historic stored metadata."""
        return replace(article)

    @abstractmethod
    def fetch_article(self, url: str) -> Article:
        """Fetch and parse one canonical article for an explicit refresh/backfill."""
