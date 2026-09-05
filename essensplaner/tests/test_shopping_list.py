from datetime import date, datetime


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


def test_aggregate_shopping_list_sums_by_artikel_and_unit(client):
    from models import Recipe, Ingredient, PlanEntry
    from planner import aggregate_shopping_list

    db = _db(client)
    gouda = _mk_artikel(db, "Gouda")
    r1 = Recipe(title="Rezept 1")
    r2 = Recipe(title="Rezept 2")
    db.add_all([r1, r2])
    db.commit()
    db.add(Ingredient(recipe_id=r1.id, artikel_id=gouda.id, amount=100, unit="g"))
    db.add(Ingredient(recipe_id=r2.id, artikel_id=gouda.id, amount=150, unit="g"))
    db.commit()

    e1 = PlanEntry(date=date.today(), recipe_id=r1.id)
    e2 = PlanEntry(date=date(2026, 1, 1), recipe_id=r2.id)
    db.add_all([e1, e2])
    db.commit()

    items = aggregate_shopping_list(db, [e1, e2])
    assert items == ["250 g Gouda"]


def test_aggregate_shopping_list_lists_unitless_separately(client):
    from models import Recipe, Ingredient, PlanEntry
    from planner import aggregate_shopping_list

    db = _db(client)
    salz = _mk_artikel(db, "Salz")
    r1 = Recipe(title="Rezept 1")
    db.add(r1)
    db.commit()
    db.add(Ingredient(recipe_id=r1.id, artikel_id=salz.id, amount=None, unit=None))
    db.commit()

    e1 = PlanEntry(date=date.today(), recipe_id=r1.id)
    db.add(e1)
    db.commit()

    assert aggregate_shopping_list(db, [e1]) == ["Salz"]
