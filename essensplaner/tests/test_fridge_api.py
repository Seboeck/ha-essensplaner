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


def test_fridge_item_upsert_and_list(client):
    db = _db(client)
    gouda = _mk_artikel(db, "Gouda")

    res = client.post("/api/fridge/items", json={"artikel_id": gouda.id, "amount": 1, "unit": "Stück"})
    assert res.status_code == 200
    assert res.json()["name"] == "Gouda"

    res = client.get("/api/fridge")
    assert len(res.json()) == 1
    assert res.json()[0]["in_stock"] is True


def test_fridge_item_rejects_unknown_artikel(client):
    res = client.post("/api/fridge/items", json={"artikel_id": 9999})
    assert res.status_code == 400


def test_staple_without_stock_shows_as_missing(client):
    db = _db(client)
    mehl = _mk_artikel(db, "Mehl")
    client.post("/api/fridge/staples", json={"artikel_id": mehl.id, "unit": "kg"})

    res = client.get("/api/fridge")
    body = res.json()
    assert len(body) == 1
    assert body[0]["is_staple"] is True
    assert body[0]["in_stock"] is False


def test_unmark_staple_by_artikel_id(client):
    db = _db(client)
    mehl = _mk_artikel(db, "Mehl")
    client.post("/api/fridge/staples", json={"artikel_id": mehl.id, "unit": "kg"})

    res = client.delete(f"/api/fridge/staples/by-artikel/{mehl.id}")
    assert res.status_code == 200
    assert client.get("/api/fridge").json() == []
