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


def test_export_returns_artikel_names_as_freetext(client):
    db = _db(client)
    gouda = _mk_artikel(db, "Gouda")
    create_res = client.post("/api/recipes", json={
        "title": "Käsebrot", "ingredients": [{"artikel_id": gouda.id, "amount": 200, "unit": "g"}],
    })
    recipe_id = create_res.json()["id"]

    res = client.get(f"/api/recipes/{recipe_id}/export")
    assert res.status_code == 200
    assert res.json()["recipes"][0]["ingredients"][0]["name"] == "Gouda"


def test_import_apply_auto_creates_artikel_for_new_ingredient_name(client):
    res = client.post("/api/recipes/import/apply", json={
        "recipes": [{
            "title": "Neues Rezept",
            "ingredients": [{"name": "Brandneue Zutat", "amount": 1, "unit": "Stück"}],
        }],
        "resolutions": [],
    })
    assert res.status_code == 200
    assert res.json()["imported"] == 1

    from models import Artikel
    db = _db(client)
    assert db.query(Artikel).filter(Artikel.name == "Brandneue Zutat").first() is not None


def test_import_apply_links_high_confidence_existing_artikel(client):
    db = _db(client)
    gouda = _mk_artikel(db, "Gouda")

    res = client.post("/api/recipes/import/apply", json={
        "recipes": [{
            "title": "Käsebrot",
            "ingredients": [{"name": "Gouda Scheiben", "amount": 200, "unit": "g"}],
        }],
        "resolutions": [],
    })
    assert res.status_code == 200

    from models import Ingredient
    db2 = _db(client)
    ingredient = db2.query(Ingredient).first()
    assert ingredient.artikel_id == gouda.id


def test_import_preview_reports_medium_confidence_ambiguity(client):
    db = _db(client)
    _mk_artikel(db, "Paprika rot")

    res = client.post("/api/recipes/import/preview", json={
        "recipes": [{
            "title": "Auflauf",
            "ingredients": [{"name": "Paprikapulver edelsüß", "amount": 1, "unit": "TL"}],
        }],
    })
    assert res.status_code == 200
    body = res.json()
    if body["ingredient_ambiguities"]:
        assert body["ingredient_ambiguities"][0]["ingredient_name"] == "Paprikapulver edelsüß"


def test_import_apply_respects_explicit_ingredient_resolution(client):
    db = _db(client)
    keep = _mk_artikel(db, "Paprika rot")
    other = _mk_artikel(db, "Paprika grün")

    res = client.post("/api/recipes/import/apply", json={
        "recipes": [{
            "title": "Auflauf",
            "ingredients": [{"name": "Paprika", "amount": 1, "unit": "Stück"}],
        }],
        "resolutions": [],
        "ingredient_resolutions": [{"recipe_index": 0, "ingredient_index": 0, "artikel_id": keep.id}],
    })
    assert res.status_code == 200

    from models import Ingredient
    db2 = _db(client)
    ingredient = db2.query(Ingredient).first()
    assert ingredient.artikel_id == keep.id
