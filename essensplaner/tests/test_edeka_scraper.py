from pathlib import Path

from offers.edeka_scraper import _parse_offers_html

FIXTURE = (Path(__file__).parent / "fixtures" / "edeka_sample.html").read_text(encoding="utf-8")


def test_parse_offers_html_extracts_all_items():
    offers = _parse_offers_html(FIXTURE)
    assert len(offers) == 2
    assert offers[0].product_name == "Rispentomaten 500g"
    assert offers[0].price == 0.99
    assert offers[0].retailer == "edeka"
    assert offers[1].discount_text == "-25%"
    assert offers[1].description == "aus Deutschland"


def test_parse_offers_html_skips_items_without_validity():
    html = '<li class="product-grid__item"><span class="product-grid__title">Ohne Datum</span></li>'
    assert _parse_offers_html(html) == []
