from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

from feedsmith.core.models import FeedFilter


@dataclass(frozen=True)
class SourceSettings:
    name: str
    enabled: bool
    retention_days: int
    latest_urls: tuple[str, ...]
    full_urls: tuple[str, ...]
    max_candidates_per_url: int
    max_backfill_articles: int
    feeds: tuple[FeedFilter, ...]
    feed_title: str
    homepage_url: str
    canonical_hosts: tuple[str, ...]


@dataclass(frozen=True)
class Settings:
    database: Path
    public_dir: Path
    public_base_url: str
    retention_days: int
    feed_entries: int
    minimum_entries: int
    maximum_newest_age_hours: int
    request_timeout_seconds: int
    request_delay_seconds: float
    user_agent: str
    r2_endpoint_url: str | None
    r2_bucket: str | None
    r2_access_key_id: str | None
    r2_secret_access_key: str | None
    metrics_path: Path | None
    sources: dict[str, SourceSettings]

    @classmethod
    def from_toml(cls, path: Path) -> "Settings":
        with path.open("rb") as config_file:
            data = tomllib.load(config_file)
        application = data.get("application", {})
        publishing = data.get("publishing", {})
        scraping = data.get("scraping", {})
        sources = {
            name: _source_settings(name, value, int(application.get("retention_days", 30)))
            for name, value in data.get("sources", {}).items()
        }
        return cls(
            database=Path(application.get("database", "/var/lib/feedsmith/feedsmith.sqlite3")),
            public_dir=Path(application.get("public_dir", "/var/lib/feedsmith/public")),
            public_base_url=str(publishing.get("public_base_url", "https://rss.example.com")).rstrip("/"),
            retention_days=int(application.get("retention_days", 30)), feed_entries=int(application.get("feed_entries", 500)),
            minimum_entries=int(application.get("minimum_entries", 1)), maximum_newest_age_hours=int(application.get("maximum_newest_age_hours", 48)),
            request_timeout_seconds=int(scraping.get("request_timeout_seconds", 20)), request_delay_seconds=float(scraping.get("request_delay_seconds", 0.6)),
            user_agent=os.getenv("FEEDSMITH_USER_AGENT", "feedsmith/0.1 (+https://rss.example.com/contact)"),
            r2_endpoint_url=os.getenv("R2_ENDPOINT_URL") or None, r2_bucket=os.getenv("R2_BUCKET") or None,
            r2_access_key_id=os.getenv("R2_ACCESS_KEY_ID") or None, r2_secret_access_key=os.getenv("R2_SECRET_ACCESS_KEY") or None,
            metrics_path=Path(os.environ["PROMETHEUS_TEXTFILE_PATH"]) if os.getenv("PROMETHEUS_TEXTFILE_PATH") else None,
            sources=sources,
        )

    def validate_r2(self) -> None:
        if not all((self.r2_endpoint_url, self.r2_bucket, self.r2_access_key_id, self.r2_secret_access_key)):
            raise ValueError("R2 upload requires R2_ENDPOINT_URL, R2_BUCKET, R2_ACCESS_KEY_ID and R2_SECRET_ACCESS_KEY")


def _source_settings(name: str, data: dict[str, object], default_retention_days: int) -> SourceSettings:
    default_latest_urls = ["https://omni.se/senaste"] if name == "omni" else []
    default_full_urls = ["https://omni.se/", "https://omni.se/ekonomi", "https://omni.se/utrikes"] if name == "omni" else []
    feeds_data = data.get("feeds", {}) if isinstance(data.get("feeds", {}), dict) else {}
    filters: list[FeedFilter] = [FeedFilter("all")] if feeds_data.get("all", True) else []
    if feeds_data.get("free", False):
        filters.append(FeedFilter("free", premium=False))
    if feeds_data.get("premium", False):
        filters.append(FeedFilter("premium", premium=True))
    categories = feeds_data.get("categories", [])
    if categories is True:
        categories = []  # Explicit categories avoid unexpectedly publishing a growing endpoint set.
    for category in categories if isinstance(categories, list) else []:
        filters.append(FeedFilter(str(category).casefold(), section=str(category)))
    return SourceSettings(
        name=name, enabled=bool(data.get("enabled", True)), retention_days=int(data.get("retention_days", default_retention_days)),
        latest_urls=tuple(data.get("latest_urls", default_latest_urls)),
        full_urls=tuple(data.get("full_urls", default_full_urls)),
        max_candidates_per_url=int(data.get("max_candidates_per_url", 50)),
        max_backfill_articles=int(data.get("max_backfill_articles", 500)), feeds=tuple(filters),
        feed_title=str(data.get("feed_title", f"{name} – latest articles")),
        homepage_url=str(data.get("homepage_url", (data.get("latest_urls") or default_latest_urls or ["https://example.invalid"])[0])),
        canonical_hosts=tuple(data.get("canonical_hosts", [f"{name}.invalid"])),
    )
