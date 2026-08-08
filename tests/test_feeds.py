from datetime import UTC, datetime
from xml.etree import ElementTree as ET

from omni_rss.feeds import atom_bytes, rss_bytes
from omni_rss.models import Article
from omni_rss.publish import validate_feed


ARTICLE = Article(
    guid="abc", link="https://omni.se/example/a/abc", title="Title", summary="Summary",
    image_url="https://gfx.omni.se/example.jpg", category="Inrikes",
    published_at=datetime(2026, 8, 8, 10, tzinfo=UTC), source_url="https://omni.se/senaste",
)


def test_rss_is_well_formed_and_contains_media_image():
    payload = rss_bytes([ARTICLE], feed_base_url="https://rss.example.com")
    assert validate_feed(payload, "rss", 1) == 1
    root = ET.fromstring(payload)
    assert root.find(".//{http://search.yahoo.com/mrss/}content").attrib["url"] == ARTICLE.image_url


def test_atom_is_well_formed_and_contains_enclosure():
    payload = atom_bytes([ARTICLE], feed_base_url="https://rss.example.com")
    assert validate_feed(payload, "feed", 1) == 1
    root = ET.fromstring(payload)
    assert root.find(".//{http://www.w3.org/2005/Atom}link[@rel='enclosure']").attrib["href"] == ARTICLE.image_url
