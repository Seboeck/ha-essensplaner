from unittest.mock import patch
from datetime import date

from offers.base import OfferData


def test_list_offer_sources_returns_all_three(client):
    res = client.get("/api/offers/sources")
    assert res.status_code == 200
    sources = {s["source"] for s in res.json()}
    assert sources == {"kaufland_scraper", "edeka_scraper", "marktguru"}


def test_update_offer_source_toggles_enabled(client):
    res = client.put("/api/offers/sources/marktguru", json={"enabled": False})
    assert res.status_code == 200
    assert res.json()["enabled"] is False


def test_refresh_requires_plz(client):
    res = client.post("/api/offers/refresh/kaufland_scraper")
    assert res.status_code == 400


def test_refresh_runs_connector(client):
    client.post("/api/settings", json={"calendar_entity": "calendar.essensplan", "todo_entity": "todo.einkaufen", "plz": "12345"})
    fake_offers = [OfferData(retailer="kaufland", product_name="Test", valid_from=date(2026, 9, 7), valid_until=date(2026, 9, 13))]
    with patch("offers.kaufland_scraper.fetch_offers", return_value=fake_offers):
        res = client.post("/api/offers/refresh/kaufland_scraper")
    assert res.status_code == 200
    assert res.json()["last_status"] == "ok"


def test_refresh_unknown_source_returns_404(client):
    res = client.post("/api/offers/refresh/unknown")
    assert res.status_code == 404
