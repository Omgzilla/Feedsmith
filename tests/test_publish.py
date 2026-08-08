from dataclasses import replace
from pathlib import Path

from omni_rss.config import Settings
from omni_rss.publish import atomic_write, upload_r2


def test_atomic_write_replaces_a_complete_file(tmp_path: Path):
    target = tmp_path / "nested" / "rss.xml"
    atomic_write(target, b"first")
    atomic_write(target, b"second")
    assert target.read_bytes() == b"second"
    assert not list(target.parent.glob(".*.tmp"))


def test_r2_upload_uses_expected_object_names_and_headers(monkeypatch):
    calls = []

    class FakeClient:
        def put_object(self, **kwargs):
            calls.append(kwargs)

    monkeypatch.setattr("omni_rss.publish.boto3.client", lambda *args, **kwargs: FakeClient())
    settings = replace(
        Settings.from_env(), r2_endpoint_url="https://account.r2.cloudflarestorage.com",
        r2_bucket="omni-rss", r2_access_key_id="access", r2_secret_access_key="secret", r2_prefix="feeds",
    )
    upload_r2(settings, {"rss.xml": b"rss", "atom.xml": b"atom"})
    assert [call["Key"] for call in calls] == ["feeds/rss.xml", "feeds/atom.xml"]
    assert all(call["CacheControl"] == "public, max-age=300, must-revalidate" for call in calls)
