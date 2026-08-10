from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
import sqlite3
from xml.etree import ElementTree as ET

import pytest

from feedsmith.config import Settings
from feedsmith.cli import run
from feedsmith.core.database import Database
from feedsmith.core.feeds import atom_bytes, rss_bytes
from feedsmith.core.http import ConditionalFetcher
from feedsmith.core.metrics import write_metrics
from feedsmith.core.models import Article
from feedsmith.core.publisher import upload_r2, validate_feed
from feedsmith.sources.registry import load_adapter


def article(**changes) -> Article:
    value = Article(
        source="omni", external_id="a", canonical_url="https://omni.se/ekonomi/a/a", title="A & B",
        description="Teaser", image_url="https://images.omni.se/a.jpg?width=1200", section="Ekonomi",
        author=None, published_at=datetime.now(UTC), updated_at=None, is_premium=True, tags=("Börs",),
    )
    return replace(value, **changes)


def test_rss_and_atom_have_premium_and_multiple_image_forms():
    item = article()
    rss = rss_bytes([item], feed_url="https://rss.example.com/omni/rss.xml", source_title="Omni", source_url="https://omni.se/senaste")
    atom = atom_bytes([item], feed_url="https://rss.example.com/omni/atom.xml", source_title="Omni", source_url="https://omni.se/senaste")
    assert validate_feed(rss, "rss", [item], 1, 48, ("omni.se",)) == 1
    assert validate_feed(atom, "feed", [item], 1, 48, ("omni.se",)) == 1
    root = ET.fromstring(rss)
    assert [node.text for node in root.findall(".//channel/item/category")] == ["Premium", "Ekonomi", "Börs"]
    assert root.find(".//channel/item/enclosure").attrib["url"] == item.image_url
    assert root.find(".//{http://search.yahoo.com/mrss/}thumbnail").attrib["url"] == item.image_url
    atom_root = ET.fromstring(atom)
    assert atom_root.find("{http://www.w3.org/2005/Atom}author/{http://www.w3.org/2005/Atom}name").text == "Feedsmith"
    assert atom_root.find(".//{http://www.w3.org/2005/Atom}entry/{http://www.w3.org/2005/Atom}author/{http://www.w3.org/2005/Atom}name") is None
    assert "&amp;" in rss.decode()


def test_full_content_is_emitted_in_rss_and_atom():
    item = article(content_html="<p>Full public article text.</p>", image_caption="A & B / TT")
    rss = rss_bytes([item], feed_url="https://rss.example.com/omni/rss.xml", source_title="Omni", source_url="https://omni.se/senaste")
    atom = atom_bytes([item], feed_url="https://rss.example.com/omni/atom.xml", source_title="Omni", source_url="https://omni.se/senaste")
    rss_root = ET.fromstring(rss)
    atom_root = ET.fromstring(atom)
    assert "Full public article text." in rss_root.find(".//{http://purl.org/rss/1.0/modules/content/}encoded").text
    assert "Full public article text." in atom_root.find(".//{http://www.w3.org/2005/Atom}content").text
    assert "<figcaption>A &amp; B / TT</figcaption>" in rss_root.find(".//{http://purl.org/rss/1.0/modules/content/}encoded").text
    assert "<figcaption>A &amp; B / TT</figcaption>" in atom_root.find(".//{http://www.w3.org/2005/Atom}content").text


def test_database_preserves_existing_metadata_when_new_scrape_is_missing(tmp_path: Path):
    database = Database(tmp_path / "state.sqlite3")
    database.upsert(article(image_caption="Photo credit"))
    database.upsert(article(description=None, image_url=None, image_caption=None, section=None, published_at=None))
    database.commit()
    stored = database.latest("omni", 10)[0]
    assert stored.description == "Teaser"
    assert stored.image_url == "https://images.omni.se/a.jpg?width=1200"
    assert stored.image_caption == "Photo credit"
    assert stored.section == "Ekonomi"
    assert stored.published_at is not None
    assert stored.is_premium is True
    database.close()


