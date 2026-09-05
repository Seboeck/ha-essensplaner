from datetime import datetime


def _mk_artikel(db, name):
    from models import Artikel
    a = Artikel(name=name, created_at=datetime.utcnow().isoformat())
    db.add(a)
    db.commit()
    db.refresh(a)
    return a


def _db(client):
    import database
    return database.SessionLocal()


def test_create_and_list_artikel(client):
    res = client.post("/api/artikel", json={"name": "Gouda"})
    assert res.status_code == 200
    assert res.json()["name"] == "Gouda"

    res = client.get("/api/artikel")
    assert len(res.json()) == 1


def test_create_artikel_rejects_empty_name(client):
    res = client.post("/api/artikel", json={"name": "   "})
    assert res.status_code == 400


def test_get_artikel_404_for_unknown_id(client):
    assert client.get("/api/artikel/9999").status_code == 404


def test_history_reflects_price_entries(client):
    db = _db(client)
    a = _mk_artikel(db, "Gouda")
    from models import ArtikelPriceHistory
    from datetime import date
    db.add(ArtikelPriceHistory(
        artikel_id=a.id, price=1.99, discount_text="-20%", retailer="kaufland",
        source="kaufland_scraper", valid_from=date.today(), valid_until=date.today(),
        recorded_at=datetime.utcnow().isoformat(),
    ))
    db.commit()

    res = client.get(f"/api/artikel/{a.id}/history")
    assert res.status_code == 200
    body = res.json()
    assert len(body) == 1
    assert body[0]["price"] == 1.99

    res = client.get(f"/api/artikel/{a.id}")
    assert res.json()["last_price"] == 1.99


def test_suggest_returns_high_confidence_single_result(client):
    db = _db(client)
    _mk_artikel(db, "Gouda")
    res = client.get("/api/artikel/suggest?q=Gouda")
    assert res.status_code == 200
    body = res.json()
    assert len(body) == 1
    assert body[0]["confidence"] == "high"


def test_suggest_returns_empty_for_blank_query(client):
    res = client.get("/api/artikel/suggest?q=")
    assert res.status_code == 200
    assert res.json() == []


def test_merge_repoints_fridge_staple_and_deletes_source(client):
    db = _db(client)
    keep = _mk_artikel(db, "Gouda")
    drop = _mk_artikel(db, "Gouda jung")
    from models import FridgeStaple
    db.add(FridgeStaple(artikel_id=drop.id, unit="Stück"))
    db.commit()

    res = client.post(f"/api/artikel/{keep.id}/merge/{drop.id}")
    assert res.status_code == 200

    db2 = _db(client)
    staple = db2.query(FridgeStaple).first()
    assert staple.artikel_id == keep.id
    assert db2.query(type(keep)).filter(type(keep).id == drop.id).first() is None


def test_merge_rejects_self_merge(client):
    db = _db(client)
    a = _mk_artikel(db, "Gouda")
    res = client.post(f"/api/artikel/{a.id}/merge/{a.id}")
    assert res.status_code == 400
