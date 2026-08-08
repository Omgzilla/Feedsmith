from pathlib import Path

from omni_rss.scraper import extract_article_links, parse_article


FIXTURES = Path(__file__).parent / "fixtures"


def test_extracts_only_omni_article_links():
    links = extract_article_links((FIXTURES / "listing.html").read_text())
    assert links == ["https://omni.se/story-one/a/AbC123", "https://omni.se/story-two/a/XyZ987"]


def test_parses_article_and_hotlinks_only_omni_image():
    article = parse_article((FIXTURES / "article.html").read_text(), "https://omni.se/test/a/AbC123", source_url="https://omni.se/senaste")
    assert article.title == "Test & headline"
    assert article.image_url == "https://gfx.omni.se/images/test.jpg"
    assert article.category == "Inrikes"
    assert article.published_at.isoformat() == "2026-08-08T08:30:00+00:00"
