from pathlib import Path
from offers.kaufland_scraper import _parse_offers_html

FIXTURE = (Path(__file__).parent / "fixtures" / "kaufland_sample.html").read_text(encoding="utf-8")


def test_parse_offers_html_extracts_all_tiles():
    offers = _parse_offers_html(FIXTURE)
    assert len(offers) == 2
    assert offers[0].product_name == "Gouda Scheiben 250g"
    assert offers[0].price == 1.99
    assert offers[0].retailer == "kaufland"
    assert offers[1].discount_text == "-20%"
    assert offers[1].price is None


def test_parse_offers_html_skips_tiles_without_validity():
    html = '<div class="offer-tile"><h3 class="offer-tile__title">Ohne Datum</h3></div>'
    assert _parse_offers_html(html) == []
