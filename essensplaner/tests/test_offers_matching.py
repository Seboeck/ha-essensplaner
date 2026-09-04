from models import Recipe, Ingredient, FridgeStaple, WatchlistItem
from offers.matching import match_score, find_matching_recipe_ids, is_watchlist_match


def _db(client):
    import database
    return database.SessionLocal()


def test_match_score_tolerates_extra_words():
    assert match_score("Gouda Scheiben 250g", "Gouda") > 35


def test_find_matching_recipe_ids(client):
    db = _db(client)
    recipe = Recipe(title="Käsebrot")
    db.add(recipe)
    db.commit()
    db.add(Ingredient(recipe_id=recipe.id, name="Gouda", amount=200, unit="g"))
    db.commit()

    result = find_matching_recipe_ids("Gouda Scheiben 250g Angebot", db)
    assert result == [recipe.id]

    result_no_match = find_matching_recipe_ids("Klopapier", db)
    assert result_no_match == []


def test_is_watchlist_match_checks_staples_and_watchlist(client):
    db = _db(client)
    db.add(FridgeStaple(name="Milch"))
    db.add(WatchlistItem(name="Mehl"))
    db.commit()

    assert is_watchlist_match("Frische Milch 1L", db) is True
    assert is_watchlist_match("Weizenmehl Type 405", db) is True
    assert is_watchlist_match("Klopapier 8er Pack", db) is False
