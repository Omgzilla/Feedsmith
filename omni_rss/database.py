from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .models import Article


class Database:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA foreign_keys=ON")
        self._create_schema()

    def close(self) -> None:
        self.connection.close()

    def _create_schema(self) -> None:
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS articles (
                guid TEXT PRIMARY KEY,
                link TEXT NOT NULL UNIQUE,
                title TEXT NOT NULL,
                summary TEXT NOT NULL,
                image_url TEXT,
                category TEXT,
                published_at TEXT NOT NULL,
                source_url TEXT NOT NULL,
                first_seen TEXT NOT NULL,
                last_seen TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS articles_published_at ON articles(published_at DESC);
            CREATE TABLE IF NOT EXISTS runs (
                id INTEGER PRIMARY KEY,
                started_at TEXT NOT NULL,
                finished_at TEXT,
                status TEXT NOT NULL,
                discovered INTEGER NOT NULL DEFAULT 0,
                published INTEGER NOT NULL DEFAULT 0,
                error TEXT
            );
            """
        )
        self.connection.commit()

    def start_run(self) -> int:
        now = _timestamp()
        cursor = self.connection.execute("INSERT INTO runs(started_at, status) VALUES (?, 'running')", (now,))
        self.connection.commit()
        return int(cursor.lastrowid)

    def finish_run(self, run_id: int, *, status: str, discovered: int, published: int, error: str | None = None) -> None:
        self.connection.execute(
            """UPDATE runs SET finished_at=?, status=?, discovered=?, published=?, error=? WHERE id=?""",
            (_timestamp(), status, discovered, published, error, run_id),
        )
        self.connection.commit()

    def upsert(self, article: Article) -> None:
        now = _timestamp()
        self.connection.execute(
            """
            INSERT INTO articles(guid, link, title, summary, image_url, category, published_at, source_url, first_seen, last_seen)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(guid) DO UPDATE SET
              link=excluded.link, title=excluded.title, summary=excluded.summary,
              image_url=excluded.image_url, category=excluded.category,
              published_at=excluded.published_at, source_url=excluded.source_url, last_seen=excluded.last_seen
            """,
            (
                article.guid, article.link, article.title, article.summary, article.image_url,
                article.category, article.published_at.astimezone(UTC).isoformat(), article.source_url, now, now,
            ),
        )

    def commit(self) -> None:
        self.connection.commit()

    def prune(self, days: int) -> None:
        cutoff = (datetime.now(UTC) - timedelta(days=days)).isoformat()
        self.connection.execute("DELETE FROM articles WHERE published_at < ?", (cutoff,))
        self.connection.commit()

    def latest(self, limit: int) -> list[Article]:
        rows = self.connection.execute(
            """SELECT guid, link, title, summary, image_url, category, published_at, source_url
               FROM articles ORDER BY published_at DESC, first_seen DESC LIMIT ?""",
            (limit,),
        ).fetchall()
        return [
            Article(
                guid=row["guid"], link=row["link"], title=row["title"], summary=row["summary"],
                image_url=row["image_url"], category=row["category"],
                published_at=datetime.fromisoformat(row["published_at"]), source_url=row["source_url"],
            )
            for row in rows
        ]


def _timestamp() -> str:
    return datetime.now(UTC).isoformat()