def test_database_backfill_selects_only_free_articles_without_bodies(tmp_path: Path):
    database = Database(tmp_path / "state.sqlite3")
    database.upsert(article(is_premium=False, content_html=None))
    database.upsert(article(external_id="premium", canonical_url="https://omni.se/a/premium", is_premium=True, content_html=None))
    database.upsert(article(external_id="body", canonical_url="https://omni.se/a/body", is_premium=False, content_html="<p>Stored</p>"))
    database.commit()
    assert [item.canonical_url for item in database.without_content("omni", 10)] == ["https://omni.se/ekonomi/a/a"]
    database.close()


def test_database_backfill_includes_articles_missing_an_image_caption(tmp_path: Path):
    database = Database(tmp_path / "state.sqlite3")
    database.upsert(article(is_premium=False, content_html="<p>Stored</p>", image_caption=None))
    database.upsert(article(external_id="caption", canonical_url="https://omni.se/a/caption", is_premium=True, content_html=None, image_caption=None))
    database.upsert(article(external_id="complete", canonical_url="https://omni.se/a/complete", is_premium=False, content_html="<p>Stored</p>", image_caption="Caption"))
    database.commit()
    assert [item.canonical_url for item in database.needing_backfill("omni", 10)] == [
        "https://omni.se/a/caption", "https://omni.se/ekonomi/a/a",
    ]
    database.close()


def test_migrations_are_recorded_and_upgrade_a_pre_migration_database(tmp_path: Path):
    path = tmp_path / "state.sqlite3"
    connection = sqlite3.connect(path)
    connection.executescript(
        """CREATE TABLE articles (
            source TEXT NOT NULL, external_id TEXT NOT NULL, canonical_url TEXT NOT NULL,
            title TEXT NOT NULL, description TEXT, image_url TEXT, section TEXT, author TEXT,
            published_at TEXT, updated_at TEXT, first_seen_at TEXT NOT NULL, last_seen_at TEXT NOT NULL,
            is_premium INTEGER NOT NULL DEFAULT 0, tags_json TEXT NOT NULL DEFAULT '[]',
            PRIMARY KEY (source, canonical_url)
        );
        CREATE TABLE runs (id INTEGER PRIMARY KEY, source TEXT NOT NULL, mode TEXT NOT NULL,
            started_at TEXT NOT NULL, finished_at TEXT, status TEXT NOT NULL,
            discovered INTEGER NOT NULL DEFAULT 0, stored INTEGER NOT NULL DEFAULT 0,
            published INTEGER NOT NULL DEFAULT 0, error TEXT);
        """
    )
    connection.commit()
    connection.close()
    database = Database(path)
    versions = [row[0] for row in database.connection.execute("SELECT version FROM schema_migrations ORDER BY version")]
    columns = {row[1] for row in database.connection.execute("PRAGMA table_info(articles)")}
    assert versions == [1, 2, 3, 4]
    assert "content_html" in columns
    assert "image_caption" in columns
    assert database.connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='http_cache'").fetchone()
    database.close()


def test_conditional_fetcher_reuses_etag_and_skips_unchanged_response(monkeypatch):
    class Cache:
        def __init__(self):
            self.headers = {}
            self.touched = []
        def http_cache_headers(self, source, url):
            return self.headers
        def store_http_cache_headers(self, source, url, *, etag, last_modified):
            self.headers = {"If-None-Match": etag, "If-Modified-Since": last_modified}
        def touch_http_cache(self, source, url):
            self.touched.append((source, url))
    class Response:
        def __init__(self, status, text="", headers=None):
            self.status_code, self.text, self.headers = status, text, headers or {}
        def raise_for_status(self):
            if self.status_code >= 400:
                raise RuntimeError("bad response")
    class Session:
        def __init__(self):
            self.calls = []
            self.headers = {}
        def get(self, url, headers, timeout):
            self.calls.append(headers)
            return Response(200, "page", {"ETag": '"v1"', "Last-Modified": "Mon, 01 Jan 2024 00:00:00 GMT"}) if len(self.calls) == 1 else Response(304)
    cache = Cache()
    fetcher = ConditionalFetcher(source="omni", cache=cache, timeout=1, delay=0, user_agent="test")
    session = Session()
    object.__setattr__(fetcher, "session", session)
    assert fetcher.get("https://omni.se/senaste") == "page"
    assert fetcher.get("https://omni.se/senaste") is None
    assert session.calls == [{}, {"If-None-Match": '"v1"', "If-Modified-Since": "Mon, 01 Jan 2024 00:00:00 GMT"}]
    assert cache.touched == [("omni", "https://omni.se/senaste")]


