from unittest.mock import patch
from datetime import date, timedelta
from offers.base import OfferData


def test_list_offers_empty_by_default(client):
    res = client.get("/api/offers")
    assert res.status_code == 200
    assert res.json() == []


def test_list_offers_sorts_watchlist_matches_first(client):
    client.post("/api/settings", json={"calendar_entity": "calendar.essensplan", "todo_entity": "todo.einkaufen", "plz": "12345"})
    client.post("/api/watchlist", json={"name": "Mehl"})

    fake_offers = [
        OfferData(retailer="kaufland", product_name="Klopapier 8er", valid_from=date.today(), valid_until=date.today() + timedelta(days=5)),
        OfferData(retailer="kaufland", product_name="Weizenmehl 1kg", valid_from=date.today(), valid_until=date.today() + timedelta(days=2)),
    ]
    with patch("offers.kaufland_scraper.fetch_offers", return_value=fake_offers):
        client.post("/api/offers/refresh/kaufland_scraper")

    res = client.get("/api/offers")
    assert res.status_code == 200
    body = res.json()
    assert len(body) == 2
    assert body[0]["product_name"] == "Weizenmehl 1kg"
    assert body[0]["matched_watchlist"] is True
    assert body[1]["matched_watchlist"] is False


def test_list_offers_filters_by_retailer_and_source(client):
    fake_offers = [OfferData(retailer="kaufland", product_name="Test", valid_from=date.today(), valid_until=date.today() + timedelta(days=5))]
    client.post("/api/settings", json={"calendar_entity": "calendar.essensplan", "todo_entity": "todo.einkaufen", "plz": "12345"})
    with patch("offers.kaufland_scraper.fetch_offers", return_value=fake_offers):
        client.post("/api/offers/refresh/kaufland_scraper")

    assert len(client.get("/api/offers?retailer=kaufland").json()) == 1
    assert len(client.get("/api/offers?retailer=edeka").json()) == 0
    assert len(client.get("/api/offers?source=kaufland_scraper").json()) == 1
    assert len(client.get("/api/offers?source=marktguru").json()) == 0


def test_list_offers_excludes_expired_offers(client):
    """Ein fehlgeschlagener Connector-Lauf lässt bewusst alte Zeilen stehen (siehe
    runner.py). GET /api/offers darf solche abgelaufenen Angebote trotzdem nicht
    mehr anzeigen, sonst wirken veraltete Daten wie aktuelle Angebote."""
    client.post("/api/settings", json={"calendar_entity": "calendar.essensplan", "todo_entity": "todo.einkaufen", "plz": "12345"})

    fake_offers = [
        OfferData(retailer="kaufland", product_name="Abgelaufen", valid_from=date.today() - timedelta(days=14),
                   valid_until=date.today() - timedelta(days=1)),
        OfferData(retailer="kaufland", product_name="Aktiv", valid_from=date.today(),
                   valid_until=date.today() + timedelta(days=5)),
    ]
    with patch("offers.kaufland_scraper.fetch_offers", return_value=fake_offers):
        client.post("/api/offers/refresh/kaufland_scraper")

    res = client.get("/api/offers")
    assert res.status_code == 200
    names = [o["product_name"] for o in res.json()]
    assert "Aktiv" in names
    assert "Abgelaufen" not in names
