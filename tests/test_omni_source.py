from pathlib import Path
from datetime import UTC, datetime

from feedsmith.core.models import Article
from feedsmith.sources.omni import canonicalize_url, clean_teaser, extract_article_links, parse_article
from feedsmith.sources.omni import OmniSource


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
    assert clean_teaser("Teaser. Kontakta redaktionen för frågor.") == "Teaser. för frågor."


def test_expanded_omni_mer_benefits_card_is_removed():
    teaser = """Analytikern tror att marknaden vänder.
    Fortsätt läsa - testa gratis i 1 månad
    Få tillgång till hela artikeln och allt vårt bästa material i Omni Mer.
    Bild: annons Läs utan annonser Bild: annons Dela med en vän
    Bild: annons Avsluta när du vill LINK Prova gratis"""
    assert clean_teaser(teaser) == "Analytikern tror att marknaden vänder."


def test_historic_stored_description_is_cleaned_when_rendering_a_feed():
    historic = Article(
        source="omni", external_id="id", canonical_url="https://omni.se/a/a1", title="Title",
        description="Teaser. Kontakta redaktionen. Fortsätt läsa - testa gratis i 1 månad Få tillgång till hela artikeln och allt vårt bästa material i Omni Mer.",
        image_url=None, section=None, author=None, published_at=datetime.now(UTC), updated_at=None, is_premium=False,
    )
    adapter = OmniSource(timeout=1, delay=0, user_agent="test")
    assert adapter.normalize_for_feed(historic).description == "Teaser."


def test_live_omni_paywall_and_contact_components_are_removed_as_whole_blocks():
    fragment = """<p>Public teaser.</p>
    <div class="SalesPosterContainer-module-scss-module__abc__salesPoster">
      <h2>Fortsätt läsa – testa gratis i 1 månad</h2>
      <p>Få tillgång till hela artikeln och allt vårt bästa material i Omni Mer.</p>
      <ul><li>Läs utan annonser</li><li>Dela med en vän</li><li>Avsluta när du vill</li></ul>
      <a>Prova gratis</a>
    </div>
    <div class="ArticleActions-module-scss-module__abc__contactInformation">
      Omni är politiskt obundna och oberoende. Vi strävar efter att ge fler perspektiv på nyheterna.
      Har du frågor eller synpunkter kring vår rapportering? <a>Kontakta redaktionen</a>
    </div>"""
    assert clean_teaser(fragment) == "Public teaser."


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
