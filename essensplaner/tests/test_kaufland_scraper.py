from datetime import date
from pathlib import Path

from offers.kaufland_scraper import _parse_offers_html, _parse_validity

FIXTURE = (Path(__file__).parent / "fixtures" / "kaufland_sample.html").read_text(encoding="utf-8")

# Fixiertes "heute", damit die (jahrlose) Datumsauflösung in den Tests
# deterministisch bleibt.
TODAY = date(2026, 9, 4)


def test_parse_offers_html_extracts_all_tiles():
    offers = _parse_offers_html(FIXTURE, today=TODAY)
    assert len(offers) == 2
    assert offers[0].product_name == "GOUDA Scheiben 250g, jung, mild"
    assert offers[0].price == 1.99
    assert offers[0].retailer == "kaufland"
    assert offers[0].discount_text == "-20%"
    assert offers[0].valid_from == date(2026, 9, 7)
    assert offers[0].valid_until == date(2026, 9, 13)
    assert offers[1].product_name == "BIO-MÖHREN 1kg"
    assert offers[1].discount_text is None
    assert offers[1].price == 0.99


def test_parse_offers_html_skips_sections_without_valid_dates():
    html = """
    <div class="k-product-section">
      <div class="k-product-section__subheadline">Ohne Datum</div>
      <a class="k-product-tile">
        <div class="k-product-tile__title">Ohne Datum</div>
      </a>
    </div>
    """
    assert _parse_offers_html(html, today=TODAY) == []


def test_parse_validity_handles_single_day_without_year():
    assert _parse_validity("Angebote gültig am 04.09.", today=TODAY) == (date(2026, 9, 4), date(2026, 9, 4))


def test_parse_validity_handles_range_across_year_boundary():
    # Ende Dezember gescrapt, Angebot bezieht sich auf Anfang Januar -> Folgejahr.
    result = _parse_validity("Gültig vom 02.01. bis 08.01.", today=date(2026, 12, 20))
    assert result == (date(2027, 1, 2), date(2027, 1, 8))


def test_parse_validity_returns_none_without_recognizable_date():
    assert _parse_validity("Nur diese Woche im Online-Marktplatz", today=TODAY) is None
