def test_delete_recipe_removes_orphaned_plan_entries(client):
    from datetime import date
    from models import PlanEntry
    res = client.post("/api/recipes", json={"title": "Löschtest", "base_servings": 4, "ingredients": []})
    assert res.status_code == 200
    recipe_id = res.json()["id"]

    import database
    db = database.SessionLocal()
    db.add(PlanEntry(date=date.today(), recipe_id=recipe_id))
    db.commit()
    db.close()

    res = client.delete(f"/api/recipes/{recipe_id}")
    assert res.status_code == 200

    db2 = database.SessionLocal()
    assert db2.query(PlanEntry).filter(PlanEntry.recipe_id == recipe_id).count() == 0
    db2.close()
