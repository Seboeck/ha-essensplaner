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


def test_create_recipe_with_artikel_id(client):
    db = _db(client)
    gouda = _mk_artikel(db, "Gouda")

    res = client.post("/api/recipes", json={
        "title": "Käsebrot",
        "ingredients": [{"artikel_id": gouda.id, "amount": 200, "unit": "g"}],
    })
    assert res.status_code == 200
    body = res.json()
    assert body["ingredients"][0]["artikel_id"] == gouda.id
    assert body["ingredients"][0]["name"] == "Gouda"


def test_create_recipe_rejects_unknown_artikel_id(client):
    res = client.post("/api/recipes", json={
        "title": "Käsebrot",
        "ingredients": [{"artikel_id": 9999, "amount": 200, "unit": "g"}],
    })
    assert res.status_code == 400


def test_update_recipe_replaces_ingredients(client):
    db = _db(client)
    gouda = _mk_artikel(db, "Gouda")
    mehl = _mk_artikel(db, "Mehl")

    create_res = client.post("/api/recipes", json={
        "title": "Käsebrot", "ingredients": [{"artikel_id": gouda.id, "amount": 200, "unit": "g"}],
    })
    recipe_id = create_res.json()["id"]

    update_res = client.put(f"/api/recipes/{recipe_id}", json={
        "title": "Käsebrot", "ingredients": [{"artikel_id": mehl.id, "amount": 500, "unit": "g"}],
    })
    assert update_res.status_code == 200
    assert len(update_res.json()["ingredients"]) == 1
    assert update_res.json()["ingredients"][0]["name"] == "Mehl"


def test_list_recipes_includes_ingredient_names(client):
    db = _db(client)
    gouda = _mk_artikel(db, "Gouda")
    client.post("/api/recipes", json={
        "title": "Käsebrot", "ingredients": [{"artikel_id": gouda.id, "amount": 200, "unit": "g"}],
    })
    res = client.get("/api/recipes")
    assert res.json()[0]["ingredients"][0]["name"] == "Gouda"
