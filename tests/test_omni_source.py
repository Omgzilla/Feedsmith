from pathlib import Path

from feedsmith.sources.omni import canonicalize_url, clean_teaser, extract_article_links, parse_article


FIXTURES = Path(__file__).parent / "fixtures"


def test_premium_article_preserves_title_and_removes_mer_cta():
    article = parse_article((FIXTURES / "omni_premium.html").read_text(), "https://omni.se/marknad/a/AbC123")
    assert article.title == "Oförändrad premiumrubrik"
    assert article.is_premium is True
    assert article.description == "Analytikern tror att marknaden vänder."
    assert article.image_url == "https://images.omni.se/news.jpg?width=1200&quality=80"
    assert article.canonical_url == "https://omni.se/marknad/a/AbC123"
    assert article.tags == ("Börs", "Aktier")


def test_no_image_and_second_mer_cta_are_supported():
    article = parse_article((FIXTURES / "omni_no_image.html").read_text(), "https://omni.se/inrikes/a/XyZ987")
    assert article.image_url is None
    assert article.description == "Kort offentlig teaser."
    assert article.is_premium is False


def test_contact_editorial_link_and_markup_are_removed_only_by_omni_cleanup():
    assert clean_teaser("<p>Teaser</p><a href='/contact'> Kontakta&nbsp;redaktionen </a>") == "Teaser"


def test_canonicalization_removes_tracking_and_fragments_but_preserves_other_query():
    assert canonicalize_url("https://omni.se/a/a1/?utm_source=x&variant=amp#comments") == "https://omni.se/a/a1?variant=amp"


def test_extract_links_deduplicates_on_canonical_url():
    html = '<a href="/one/a/a1?utm_source=x"></a><a href="/one/a/a1#more"></a>'
    assert extract_article_links(html) == ["https://omni.se/one/a/a1"]


def test_srcset_chooses_highest_resolution_omni_image_with_parameters():
    html = """<html><head><meta property='og:title' content='Story'><meta property='og:url' content='https://omni.se/a/a1'></head>
    <body><img srcset='https://images.omni.se/a.jpg?width=320 320w, https://images.omni.se/a.jpg?width=1600&quality=80 1600w'></body></html>"""
    article = parse_article(html, "https://omni.se/a/a1")
    assert article.image_url == "https://images.omni.se/a.jpg?width=1600&quality=80"
