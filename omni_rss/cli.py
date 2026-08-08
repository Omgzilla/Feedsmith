from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime

from .config import Settings
from .database import Database
from .feeds import atom_bytes, rss_bytes
from .publish import atomic_write, upload_r2, validate_feed
from .scraper import OmniScraper


def run(settings: Settings, *, upload: bool) -> int:
    database = Database(settings.data_dir / "omni.sqlite3")
    run_id = database.start_run()
    discovered = published = 0
    try:
        scraper = OmniScraper(timeout=settings.request_timeout_seconds, delay=settings.request_delay_seconds, user_agent=settings.user_agent)
        articles = scraper.discover(settings.source_urls, settings.max_candidates_per_source)
        discovered = len(articles)
        for article in articles:
            database.upsert(article)
        database.commit()
        database.prune(settings.retention_days)
        feed_articles = database.latest(settings.max_feed_items)
        rss = rss_bytes(feed_articles, feed_base_url=settings.feed_base_url)
        atom = atom_bytes(feed_articles, feed_base_url=settings.feed_base_url)
        rss_count = validate_feed(rss, "rss", settings.min_items)
        atom_count = validate_feed(atom, "feed", settings.min_items)
        atomic_write(settings.public_dir / "rss.xml", rss)
        atomic_write(settings.public_dir / "atom.xml", atom)
        if upload:
            upload_r2(settings, {"rss.xml": rss, "atom.xml": atom})
        published = min(rss_count, atom_count)
        database.finish_run(run_id, status="success", discovered=discovered, published=published)
        write_metrics(settings, success=True, discovered=discovered, published=published)
        print(f"Published {published} item(s); discovered {discovered} article(s).")
        return 0
    except Exception as error:
        database.finish_run(run_id, status="failure", discovered=discovered, published=published, error=str(error))
        write_metrics(settings, success=False, discovered=discovered, published=published)
        print(f"omni-rss failed: {error}", file=sys.stderr)
        return 1
    finally:
        database.close()


def write_metrics(settings: Settings, *, success: bool, discovered: int, published: int) -> None:
    if not settings.metrics_path:
        return
    now = datetime.now(UTC).timestamp()
    payload = (
        "# HELP omni_rss_last_run_success 1 when the most recent feed run succeeded.\n"
        "# TYPE omni_rss_last_run_success gauge\n"
        f"omni_rss_last_run_success {1 if success else 0}\n"
        "# HELP omni_rss_last_run_timestamp_seconds Unix timestamp of the most recent feed run.\n"
        "# TYPE omni_rss_last_run_timestamp_seconds gauge\n"
        f"omni_rss_last_run_timestamp_seconds {now:.0f}\n"
        "# TYPE omni_rss_discovered_articles gauge\n"
        f"omni_rss_discovered_articles {discovered}\n"
        "# TYPE omni_rss_published_items gauge\n"
        f"omni_rss_published_items {published}\n"
    ).encode()
    atomic_write(settings.metrics_path, payload)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build and optionally publish Omni RSS feeds.")
    parser.add_argument("command", nargs="?", choices=("run", "check"), default="run")
    parser.add_argument("--no-upload", action="store_true", help="write local files but do not upload them to R2")
    arguments = parser.parse_args()
    settings = Settings.from_env()
    if arguments.command == "check":
        settings.validate_r2()
        print("Configuration is valid.")
        return
    raise SystemExit(run(settings, upload=not arguments.no_upload))


if __name__ == "__main__":
    main()
