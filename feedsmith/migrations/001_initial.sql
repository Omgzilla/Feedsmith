CREATE TABLE IF NOT EXISTS articles (
    source TEXT NOT NULL,
    external_id TEXT NOT NULL,
    canonical_url TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT,
    image_url TEXT,
    section TEXT,
    author TEXT,
    published_at TEXT,
    updated_at TEXT,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    is_premium INTEGER NOT NULL DEFAULT 0,
    tags_json TEXT NOT NULL DEFAULT '[]',
    PRIMARY KEY (source, canonical_url)
);

CREATE INDEX IF NOT EXISTS articles_ordering
    ON articles(source, published_at DESC, first_seen_at DESC);

CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY,
    source TEXT NOT NULL,
    mode TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL,
    discovered INTEGER NOT NULL DEFAULT 0,
    stored INTEGER NOT NULL DEFAULT 0,
    published INTEGER NOT NULL DEFAULT 0,
    error TEXT
);
