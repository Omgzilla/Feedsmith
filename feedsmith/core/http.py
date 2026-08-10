from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Protocol

import requests


class HttpCache(Protocol):
    def http_cache_headers(self, source: str, url: str) -> dict[str, str]: ...
    def store_http_cache_headers(self, source: str, url: str, *, etag: str | None, last_modified: str | None) -> None: ...
    def touch_http_cache(self, source: str, url: str) -> None: ...


class NullHttpCache:
    def http_cache_headers(self, source: str, url: str) -> dict[str, str]:
        return {}

    def store_http_cache_headers(self, source: str, url: str, *, etag: str | None, last_modified: str | None) -> None:
        pass

    def touch_http_cache(self, source: str, url: str) -> None:
        pass


@dataclass(frozen=True)
class ConditionalFetcher:
    """Polite requests session that avoids transferring unchanged public pages."""

    source: str
    cache: HttpCache
    timeout: int
    delay: float
    user_agent: str

    def __post_init__(self) -> None:
        session = requests.Session()
        session.headers.update({"User-Agent": self.user_agent, "Accept-Language": "sv-SE,sv;q=0.9,en;q=0.5"})
        object.__setattr__(self, "session", session)

    def get(self, url: str, *, conditional: bool = True) -> str | None:
        headers = self.cache.http_cache_headers(self.source, url) if conditional else {}
        response = self.session.get(url, headers=headers, timeout=self.timeout)
        try:
            if conditional and response.status_code == requests.codes.not_modified:
                self.cache.touch_http_cache(self.source, url)
                return None
            response.raise_for_status()
            self.cache.store_http_cache_headers(
                self.source,
                url,
                etag=response.headers.get("ETag"),
                last_modified=response.headers.get("Last-Modified"),
            )
            return response.text
        finally:
            time.sleep(self.delay)
