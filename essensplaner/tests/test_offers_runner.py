from datetime import date
from unittest.mock import patch

from models import Offer, OfferSourceConfig
from offers.base import OfferData
from offers.runner import run_source


def _db(client):
    import database
    return database.SessionLocal()


def test_run_source_persists_offers_and_marks_ok(client):
    db = _db(client)
    fake_offers = [
        OfferData(retailer="kaufland", product_name="Testartikel",
                   valid_from=date(2026, 9, 7), valid_until=date(2026, 9, 13), price=1.0)
    ]
    with patch("offers.kaufland_scraper.fetch_offers", return_value=fake_offers):
        config = run_source("kaufland_scraper", db, plz="12345")

    assert config.last_status == "ok"
    offers = db.query(Offer).filter(Offer.source == "kaufland_scraper").all()
    assert len(offers) == 1
    assert offers[0].product_name == "Testartikel"


def test_run_source_replaces_previous_offers_of_same_source(client):
    db = _db(client)
    old_offers = [OfferData(retailer="kaufland", product_name="Alt",
                             valid_from=date(2026, 9, 1), valid_until=date(2026, 9, 6))]
    new_offers = [OfferData(retailer="kaufland", product_name="Neu",
                             valid_from=date(2026, 9, 7), valid_until=date(2026, 9, 13))]

    with patch("offers.kaufland_scraper.fetch_offers", return_value=old_offers):
        run_source("kaufland_scraper", db, plz="12345")
    with patch("offers.kaufland_scraper.fetch_offers", return_value=new_offers):
        run_source("kaufland_scraper", db, plz="12345")

    names = [o.product_name for o in db.query(Offer).filter(Offer.source == "kaufland_scraper").all()]
    assert names == ["Neu"]


def test_run_source_records_failure_without_raising(client):
    db = _db(client)
    with patch("offers.kaufland_scraper.fetch_offers", side_effect=RuntimeError("Seite nicht erreichbar")):
        config = run_source("kaufland_scraper", db, plz="12345")

    assert "Fehler" in config.last_status
    assert db.query(Offer).filter(Offer.source == "kaufland_scraper").count() == 0


def test_run_source_unknown_source_raises(client):
    import pytest
    db = _db(client)
    with pytest.raises(ValueError):
        run_source("unknown_source", db, plz="12345")
