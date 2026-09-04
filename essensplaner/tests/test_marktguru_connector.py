import json
from datetime import date
from pathlib import Path

from offers.marktguru_connector import _compute_discount_text, _parse_response, _parse_validity

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "marktguru_sample.json").read_text(encoding="utf-8"))


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
