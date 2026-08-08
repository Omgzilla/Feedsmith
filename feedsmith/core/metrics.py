from __future__ import annotations

from datetime import UTC, datetime

from feedsmith.config import Settings
from feedsmith.core.publisher import atomic_write


def write_metrics(settings: Settings, *, source: str, success: bool, discovered: int, stored: int, published: int, duration_seconds: float) -> None:
    if not settings.metrics_path:
        return
    labels = f'source="{source}"'
    now = datetime.now(UTC).timestamp()
    payload = (
        "# TYPE feedsmith_scrape_success gauge\n"
        f"feedsmith_scrape_success{{{labels}}} {int(success)}\n"
        "# TYPE feedsmith_scrape_duration_seconds gauge\n"
        f"feedsmith_scrape_duration_seconds{{{labels}}} {duration_seconds:.3f}\n"
        "# TYPE feedsmith_articles_discovered_total gauge\n"
        f"feedsmith_articles_discovered_total{{{labels}}} {discovered}\n"
        "# TYPE feedsmith_articles_stored gauge\n"
        f"feedsmith_articles_stored{{{labels}}} {stored}\n"
        "# TYPE feedsmith_feed_entries gauge\n"
        f"feedsmith_feed_entries{{{labels}}} {published}\n"
        "# TYPE feedsmith_last_success_timestamp_seconds gauge\n"
        f"feedsmith_last_success_timestamp_seconds{{{labels}}} {now:.0f}\n"
        "# TYPE feedsmith_publish_success gauge\n"
        f"feedsmith_publish_success{{{labels}}} {int(success)}\n"
    ).encode()
    atomic_write(settings.metrics_path, payload)
