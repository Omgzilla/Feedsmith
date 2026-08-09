CREATE TABLE IF NOT EXISTS http_cache (
    source TEXT NOT NULL,
    url TEXT NOT NULL,
    etag TEXT,
    last_modified TEXT,
    checked_at TEXT NOT NULL,
    PRIMARY KEY (source, url)
);
