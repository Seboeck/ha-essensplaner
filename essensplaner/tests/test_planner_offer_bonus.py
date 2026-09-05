from datetime import date, datetime, timedelta
from models import Recipe, Ingredient, Offer
from planner import generate_week_plan, OFFER_WEIGHT_BONUS


def _db(client):
    import database
    return database.SessionLocal()


def _mk_artikel(db, name):
    from models import Artikel
    a = Artikel(name=name, created_at=datetime.utcnow().isoformat())
    db.add(a)
    db.commit()
    db.refresh(a)
    return a


def test_recipe_with_active_offer_ingredient_gets_weight_bonus(client):
    db = _db(client)
    plain = Recipe(title="Ohne Angebot")
    with_offer = Recipe(title="Mit Angebot")
    db.add_all([plain, with_offer])
    db.commit()
    gouda = _mk_artikel(db, "Gouda")
    db.add(Ingredient(recipe_id=with_offer.id, artikel_id=gouda.id, amount=200, unit="g"))
    db.add(Offer(
        retailer="kaufland", source="kaufland_scraper", product_name="Gouda Scheiben",
        valid_from=date.today(), valid_until=date.today() + timedelta(days=3),
        scraped_at=date.today().isoformat(),
    ))
    db.commit()

    import random
    random.seed(1)
    entries = generate_week_plan(db, date.today())
    # Kein deterministischer Ausgang bei zufälliger Auswahl -> stattdessen die
    # Gewichts-Hilfsfunktion direkt prüfen:
    from planner import _recipe_ids_with_active_offer
    assert with_offer.id in _recipe_ids_with_active_offer(db)
    assert plain.id not in _recipe_ids_with_active_offer(db)
    assert len(entries) == 7


def test_expired_offer_gives_no_bonus(client):
    db = _db(client)
    recipe = Recipe(title="Testgericht")
    db.add(recipe)
    db.commit()
    gouda = _mk_artikel(db, "Gouda")
    db.add(Ingredient(recipe_id=recipe.id, artikel_id=gouda.id, amount=200, unit="g"))
    db.add(Offer(
        retailer="kaufland", source="kaufland_scraper", product_name="Gouda Scheiben",
        valid_from=date.today() - timedelta(days=10), valid_until=date.today() - timedelta(days=3),
        scraped_at=date.today().isoformat(),
    ))
    db.commit()

    from planner import _recipe_ids_with_active_offer
    assert recipe.id not in _recipe_ids_with_active_offer(db)