def test_registry_loads_source_module_without_cli_registration():
    assert load_adapter("omni").__name__ == "OmniSource"
    with pytest.raises(ValueError, match="no adapter"):
        load_adapter("not_installed")


def test_r2_uses_omni_object_paths_and_correct_content_types(monkeypatch, tmp_path: Path):
    calls = []
    class FakeClient:
        def put_object(self, **kwargs):
            calls.append(kwargs)
    monkeypatch.setattr("feedsmith.core.publisher.boto3.client", lambda *args, **kwargs: FakeClient())
    config = tmp_path / "config.toml"
    config.write_text("[sources.omni]\nenabled = true\n")
    settings = Settings.from_toml(config)
    settings = replace(settings, r2_endpoint_url="https://account.r2.cloudflarestorage.com", r2_bucket="feedsmith", r2_access_key_id="key", r2_secret_access_key="secret")
    upload_r2(settings, {"omni/rss.xml": b"rss", "omni/atom.xml": b"atom"})
    assert [call["Key"] for call in calls] == ["omni/rss.xml", "omni/atom.xml"]
    assert [call["ContentType"] for call in calls] == ["application/rss+xml; charset=utf-8", "application/atom+xml; charset=utf-8"]


def test_metrics_use_a_run_gauge_without_a_misleading_total_suffix(tmp_path: Path):
    config = tmp_path / "config.toml"
    config.write_text("[sources.omni]\nenabled = true\n")
    settings = replace(Settings.from_toml(config), metrics_path=tmp_path / "feedsmith.prom")
    write_metrics(settings, source="omni", success=True, discovered=3, stored=2, published=2, duration_seconds=1.25)
    output = settings.metrics_path.read_text()
    assert "feedsmith_articles_discovered{source=\"omni\"} 3" in output
    assert "feedsmith_articles_discovered_total" not in output


def test_validation_rejects_an_empty_or_stale_feed_before_publish():
    empty = rss_bytes([], feed_url="https://rss.example.com/omni/rss.xml", source_title="Omni", source_url="https://omni.se/senaste")
    try:
        validate_feed(empty, "rss", [], 1, 48, ("omni.se",))
    except ValueError as error:
        assert "below configured minimum" in str(error)
    else:
        raise AssertionError("empty feed was accepted")
    stale = article(published_at=datetime.now(UTC) - timedelta(hours=49))
    payload = rss_bytes([stale], feed_url="https://rss.example.com/omni/rss.xml", source_title="Omni", source_url="https://omni.se/senaste")
    try:
        validate_feed(payload, "rss", [stale], 1, 48, ("omni.se",))
    except ValueError as error:
        assert "newest article" in str(error)
    else:
        raise AssertionError("stale feed was accepted")


def test_rejected_scrape_rolls_back_new_database_rows(monkeypatch, tmp_path: Path):
    config = tmp_path / "config.toml"
    config.write_text(
        f"""[application]
database = \"{tmp_path / 'state.sqlite3'}\"
public_dir = \"{tmp_path / 'public'}\"
minimum_entries = 2
[publishing]
public_base_url = \"https://rss.example.com\"
[sources.omni]
enabled = true
canonical_hosts = [\"omni.se\"]
feed_title = \"Omni\"
homepage_url = \"https://omni.se/senaste\"
"""
    )
    class OneArticleAdapter:
        def __init__(self, **kwargs):
            pass
        def discover(self, urls, limit):
            return [article()]
    monkeypatch.setattr("feedsmith.cli.registry.load_adapter", lambda name: OneArticleAdapter)
    settings = Settings.from_toml(config)
    assert run(settings, source_name="omni", mode="latest", upload=False) == 1
    database = Database(tmp_path / "state.sqlite3")
    assert database.latest("omni", 10) == []
    database.close()
