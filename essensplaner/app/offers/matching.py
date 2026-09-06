"""Fuzzy-Matching zwischen Angebots-Produktnamen und Rezept-Zutaten /
Merklisten-Artikeln. Nutzt zentral resolve_artikel() (siehe
app/artikel_matching.py) — nur Angebote mit hoher Konfidenz zu einem
bestehenden Artikel gelten als Treffer; mittlere Konfidenz landet
stattdessen in der Bestätigungs-Warteschlange (siehe offers/runner.py,
Task 10)."""
from sqlalchemy.orm import Session

from models import Ingredient, FridgeStaple, WatchlistItem
from artikel_matching import resolve_artikel


def find_matching_recipe_ids(product_name: str, db: Session) -> list[int]:
    match = resolve_artikel(product_name, db)
    if match.confidence != "high":
        return []
    return sorted({
        i.recipe_id for i in db.query(Ingredient).filter(Ingredient.artikel_id == match.artikel.id).all()
    })


def is_watchlist_match(product_name: str, db: Session) -> bool:
    match = resolve_artikel(product_name, db)
    if match.confidence != "high":
        return False
    artikel_id = match.artikel.id
    if db.query(FridgeStaple).filter(FridgeStaple.artikel_id == artikel_id).first():
        return True
    if db.query(WatchlistItem).filter(WatchlistItem.artikel_id == artikel_id).first():
        return True
    return False
