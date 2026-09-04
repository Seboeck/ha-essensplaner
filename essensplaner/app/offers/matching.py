"""Fuzzy-Matching zwischen Angebots-Produktnamen und Rezept-Zutaten /
Merklisten-Artikeln. Läuft on-demand (kein persistiertes Ergebnis), da sich
der Rezeptbestand ändern kann."""
from rapidfuzz import fuzz
from sqlalchemy.orm import Session

from models import Ingredient, FridgeStaple, WatchlistItem

DEFAULT_THRESHOLD = 80


def match_score(a: str, b: str) -> float:
    return fuzz.token_set_ratio(a.lower().strip(), b.lower().strip())


def find_matching_recipe_ids(product_name: str, db: Session, threshold: int = DEFAULT_THRESHOLD) -> list[int]:
    matched: set[int] = set()
    product_lower = product_name.lower().strip()
    for ingredient in db.query(Ingredient).all():
        ingredient_lower = ingredient.name.lower().strip()
        # Match if fuzzy score is high OR if ingredient name is a substring of product name
        # Substring check handles German compound words (e.g., "Mehl" in "Weizenmehl")
        if match_score(product_name, ingredient.name) >= threshold or ingredient_lower in product_lower:
            matched.add(ingredient.recipe_id)
    return sorted(matched)


def is_watchlist_match(product_name: str, db: Session, threshold: int = DEFAULT_THRESHOLD) -> bool:
    names = [s.name for s in db.query(FridgeStaple).all()]
    names += [w.name for w in db.query(WatchlistItem).all()]
    product_lower = product_name.lower().strip()
    for name in names:
        name_lower = name.lower().strip()
        # Match if fuzzy score is high OR if name is a substring of product name
        # Substring check handles German compound words (e.g., "Mehl" in "Weizenmehl")
        if match_score(product_name, name) >= threshold or name_lower in product_lower:
            return True
    return False
