from __future__ import annotations

from abc import ABC, abstractmethod

from feedsmith.core.models import Article


class SourceAdapter(ABC):
    """A site-specific discovery and public-metadata parser."""

    name: str

    @abstractmethod
    def discover(self, urls: tuple[str, ...], limit_per_url: int) -> list[Article]:
        """Return publicly available article metadata from configured landing pages."""
