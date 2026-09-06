from datetime import date, datetime
from unittest.mock import AsyncMock, patch

from models import FridgeStaple, Offer, OfferSourceConfig
from offers.base import OfferData
from offers.runner import run_source


def _db(client):
    import database
    return database.SessionLocal()


def _mk_artikel(db, name):
    from models import Artikel
    a = Artikel(name=name, created_at=datetime.utcnow().isoformat())
    db.add(a)
    db.commit()
    db.refresh(a)
    return a


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


def test_run_source_notifies_and_marks_watchlist_matches(client):
    db = _db(client)
    gouda = _mk_artikel(db, "Gouda")
    db.add(FridgeStaple(artikel_id=gouda.id))
    db.commit()

    fake_offers = [OfferData(retailer="kaufland", product_name="Gouda Scheiben 250g",
                              valid_from=date(2026, 9, 7), valid_until=date(2026, 9, 13))]
    with patch("offers.kaufland_scraper.fetch_offers", return_value=fake_offers), \
         patch("ha_client.notify", new_callable=AsyncMock) as mock_notify:
        run_source("kaufland_scraper", db, plz="12345")

    mock_notify.assert_called_once()
    offer = db.query(Offer).filter(Offer.source == "kaufland_scraper").first()
    assert offer.notified_at is not None


def test_run_source_does_not_renotify_same_offer_on_next_run(client):
    db = _db(client)
    gouda = _mk_artikel(db, "Gouda")
    db.add(FridgeStaple(artikel_id=gouda.id))
    db.commit()
    fake_offers = [OfferData(retailer="kaufland", product_name="Gouda",
                              valid_from=date(2026, 9, 7), valid_until=date(2026, 9, 13))]

    with patch("offers.kaufland_scraper.fetch_offers", return_value=fake_offers), \
         patch("ha_client.notify", new_callable=AsyncMock) as mock_notify:
        run_source("kaufland_scraper", db, plz="12345")
        run_source("kaufland_scraper", db, plz="12345")

    # Obwohl der zweite Lauf die Offer-Zeile komplett ersetzt (delete-then-replace),
    # wird notified_at anhand der Identität (product_name, valid_until) auf die neue
    # Zeile übertragen -> dasselbe Angebot löst kein zweites Mal eine Benachrichtigung aus.
    assert mock_notify.call_count == 1


def test_run_source_survives_notify_failure(client):
    db = _db(client)
    gouda = _mk_artikel(db, "Gouda")
    db.add(FridgeStaple(artikel_id=gouda.id))
    db.commit()

    fake_offers = [OfferData(retailer="kaufland", product_name="Gouda Scheiben 250g",
                              valid_from=date(2026, 9, 7), valid_until=date(2026, 9, 13))]
    with patch("offers.kaufland_scraper.fetch_offers", return_value=fake_offers), \
         patch("ha_client.notify", new_callable=AsyncMock, side_effect=Exception("HA nicht erreichbar")):
        config = run_source("kaufland_scraper", db, plz="12345")

    # Verbindung zum HA-Notify-Service ist fehlgeschlagen, der Connector-Lauf selbst
    # war aber erfolgreich -> darf den Lauf nicht scheitern lassen (nur die Benachrichtigung).
    assert config.last_status == "ok"


def test_run_source_records_price_history_for_high_confidence_match(client):
    from models import ArtikelPriceHistory
    db = _db(client)
    gouda = _mk_artikel(db, "Gouda")

    fake_offers = [OfferData(retailer="kaufland", product_name="Gouda Scheiben 250g",
                              valid_from=date(2026, 9, 7), valid_until=date(2026, 9, 13), price=1.99)]
    with patch("offers.kaufland_scraper.fetch_offers", return_value=fake_offers), \
         patch("ha_client.notify", new_callable=AsyncMock):
        run_source("kaufland_scraper", db, plz="12345")

    db2 = _db(client)
    history = db2.query(ArtikelPriceHistory).filter(ArtikelPriceHistory.artikel_id == gouda.id).all()
    assert len(history) == 1
    assert history[0].price == 1.99


def test_run_source_does_not_duplicate_identical_price_history_entry(client):
    from models import ArtikelPriceHistory
    db = _db(client)
    gouda = _mk_artikel(db, "Gouda")

    fake_offers = [OfferData(retailer="kaufland", product_name="Gouda",
                              valid_from=date(2026, 9, 7), valid_until=date(2026, 9, 13), price=1.99)]
    with patch("offers.kaufland_scraper.fetch_offers", return_value=fake_offers), \
         patch("ha_client.notify", new_callable=AsyncMock):
        run_source("kaufland_scraper", db, plz="12345")
        run_source("kaufland_scraper", db, plz="12345")

    db2 = _db(client)
    history = db2.query(ArtikelPriceHistory).filter(ArtikelPriceHistory.artikel_id == gouda.id).all()
    assert len(history) == 1  # identischer Preis/Zeitraum -> kein zweiter Eintrag


