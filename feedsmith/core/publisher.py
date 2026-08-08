from __future__ import annotations

import os
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse
from xml.etree import ElementTree as ET

import boto3

from feedsmith.config import Settings
from feedsmith.core.models import Article


def validate_feed(payload: bytes, expected_root: str, articles: list[Article], minimum_items: int, maximum_newest_age_hours: int, canonical_hosts: tuple[str, ...]) -> int:
    root = ET.fromstring(payload)
    if root.tag.rsplit("}", 1)[-1] != expected_root:
        raise ValueError(f"expected {expected_root} document, got {root.tag}")
    count = len(root.findall("./channel/item")) if expected_root == "rss" else len(root.findall("{http://www.w3.org/2005/Atom}entry"))
    if count < minimum_items:
        raise ValueError(f"feed has {count} entry(s), below configured minimum of {minimum_items}")
    if not all(article.title.strip() and urlparse(article.canonical_url).netloc in canonical_hosts for article in articles):
        raise ValueError("feed contains a missing title or link outside the configured source hosts")
    newest = max((article.published_at or article.updated_at for article in articles), default=None)
    if newest and newest < datetime.now(UTC) - timedelta(hours=maximum_newest_age_hours):
        raise ValueError(f"newest article is older than {maximum_newest_age_hours} hours")
    return count


def atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as temporary:
            temporary.write(content)
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_name, path)
        directory = os.open(path.parent, os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    except BaseException:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


def upload_r2(settings: Settings, files: dict[str, bytes]) -> None:
    settings.validate_r2()
    client = boto3.client(
        "s3", endpoint_url=settings.r2_endpoint_url, region_name="auto",
        aws_access_key_id=settings.r2_access_key_id, aws_secret_access_key=settings.r2_secret_access_key,
    )
    for name, payload in files.items():
        content_type = "application/atom+xml; charset=utf-8" if name.endswith("atom.xml") else "application/rss+xml; charset=utf-8"
        client.put_object(
            Bucket=settings.r2_bucket, Key=name, Body=payload, ContentType=content_type,
            CacheControl="public, max-age=300, must-revalidate",
        )
