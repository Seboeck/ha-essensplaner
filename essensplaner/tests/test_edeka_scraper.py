from datetime import date
from pathlib import Path

from offers.edeka_scraper import _parse_offers_html

FIXTURE = (Path(__file__).parent / "fixtures" / "edeka_sample.html").read_text(encoding="utf-8")


def test_parse_offers_html_extracts_all_items():
    offers = _parse_offers_html(FIXTURE)
    assert len(offers) == 2

    assert offers[0].product_name == "Rispentomaten 500g"
    assert offers[0].price == 0.99
    assert offers[0].retailer == "edeka"
    assert offers[0].discount_text is None
    assert offers[0].description == "Kl. I, Schale"
    assert offers[0].valid_from == date(2026, 9, 7)
    assert offers[0].valid_until == date(2026, 9, 13)

    assert offers[1].product_name == "Hähnchenbrustfilet 400g"
    assert offers[1].price == 1.99
    assert offers[1].discount_text == "-25%"
    assert offers[1].description == "aus Deutschland"
    # Kachel überschreibt den Wochenstart ("Gültig ab 09.09.2026"), das
    # Wochenende bleibt bestehen.
    assert offers[1].valid_from == date(2026, 9, 9)
    assert offers[1].valid_until == date(2026, 9, 13)


def test_parse_offers_html_prefers_regular_price_over_app_price():
    # Kachel 2 hat zwei Preis-Einträge (App-Preis 1.29€, regulärer Preis
    # 1.99€ mit -25%) - der App-exklusive Preis darf nicht übernommen werden.
    offers = _parse_offers_html(FIXTURE)
    assert offers[1].price == 1.99


def test_parse_offers_html_skips_items_without_week_validity():
    html = """
    <article>
      <h4>
        <a data-dialog-action="open"><span class="sr-only">Angebot:</span>Ohne Datum</a>
      </h4>
    </article>
    """
    assert _parse_offers_html(html) == []
