from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from feedsmith.config import Settings
from feedsmith.core.database import Database
from feedsmith.core.feeds import atom_bytes, rss_bytes
from feedsmith.core.metrics import write_metrics
from feedsmith.core.publisher import atomic_write, upload_r2, validate_feed
from feedsmith.sources.omni import OmniSource


ADAPTERS = {"omni": OmniSource}


def run(settings: Settings, *, source_name: str, mode: str, upload: bool) -> int:
    source_settings = settings.sources.get(source_name)
    if not source_settings or not source_settings.enabled:
        raise ValueError(f"source {source_name!r} is not enabled")
    adapter_class = ADAPTERS.get(source_name)
    if not adapter_class:
        raise ValueError(f"no adapter is installed for source {source_name!r}")
    database = Database(settings.database)
    run_id = database.start_run(source_name, mode)
    started = time.monotonic()
    discovered = stored = published = 0
    data_committed = False
    try:
        adapter = adapter_class(timeout=settings.request_timeout_seconds, delay=settings.request_delay_seconds, user_agent=settings.user_agent)
        if mode == "backfill":
            articles = []
            for existing in database.without_content(source_name, source_settings.max_backfill_articles):
                try:
                    articles.append(adapter.fetch_article(existing.canonical_url))
                except Exception as error:
                    print(f"event=backfill_skipped source={source_name} url={existing.canonical_url!r} error={error}")
        else:
            urls = source_settings.latest_urls if mode == "latest" else source_settings.full_urls
            articles = adapter.discover(urls, source_settings.max_candidates_per_url)
        discovered = len(articles)
        for article in articles:
            database.upsert(article)
            stored += 1
        database.prune(source_name, source_settings.retention_days)
        files: dict[str, bytes] = {}
        for feed_filter in source_settings.feeds:
            feed_articles = [adapter.normalize_for_feed(article) for article in database.latest(source_name, settings.feed_entries, feed_filter)]
            base = f"{settings.public_base_url}/{source_name}"
            prefix = "" if feed_filter.name == "all" else f"/{feed_filter.name}"
            rss_key, atom_key = f"{source_name}{prefix}/rss.xml", f"{source_name}{prefix}/atom.xml"
            rss = rss_bytes(feed_articles, feed_url=f"{base}{prefix}/rss.xml", source_title=source_settings.feed_title, source_url=source_settings.homepage_url)
            atom = atom_bytes(feed_articles, feed_url=f"{base}{prefix}/atom.xml", source_title=source_settings.feed_title, source_url=source_settings.homepage_url)
            rss_count = validate_feed(rss, "rss", feed_articles, settings.minimum_entries, settings.maximum_newest_age_hours, source_settings.canonical_hosts)
            atom_count = validate_feed(atom, "feed", feed_articles, settings.minimum_entries, settings.maximum_newest_age_hours, source_settings.canonical_hosts)
            files[rss_key], files[atom_key] = rss, atom
            published = max(published, min(rss_count, atom_count))
        # A rejected scrape leaves article history exactly as it was.  Commit only
        # after the combined updated state has produced valid feeds.
        database.commit()
        data_committed = True
        # All feeds are generated and validated before any local or R2 object is replaced.
        for key, payload in files.items():
            atomic_write(settings.public_dir / key, payload)
        if upload:
            upload_r2(settings, files)
        duration = time.monotonic() - started
        database.finish_run(run_id, status="success", discovered=discovered, stored=stored, published=published)
        write_metrics(settings, source=source_name, success=True, discovered=discovered, stored=stored, published=published, duration_seconds=duration)
        print(f"event=publish_success source={source_name} mode={mode} discovered={discovered} stored={stored} feed_entries={published} duration_seconds={duration:.3f}")
        return 0
    except Exception as error:
        if not data_committed:
            database.rollback()
        duration = time.monotonic() - started
        database.finish_run(run_id, status="failure", discovered=discovered, stored=stored, published=published, error=str(error))
        write_metrics(settings, source=source_name, success=False, discovered=discovered, stored=stored, published=published, duration_seconds=duration)
        print(f"event=publish_failure source={source_name} mode={mode} discovered={discovered} stored={stored} error={error}", file=sys.stderr)
        return 1
    finally:
        database.close()


def maintain(settings: Settings, source_name: str | None = None) -> int:
    database = Database(settings.database)
    try:
        names = (source_name,) if source_name else tuple(settings.sources)
        removed = 0
        for name in names:
            source_settings = settings.sources.get(name)
            if not source_settings:
                raise ValueError(f"source {name!r} is not configured")
            removed += database.prune(name, source_settings.retention_days)
        database.connection.execute("PRAGMA optimize")
        database.commit()
        print(f"event=maintenance_success pruned_articles={removed}")
        return 0
    finally:
        database.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Build and publish generic RSS and Atom feeds from public web metadata.")
    parser.add_argument("command", choices=("run", "check", "maintain"), nargs="?", default="run")
    parser.add_argument("--config", type=Path, default=Path("/etc/feedsmith/config.toml"))
    parser.add_argument("--source", default="omni")
    parser.add_argument("--mode", choices=("latest", "full", "backfill"), default="latest")
    parser.add_argument("--no-upload", action="store_true")
    arguments = parser.parse_args()
    settings = Settings.from_toml(arguments.config)
    if arguments.command == "check":
        settings.validate_r2()
        print("configuration is valid")
        return
    if arguments.command == "maintain":
        raise SystemExit(maintain(settings, arguments.source))
    raise SystemExit(run(settings, source_name=arguments.source, mode=arguments.mode, upload=not arguments.no_upload))
