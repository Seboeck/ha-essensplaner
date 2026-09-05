from datetime import date
from pathlib import Path

import pytest

from offers import edeka_scraper
from offers.edeka_scraper import _parse_offers_html, _resolve_store_offers_url

FIXTURE = (Path(__file__).parent / "fixtures" / "edeka_sample.html").read_text(encoding="utf-8")
STORE_SEARCH_FIXTURE = (
    Path(__file__).parent / "fixtures" / "edeka_store_search_sample.html"
).read_text(encoding="utf-8")


class _FakeResponse:
    def __init__(self, text: str):
        self.text = text

    def raise_for_status(self) -> None:
        pass


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


def test_resolve_store_offers_url_ignores_link_outside_results_container(monkeypatch):
    # Regression test for a bug where the store link was found via
    # regex-search over the ENTIRE raw page text, which could match an
    # unrelated link (e.g. a "Mein Markt" shortcut in the header) that
    # happens to appear before the actual search-results list in source
    # order. The fixture places exactly such a decoy link before
    # `#results-wrapper`, pointing at store 999999, while the real search
    # result for the PLZ is store 402574 inside the results container.
    monkeypatch.setattr(edeka_scraper.httpx, "get", lambda *a, **k: _FakeResponse(STORE_SEARCH_FIXTURE))
    url = _resolve_store_offers_url("10115")
    assert url == "https://www.edeka.de/maerkte/402574/angebote"


def test_resolve_store_offers_url_raises_when_results_container_missing(monkeypatch):
    monkeypatch.setattr(
        edeka_scraper.httpx, "get", lambda *a, **k: _FakeResponse("<html><body>keine Trefferliste hier</body></html>")
    )
    with pytest.raises(ValueError, match="Trefferlisten-Container"):
        _resolve_store_offers_url("10115")
