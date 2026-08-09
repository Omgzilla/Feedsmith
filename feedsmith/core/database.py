from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from importlib.resources import files
from pathlib import Path

from .models import Article, FeedFilter


class Database:
    """SQLite source of truth; rows are keyed by source plus canonical URL."""

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA foreign_keys=ON")
        self._apply_migrations()

    def close(self) -> None:
        self.connection.close()

    def _apply_migrations(self) -> None:
        self.connection.execute("CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)")
        applied = {row["version"] for row in self.connection.execute("SELECT version FROM schema_migrations")}
        if not applied and self._table_exists("articles"):
            # Feedsmith releases before migration bookkeeping already used the
            # initial schema, with public content optionally added in-place.
            self._mark_migration(1)
            if "content_html" in self._columns("articles"):
                self._mark_migration(2)
            applied = {row["version"] for row in self.connection.execute("SELECT version FROM schema_migrations")}
        for version, filename in ((1, "001_initial.sql"), (2, "002_public_content.sql"), (3, "003_http_cache.sql")):
            if version not in applied:
                self.connection.executescript(files("feedsmith.migrations").joinpath(filename).read_text(encoding="utf-8"))
                self._mark_migration(version)
        self.connection.commit()

    def _table_exists(self, name: str) -> bool:
        return self.connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None

    def _columns(self, table: str) -> set[str]:
        return {row["name"] for row in self.connection.execute(f"PRAGMA table_info({table})")}

    def _mark_migration(self, version: int) -> None:
        self.connection.execute("INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES (?, ?)", (version, _timestamp()))

    def start_run(self, source: str, mode: str) -> int:
        cursor = self.connection.execute(
            "INSERT INTO runs(source, mode, started_at, status) VALUES (?, ?, ?, 'running')",
            (source, mode, _timestamp()),
        )
        self.connection.commit()
        return int(cursor.lastrowid)

    def finish_run(self, run_id: int, *, status: str, discovered: int, stored: int, published: int, error: str | None = None) -> None:
        self.connection.execute(
            """UPDATE runs SET finished_at=?, status=?, discovered=?, stored=?, published=?, error=? WHERE id=?""",
            (_timestamp(), status, discovered, stored, published, error, run_id),
        )
        self.connection.commit()

    def upsert(self, article: Article) -> None:
        now = _timestamp()
        self.connection.execute(
            """
            INSERT INTO articles (
                source, external_id, canonical_url, title, description, content_html, image_url,
                section, author, published_at, updated_at, first_seen_at, last_seen_at,
                is_premium, tags_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(source, canonical_url) DO UPDATE SET
                external_id=excluded.external_id,
                title=excluded.title,
                description=COALESCE(excluded.description, articles.description),
                content_html=COALESCE(excluded.content_html, articles.content_html),
                image_url=COALESCE(excluded.image_url, articles.image_url),
                section=COALESCE(excluded.section, articles.section),
                author=COALESCE(excluded.author, articles.author),
                published_at=COALESCE(excluded.published_at, articles.published_at),
                updated_at=COALESCE(excluded.updated_at, articles.updated_at),
                is_premium=CASE WHEN articles.is_premium = 1 THEN 1 ELSE excluded.is_premium END,
                tags_json=CASE WHEN excluded.tags_json = '[]' THEN articles.tags_json ELSE excluded.tags_json END,
                last_seen_at=excluded.last_seen_at
            """,
            (
                article.source, article.external_id, article.canonical_url, article.title,
                article.description, article.content_html, article.image_url, article.section, article.author,
                _datetime(article.published_at), _datetime(article.updated_at), now, now,
                int(article.is_premium), json.dumps(article.tags, ensure_ascii=False),
            ),
        )

    def commit(self) -> None:
        self.connection.commit()

    def prune(self, source: str, days: int) -> int:
        cutoff = (datetime.now(UTC) - timedelta(days=days)).isoformat()
        cursor = self.connection.execute(
            "DELETE FROM articles WHERE source=? AND COALESCE(published_at, first_seen_at) < ?",
            (source, cutoff),
        )
        self.connection.execute(
            "DELETE FROM http_cache WHERE source=? AND checked_at < ?",
            (source, cutoff),
        )
        return cursor.rowcount

    def rollback(self) -> None:
        self.connection.rollback()

    def latest(self, source: str, limit: int, feed_filter: FeedFilter | None = None) -> list[Article]:
        predicates = ["source = ?"]
        values: list[object] = [source]
        if feed_filter and feed_filter.premium is not None:
            predicates.append("is_premium = ?")
            values.append(int(feed_filter.premium))
        if feed_filter and feed_filter.section:
            predicates.append("lower(section) = lower(?)")
            values.append(feed_filter.section)
        values.append(limit)
        rows = self.connection.execute(
            f"SELECT * FROM articles WHERE {' AND '.join(predicates)} "
            "ORDER BY COALESCE(published_at, first_seen_at) DESC, first_seen_at DESC LIMIT ?",
            values,
        ).fetchall()
        return [_article(row) for row in rows]

    def without_content(self, source: str, limit: int) -> list[Article]:
        rows = self.connection.execute(
            """SELECT * FROM articles WHERE source=? AND is_premium=0 AND content_html IS NULL
               ORDER BY COALESCE(published_at, first_seen_at) DESC, first_seen_at DESC LIMIT ?""",
            (source, limit),
        ).fetchall()
        return [_article(row) for row in rows]

    def http_cache_headers(self, source: str, url: str) -> dict[str, str]:
        row = self.connection.execute("SELECT etag, last_modified FROM http_cache WHERE source=? AND url=?", (source, url)).fetchone()
        if not row:
            return {}
        return {key: value for key, value in (("If-None-Match", row["etag"]), ("If-Modified-Since", row["last_modified"])) if value}

    def store_http_cache_headers(self, source: str, url: str, *, etag: str | None, last_modified: str | None) -> None:
        self.connection.execute(
            """INSERT INTO http_cache(source, url, etag, last_modified, checked_at) VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(source, url) DO UPDATE SET etag=excluded.etag, last_modified=excluded.last_modified, checked_at=excluded.checked_at""",
            (source, url, etag, last_modified, _timestamp()),
        )

    def touch_http_cache(self, source: str, url: str) -> None:
        self.connection.execute(
            "UPDATE http_cache SET checked_at=? WHERE source=? AND url=?",
            (_timestamp(), source, url),
        )


def _article(row: sqlite3.Row) -> Article:
    return Article(
        source=row["source"], external_id=row["external_id"], canonical_url=row["canonical_url"],
        title=row["title"], description=row["description"], content_html=row["content_html"], image_url=row["image_url"],
        section=row["section"], author=row["author"], published_at=_parse_datetime(row["published_at"]),
        updated_at=_parse_datetime(row["updated_at"]), is_premium=bool(row["is_premium"]),
        tags=tuple(json.loads(row["tags_json"])),
    )


def _timestamp() -> str:
    return datetime.now(UTC).isoformat()


def _datetime(value: datetime | None) -> str | None:
    return value.astimezone(UTC).isoformat() if value else None


def _parse_datetime(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None
