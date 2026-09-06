from datetime import date, datetime


def _mk_artikel(db, name):
    from models import Artikel
    a = Artikel(name=name, created_at=datetime.utcnow().isoformat())
    db.add(a)
    db.commit()
    db.refresh(a)
    return a


def _mk_pending(db, artikel_id, product_name="Paprikapulver edelsüß", score=65.0):
    from models import PendingArtikelMatch
    p = PendingArtikelMatch(
        product_name=product_name, artikel_id=artikel_id, score=score, status="open",
        price=1.49, discount_text="-10%", retailer="kaufland", source="kaufland_scraper",
        valid_from=date.today(), valid_until=date.today(), created_at=datetime.utcnow().isoformat(),
    )
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


def _db(client):
    import database
    return database.SessionLocal()


def test_list_pending_matches_only_returns_open(client):
    db = _db(client)
    a = _mk_artikel(db, "Paprika rot")
    _mk_pending(db, a.id)

    res = client.get("/api/artikel/pending-matches")
    assert res.status_code == 200
    assert len(res.json()) == 1
    assert res.json()[0]["artikel_name"] == "Paprika rot"


def test_confirm_creates_price_history_and_closes_entry(client):
    from models import ArtikelPriceHistory
    db = _db(client)
    a = _mk_artikel(db, "Paprika rot")
    p = _mk_pending(db, a.id)

    res = client.post(f"/api/artikel/pending-matches/{p.id}/confirm")
    assert res.status_code == 200

    db2 = _db(client)
    history = db2.query(ArtikelPriceHistory).filter(ArtikelPriceHistory.artikel_id == a.id).all()
    assert len(history) == 1
    assert history[0].price == 1.49

    assert client.get("/api/artikel/pending-matches").json() == []


def test_reject_closes_entry_without_price_history(client):
    from models import ArtikelPriceHistory
    db = _db(client)
    a = _mk_artikel(db, "Paprika rot")
    p = _mk_pending(db, a.id)

    res = client.post(f"/api/artikel/pending-matches/{p.id}/reject")
    assert res.status_code == 200

    db2 = _db(client)
    assert db2.query(ArtikelPriceHistory).count() == 0
    assert client.get("/api/artikel/pending-matches").json() == []


def test_confirm_unknown_id_returns_404(client):
    assert client.post("/api/artikel/pending-matches/9999/confirm").status_code == 404


def test_confirm_twice_returns_409_and_does_not_duplicate_history(client):
    from models import ArtikelPriceHistory
    db = _db(client)
    a = _mk_artikel(db, "Paprika rot")
    p = _mk_pending(db, a.id)

    res1 = client.post(f"/api/artikel/pending-matches/{p.id}/confirm")
    assert res1.status_code == 200
    res2 = client.post(f"/api/artikel/pending-matches/{p.id}/confirm")
    assert res2.status_code == 409

    db2 = _db(client)
    history = db2.query(ArtikelPriceHistory).filter(ArtikelPriceHistory.artikel_id == a.id).all()
    assert len(history) == 1


def test_reject_after_confirm_returns_409(client):
    db = _db(client)
    a = _mk_artikel(db, "Paprika rot")
    p = _mk_pending(db, a.id)

    client.post(f"/api/artikel/pending-matches/{p.id}/confirm")
    res = client.post(f"/api/artikel/pending-matches/{p.id}/reject")
    assert res.status_code == 409


def test_confirm_rejects_other_open_candidates_for_same_product_name(client):
    db = _db(client)
    a1 = _mk_artikel(db, "Paprika rot")
    a2 = _mk_artikel(db, "Paprika grün")
    p1 = _mk_pending(db, a1.id, product_name="Paprikapulver")
    p2 = _mk_pending(db, a2.id, product_name="Paprikapulver")  # gleicher Produktname, anderer Kandidat

    res = client.post(f"/api/artikel/pending-matches/{p1.id}/confirm")
    assert res.status_code == 200

    db2 = _db(client)
    from models import PendingArtikelMatch
    refreshed_p2 = db2.query(PendingArtikelMatch).get(p2.id)
    assert refreshed_p2.status == "rejected"

    open_count = db2.query(PendingArtikelMatch).filter(
        PendingArtikelMatch.product_name == "Paprikapulver", PendingArtikelMatch.status == "open"
    ).count()
    assert open_count == 0