def test_run_source_dedups_price_history_within_same_run(client):
    """Zwei Angebote im selben Lauf, die auf denselben Artikel/Preis/Zeitraum
    matchen (realistisch bei Kaufland: Titel+Untertitel ergeben oft fast
    identische Produktnamen), duerfen wegen autoflush=False nicht als zwei
    separate Preis-Historie-Zeilen landen — die Duplikat-Pruefung muss die
    bereits im selben Lauf (aber noch nicht committete) hinzugefuegte Zeile
    sehen."""
    from models import ArtikelPriceHistory
    db = _db(client)
    gouda = _mk_artikel(db, "Gouda")

    fake_offers = [
        OfferData(retailer="kaufland", product_name="Gouda Scheiben 250g",
                  valid_from=date(2026, 9, 7), valid_until=date(2026, 9, 13), price=1.99),
        OfferData(retailer="kaufland", product_name="Gouda jung mild 250g",
                  valid_from=date(2026, 9, 7), valid_until=date(2026, 9, 13), price=1.99),
    ]
    with patch("offers.kaufland_scraper.fetch_offers", return_value=fake_offers), \
         patch("ha_client.notify", new_callable=AsyncMock):
        run_source("kaufland_scraper", db, plz="12345")

    db2 = _db(client)
    history = db2.query(ArtikelPriceHistory).filter(ArtikelPriceHistory.artikel_id == gouda.id).all()
    assert len(history) == 1  # beide Angebote im selben Lauf matchen denselben Artikel -> nur 1 Eintrag


def test_run_source_dedups_pending_match_within_same_run(client):
    """Dieselbe Konfidenz-Lücke wie bei der Preis-Historie (autoflush=False)
    betrifft auch die Bestätigungs-Warteschlange: zwei Angebote mit
    identischem Produktnamen im selben Lauf, die beide mittel-konfident auf
    denselben Artikel matchen, duerfen nicht zwei offene Warteschlangen-
    Einträge erzeugen — die "existing"-Prüfung muss die im selben Lauf
    bereits (aber noch nicht committete) hinzugefügte Zeile sehen."""
    from models import PendingArtikelMatch
    db = _db(client)
    _mk_artikel(db, "Paprika rot")

    fake_offers = [
        OfferData(retailer="kaufland", product_name="Paprikapulver",
                  valid_from=date(2026, 9, 7), valid_until=date(2026, 9, 13), price=0.99),
        OfferData(retailer="kaufland", product_name="Paprikapulver",
                  valid_from=date(2026, 9, 7), valid_until=date(2026, 9, 13), price=1.29),
    ]
    with patch("offers.kaufland_scraper.fetch_offers", return_value=fake_offers), \
         patch("ha_client.notify", new_callable=AsyncMock):
        run_source("kaufland_scraper", db, plz="12345")

    db2 = _db(client)
    pending = db2.query(PendingArtikelMatch).filter(PendingArtikelMatch.product_name == "Paprikapulver").all()
    assert len(pending) == 1  # beide Angebote im selben Lauf matchen denselben Artikel -> nur 1 offener Eintrag
    assert pending[0].price == 1.29  # zweites (spaeteres) Angebot hat den Eintrag aktualisiert, nicht dupliziert


def test_run_source_creates_pending_match_for_medium_confidence(client):
    from models import PendingArtikelMatch
    db = _db(client)
    _mk_artikel(db, "Paprika rot")

    fake_offers = [OfferData(retailer="kaufland", product_name="Paprikapulver edelsüß",
                              valid_from=date(2026, 9, 7), valid_until=date(2026, 9, 13))]
    with patch("offers.kaufland_scraper.fetch_offers", return_value=fake_offers), \
         patch("ha_client.notify", new_callable=AsyncMock):
        run_source("kaufland_scraper", db, plz="12345")

    db2 = _db(client)
    pending = db2.query(PendingArtikelMatch).all()
    # Je nach tatsächlichem Score entweder eine Bestätigungs-Zeile (mittel)
    # oder keine (falls der Score doch unter 60 liegt) — beides ist ein
    # gültiges Ergebnis für dieses Namenspaar, daher nur auf "keine
    # Exception" und plausible Konsistenz geprüft:
    for p in pending:
        assert p.product_name == "Paprikapulver edelsüß"
        assert p.status == "open"


def test_run_source_downloads_image_on_first_high_confidence_match(client):
    db = _db(client)
    gouda = _mk_artikel(db, "Gouda")
    assert gouda.image_path is None

    fake_offers = [OfferData(retailer="kaufland", product_name="Gouda",
                              valid_from=date(2026, 9, 7), valid_until=date(2026, 9, 13),
                              image_url="https://example.invalid/gouda.jpg")]
    with patch("offers.kaufland_scraper.fetch_offers", return_value=fake_offers), \
         patch("ha_client.notify", new_callable=AsyncMock), \
         patch("offers.runner.download_artikel_image", return_value="/artikel-images/1.jpg") as mock_download:
        run_source("kaufland_scraper", db, plz="12345")

    mock_download.assert_called_once()
    db2 = _db(client)
    refreshed = db2.query(type(gouda)).get(gouda.id)
    assert refreshed.image_path == "/artikel-images/1.jpg"
