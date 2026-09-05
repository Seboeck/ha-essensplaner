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


def test_find_matching_recipe_ids_via_artikel(client):
    from models import Recipe, Ingredient
    from offers.matching import find_matching_recipe_ids

    db = _db(client)
    gouda = _mk_artikel(db, "Gouda")
    recipe = Recipe(title="Käsebrot")
    db.add(recipe)
    db.commit()
    db.add(Ingredient(recipe_id=recipe.id, artikel_id=gouda.id, amount=200, unit="g"))
    db.commit()

    assert find_matching_recipe_ids("Gouda Scheiben 250g", db) == [recipe.id]
    assert find_matching_recipe_ids("Klopapier", db) == []


def test_is_watchlist_match_via_artikel(client):
    from models import FridgeStaple, WatchlistItem
    from offers.matching import is_watchlist_match

    db = _db(client)
    milch = _mk_artikel(db, "Milch")
    mehl = _mk_artikel(db, "Mehl")
    db.add(FridgeStaple(artikel_id=milch.id))
    db.add(WatchlistItem(artikel_id=mehl.id))
    db.commit()

    assert is_watchlist_match("Frische Milch 1L", db) is True
    assert is_watchlist_match("Weizenmehl Type 405", db) is True
    assert is_watchlist_match("Klopapier 8er Pack", db) is False
