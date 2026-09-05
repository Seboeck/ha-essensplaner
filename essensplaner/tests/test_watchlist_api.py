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


def test_watchlist_crud(client):
    db = _db(client)
    mehl = _mk_artikel(db, "Mehl")

    res = client.post("/api/watchlist", json={"artikel_id": mehl.id, "unit": "kg"})
    assert res.status_code == 200
    item = res.json()
    assert item["name"] == "Mehl"

    res = client.get("/api/watchlist")
    assert res.status_code == 200
    assert len(res.json()) == 1

    res = client.delete(f"/api/watchlist/{item['id']}")
    assert res.status_code == 200
    assert client.get("/api/watchlist").json() == []


def test_watchlist_rejects_unknown_artikel(client):
    res = client.post("/api/watchlist", json={"artikel_id": 9999})
    assert res.status_code == 400


def test_remove_unknown_watchlist_item_returns_404(client):
    res = client.delete("/api/watchlist/9999")
    assert res.status_code == 404
