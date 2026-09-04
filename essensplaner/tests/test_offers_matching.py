from models import Recipe, Ingredient, FridgeStaple, WatchlistItem
from offers.matching import match_score, find_matching_recipe_ids, is_watchlist_match


def _db(client):
    import database
    return database.SessionLocal()


def test_match_score_tolerates_extra_words():
    # token_set_ratio treats "Gouda Scheiben 250g" and "Gouda" as high match
    # since "Gouda" tokens are a subset of the product name tokens
    assert match_score("Gouda Scheiben 250g", "Gouda") > 90


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
    # token_set_ratio needs "Mehl" as a separate token to match
    assert is_watchlist_match("Mehl Weizenmehl Type 405 1kg", db) is True
    assert is_watchlist_match("Klopapier 8er Pack", db) is False


def test_no_false_positives_unrelated_words(client):
    # Regression test: ensure unrelated product names don't match at threshold=80
    # with token_set_ratio (unlike token_sort_ratio with low threshold)
    db = _db(client)
    db.add(FridgeStaple(name="Käse"))
    db.commit()

    # These clearly unrelated products should NOT match "Käse" at threshold=80
    assert is_watchlist_match("Kaffee 500g", db) is False
    assert is_watchlist_match("Paprika rot gemahlen", db) is False
    assert match_score("Kaffee", "Käse") < 80
    assert match_score("Paprika rot", "Pizza") < 80
