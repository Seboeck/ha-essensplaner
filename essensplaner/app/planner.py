"""
Erzeugt einen abwechslungsreichen 7-Tage-Plan:
- Favoriten werden häufiger vorgeschlagen (höheres Gewicht)
- innerhalb der Woche keine Wiederholung desselben Rezepts
"""
import random
from datetime import date, timedelta

from sqlalchemy.orm import Session

from models import Recipe, PlanEntry, Offer
from offers.matching import find_matching_recipe_ids

FAVORITE_WEIGHT = 3
NORMAL_WEIGHT = 1
OFFER_WEIGHT_BONUS = 2


def _recipe_ids_with_active_offer(db: Session) -> set[int]:
    today = date.today()
    active_offers = db.query(Offer).filter(Offer.valid_until >= today).all()
    matched: set[int] = set()
    for offer in active_offers:
        matched.update(find_matching_recipe_ids(offer.product_name, db))
    return matched


def generate_week_plan(db: Session, start_date: date) -> list[PlanEntry]:
    recipes = db.query(Recipe).all()
    if not recipes:
        raise ValueError("Keine Rezepte vorhanden – bitte zuerst Rezepte anlegen.")

    offer_recipe_ids = _recipe_ids_with_active_offer(db)
    weights = [
        (FAVORITE_WEIGHT if r.is_favorite else NORMAL_WEIGHT)
        + (OFFER_WEIGHT_BONUS if r.id in offer_recipe_ids else 0)
        for r in recipes
    ]
    pool = list(zip(recipes, weights))

    chosen: list[Recipe] = []
    available = pool.copy()
    for _ in range(7):
        if not available:
            # falls weniger als 7 unterschiedliche Rezepte vorhanden sind: Pool wieder auffüllen
            available = pool.copy()
        picked = random.choices(
            [r for r, _ in available],
            weights=[w for _, w in available],
            k=1,
        )[0]
        chosen.append(picked)
        available = [(r, w) for r, w in available if r.id != picked.id]

    entries = []
    for i, recipe in enumerate(chosen):
        day = start_date + timedelta(days=i)
        entry = db.query(PlanEntry).filter(PlanEntry.date == day).first()
        if entry:
            entry.recipe_id = recipe.id
        else:
            entry = PlanEntry(date=day, recipe_id=recipe.id)
            db.add(entry)
        entries.append(entry)

    db.commit()
    return entries


def aggregate_shopping_list(db: Session, entries: list[PlanEntry]) -> list[str]:
    """Fasst gleiche Zutaten aus allen geplanten Rezepten zusammen (Name+Einheit als Schlüssel)."""
    totals: dict[tuple[str, str], float] = {}
    unitless: list[str] = []

    for entry in entries:
        recipe = entry.recipe
        for ing in recipe.ingredients:
            if ing.amount is None or ing.unit is None:
                unitless.append(ing.name)
                continue
            key = (ing.name.strip().lower(), ing.unit.strip().lower())
            totals[key] = totals.get(key, 0) + ing.amount

    items = [f"{amount:g} {unit} {name}" for (name, unit), amount in totals.items()]
    items.extend(sorted(set(unitless)))
    return items
