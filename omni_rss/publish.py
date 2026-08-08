from __future__ import annotations

import os
import tempfile
from pathlib import Path
from xml.etree import ElementTree as ET

import boto3

from .config import Settings


def validate_feed(payload: bytes, expected_root: str, minimum_items: int) -> int:
    root = ET.fromstring(payload)
    if root.tag.rsplit("}", 1)[-1] != expected_root:
        raise ValueError(f"expected {expected_root} document, got {root.tag}")
    if expected_root == "rss":
        count = len(root.findall("./channel/item"))
    else:
        count = len(root.findall("{http://www.w3.org/2005/Atom}entry"))
    if count < minimum_items:
        raise ValueError(f"feed has {count} item(s), below OMNI_MIN_ITEMS={minimum_items}")
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
        key = f"{settings.r2_prefix}/{name}" if settings.r2_prefix else name
        content_type = "application/atom+xml; charset=utf-8" if name == "atom.xml" else "application/rss+xml; charset=utf-8"
        client.put_object(
            Bucket=settings.r2_bucket, Key=key, Body=payload, ContentType=content_type,
            CacheControl="public, max-age=300, must-revalidate",
        )
