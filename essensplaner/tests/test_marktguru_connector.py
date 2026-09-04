import json
from datetime import date
from pathlib import Path

import httpx
import pytest

from offers import marktguru_connector
from offers.marktguru_connector import (
    _SEARCH_TERMS,
    _compute_discount_text,
    _parse_response,
    _parse_validity,
    fetch_offers,
)

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "marktguru_sample.json").read_text(encoding="utf-8"))


class _FakeJsonResponse:
    def __init__(self, payload: dict):
        self._payload = payload

    def raise_for_status(self) -> None:
        pass

    def json(self) -> dict:
        return self._payload


def _single_offer_payload(offer_id: int, uniqueName: str = "kaufland") -> dict:
    return {
        "results": [
            {
                "id": offer_id,
                "description": "Testangebot",
                "price": 1.0,
                "oldPrice": None,
                "advertisers": [{"uniqueName": uniqueName, "id": "retailers/x", "name": uniqueName}],
                "product": {"id": offer_id, "name": f"Produkt {offer_id}"},
                "validityDates": [{"from": "2026-09-06T22:00:00Z", "to": "2026-09-12T21:59:59Z"}],
            }
        ]
    }


def test_parse_response_filters_to_kaufland_and_edeka():
    offers = _parse_response(FIXTURE)
    retailers = {o.retailer for o in offers}
    assert retailers == {"edeka", "kaufland"}
    # Vier Roh-Angebote in der Fixture: REWE wird gefiltert, eines ohne
    # validityDates wird verworfen -> zwei übrig.
    assert len(offers) == 2


def test_parse_response_parses_price_and_discount():
    offers = _parse_response(FIXTURE)
    butter = next(o for o in offers if o.product_name == "Butter 250g")
    assert butter.price == 1.49
    assert butter.discount_text == "-15%"
    assert butter.retailer == "edeka"
    assert butter.valid_from == date(2026, 9, 6)
    assert butter.valid_until == date(2026, 9, 12)


def test_parse_response_skips_offers_without_validity_dates():
    offers = _parse_response(FIXTURE)
    assert all(o.product_name != "Ohne Datum" for o in offers)


def test_compute_discount_text_returns_none_without_old_price():
    assert _compute_discount_text(4.99, None) is None
    assert _compute_discount_text(4.99, 0) is None


def test_compute_discount_text_returns_none_when_not_actually_cheaper():
    assert _compute_discount_text(5.0, 4.0) is None


def test_compute_discount_text_rounds_percentage():
    assert _compute_discount_text(1.49, 1.75) == "-15%"


def test_parse_validity_uses_only_first_entry_and_drops_time():
    result = _parse_validity([
        {"from": "2026-09-06T22:00:00Z", "to": "2026-09-12T21:59:59Z"},
        {"from": "2026-09-13T22:00:00Z", "to": "2026-09-19T21:59:59Z"},
    ])
    assert result == (date(2026, 9, 6), date(2026, 9, 12))


def test_parse_validity_returns_none_for_empty_list():
    assert _parse_validity([]) is None
    assert _parse_validity(None) is None


def test_fetch_offers_merges_results_when_all_terms_succeed(monkeypatch):
    monkeypatch.setattr(marktguru_connector, "_get_api_keys", lambda: ("key", "clientkey"))

    def fake_get(url, headers=None, params=None, timeout=None):
        term = params["q"]
        offer_id = 1000 + _SEARCH_TERMS.index(term)
        return _FakeJsonResponse(_single_offer_payload(offer_id))

    monkeypatch.setattr(marktguru_connector.httpx, "get", fake_get)

    offers = fetch_offers("10115")
    # Ein Angebot pro Suchbegriff, alle mit unterschiedlicher id -> keine Dedup-Kollision.
    assert len(offers) == len(_SEARCH_TERMS)
    assert all(o.retailer == "kaufland" for o in offers)


def test_fetch_offers_returns_partial_results_when_some_terms_fail(monkeypatch):
    monkeypatch.setattr(marktguru_connector, "_get_api_keys", lambda: ("key", "clientkey"))

    def fake_get(url, headers=None, params=None, timeout=None):
        term = params["q"]
        if term == _SEARCH_TERMS[0]:
            raise httpx.TimeoutException("timed out")
        if term == _SEARCH_TERMS[1]:
            request = httpx.Request("GET", url)
            response = httpx.Response(503, request=request)
            raise httpx.HTTPStatusError("server error", request=request, response=response)
        offer_id = 2000 + _SEARCH_TERMS.index(term)
        return _FakeJsonResponse(_single_offer_payload(offer_id))

    monkeypatch.setattr(marktguru_connector.httpx, "get", fake_get)

    offers = fetch_offers("10115")
    # Zwei von len(_SEARCH_TERMS) Begriffen fehlgeschlagen - die restlichen
    # Treffer müssen trotzdem zurückkommen (graceful degradation), kein Raise.
    assert len(offers) == len(_SEARCH_TERMS) - 2


def test_fetch_offers_raises_when_all_terms_fail(monkeypatch):
    monkeypatch.setattr(marktguru_connector, "_get_api_keys", lambda: ("key", "clientkey"))

    def fake_get(url, headers=None, params=None, timeout=None):
        raise httpx.TimeoutException("timed out")

    monkeypatch.setattr(marktguru_connector.httpx, "get", fake_get)

    with pytest.raises(RuntimeError, match=f"{len(_SEARCH_TERMS)} von {len(_SEARCH_TERMS)}"):
        fetch_offers("10115")
