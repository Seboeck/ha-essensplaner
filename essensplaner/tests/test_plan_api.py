from unittest.mock import AsyncMock, patch


def test_swap_day_rejects_unknown_recipe_id(client):
    from datetime import date
    from models import PlanEntry, Recipe
    import database
    db = database.SessionLocal()
    recipe = Recipe(title="Original")
    db.add(recipe)
    db.commit()
    recipe_id = recipe.id
    db.add(PlanEntry(date=date.today(), recipe_id=recipe_id))
    db.commit()
    db.close()

    with patch("ha_client._post", new_callable=AsyncMock), \
         patch("ha_client._get", new_callable=AsyncMock, return_value=[]):
        res = client.put(f"/api/plan/{date.today().isoformat()}?recipe_id=999999")
    assert res.status_code == 404

    db2 = database.SessionLocal()
    entry = db2.query(PlanEntry).filter(PlanEntry.date == date.today()).first()
    assert entry.recipe_id == recipe_id  # unveraendert
    db2.close()


def test_swap_day_updates_recipe_and_syncs_calendar(client):
    from datetime import date
    from models import PlanEntry, Recipe
    import database
    db = database.SessionLocal()
    original = Recipe(title="Original")
    neu = Recipe(title="Neues Gericht")
    db.add_all([original, neu])
    db.commit()
    db.add(PlanEntry(date=date.today(), recipe_id=original.id))
    db.commit()
    neu_id = neu.id
    db.close()

    with patch("ha_client._post", new_callable=AsyncMock) as mock_post, \
         patch("ha_client._get", new_callable=AsyncMock, return_value=[]):
        res = client.put(f"/api/plan/{date.today().isoformat()}?recipe_id={neu_id}")
    assert res.status_code == 200
    mock_post.assert_called()

    db2 = database.SessionLocal()
    entry = db2.query(PlanEntry).filter(PlanEntry.date == date.today()).first()
    assert entry.recipe_id == neu_id
    db2.close()


def test_swap_day_rejects_invalid_date(client):
    res = client.put("/api/plan/nicht-ein-datum?recipe_id=1")
    assert res.status_code == 422


def test_sqlite_foreign_keys_are_enforced(client):
    """Stellt sicher, dass PRAGMA foreign_keys=ON tatsaechlich aktiv ist
    (nicht nur im Code steht) - versucht eine Zeile mit ungueltigem
    Fremdschluessel direkt einzufuegen und erwartet einen Fehler."""
    import database
    import pytest
    from sqlalchemy.exc import IntegrityError
    from models import PlanEntry
    from datetime import date
    db = database.SessionLocal()
    db.add(PlanEntry(date=date.today(), recipe_id=999999))
    with pytest.raises(IntegrityError):
        db.commit()
    db.close()


def test_get_plan_excludes_entries_from_following_week(client):
    from datetime import date, timedelta
    from models import Recipe, PlanEntry
    import database
    db = database.SessionLocal()
    recipe = Recipe(title="Testgericht")
    db.add(recipe)
    db.commit()

    start = date.today()
    db.add(PlanEntry(date=start, recipe_id=recipe.id))  # Tag 1 dieser Woche
    db.add(PlanEntry(date=start + timedelta(days=9), recipe_id=recipe.id))  # ausserhalb der 7-Tage-Spanne
    db.commit()
    db.close()

    res = client.get(f"/api/plan?start={start.isoformat()}")
    assert res.status_code == 200
    dates = [e["date"] for e in res.json()]
    assert start.isoformat() in dates
    assert (start + timedelta(days=9)).isoformat() not in dates


def test_get_plan_rejects_invalid_date(client):
    res = client.get("/api/plan?start=nicht-ein-datum")
    assert res.status_code == 422


def test_push_shopping_list_excludes_entries_from_following_week(client):
    from datetime import date, timedelta
    from models import Recipe, PlanEntry, Ingredient, Artikel
    import database
    db = database.SessionLocal()
    artikel = Artikel(name="Testzutat", created_at="2026-01-01T00:00:00")
    db.add(artikel)
    db.commit()
    recipe = Recipe(title="Testgericht")
    db.add(recipe)
    db.commit()
    db.add(Ingredient(recipe_id=recipe.id, artikel_id=artikel.id, amount=1, unit="Stk"))
    db.commit()

    start = date.today()
    db.add(PlanEntry(date=start, recipe_id=recipe.id))
    db.add(PlanEntry(date=start + timedelta(days=9), recipe_id=recipe.id))
    db.commit()
    db.close()

    with patch("ha_client._post", new_callable=AsyncMock):
        res = client.post(f"/api/shopping-list/push?start={start.isoformat()}")
    assert res.status_code == 200
    # nur der Eintrag innerhalb der Woche darf zur Zutaten-Aggregation beitragen -
    # waere der Eintrag ausserhalb der Woche mitgezaehlt, stuende hier "2 Stk ...".
    assert res.json()["items_added"] == ["1 stk Testzutat"]
