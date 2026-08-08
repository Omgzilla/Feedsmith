from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


DEFAULT_SOURCES = ("https://omni.se/senaste", "https://omni.se/")


def _as_int(name: str, default: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError as error:
        raise ValueError(f"{name} must be an integer") from error
    if value < 1:
        raise ValueError(f"{name} must be at least 1")
    return value


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    public_dir: Path
    feed_base_url: str
    source_urls: tuple[str, ...]
    max_candidates_per_source: int
    max_feed_items: int
    retention_days: int
    request_timeout_seconds: int
    request_delay_seconds: float
    user_agent: str
    min_items: int
    r2_endpoint_url: str | None
    r2_bucket: str | None
    r2_access_key_id: str | None
    r2_secret_access_key: str | None
    r2_prefix: str
    metrics_path: Path | None

    @classmethod
    def from_env(cls) -> "Settings":
        source_urls = tuple(
            url.strip() for url in os.getenv("OMNI_SOURCE_URLS", "").split(",") if url.strip()
        ) or DEFAULT_SOURCES
        r2_prefix = os.getenv("R2_PREFIX", "").strip("/")
        return cls(
            data_dir=Path(os.getenv("OMNI_DATA_DIR", "/var/lib/omni-rss")),
            public_dir=Path(os.getenv("OMNI_PUBLIC_DIR", "/var/lib/omni-rss/public")),
            feed_base_url=os.getenv("FEED_BASE_URL", "https://rss.example.com").rstrip("/"),
            source_urls=source_urls,
            max_candidates_per_source=_as_int("OMNI_MAX_CANDIDATES_PER_SOURCE", 50),
            max_feed_items=_as_int("OMNI_MAX_FEED_ITEMS", 100),
            retention_days=_as_int("OMNI_RETENTION_DAYS", 30),
            request_timeout_seconds=_as_int("OMNI_REQUEST_TIMEOUT_SECONDS", 20),
            request_delay_seconds=float(os.getenv("OMNI_REQUEST_DELAY_SECONDS", "0.6")),
            user_agent=os.getenv("OMNI_USER_AGENT", "omni-rss/1.0 (+https://rss.example.com/contact)"),
            min_items=_as_int("OMNI_MIN_ITEMS", 1),
            r2_endpoint_url=os.getenv("R2_ENDPOINT_URL") or None,
            r2_bucket=os.getenv("R2_BUCKET") or None,
            r2_access_key_id=os.getenv("R2_ACCESS_KEY_ID") or None,
            r2_secret_access_key=os.getenv("R2_SECRET_ACCESS_KEY") or None,
            r2_prefix=r2_prefix,
            metrics_path=Path(os.environ["PROMETHEUS_TEXTFILE_PATH"])
            if os.getenv("PROMETHEUS_TEXTFILE_PATH")
            else None,
        )

    def validate_r2(self) -> None:
        values = (self.r2_endpoint_url, self.r2_bucket, self.r2_access_key_id, self.r2_secret_access_key)
        if not all(values):
            raise ValueError(
                "R2 upload requires R2_ENDPOINT_URL, R2_BUCKET, R2_ACCESS_KEY_ID and R2_SECRET_ACCESS_KEY"
            )
