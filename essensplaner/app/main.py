from datetime import date
from fastapi import FastAPI, Depends, HTTPException
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

from database import init_db, get_db
from models import Recipe, Ingredient, PlanEntry, Settings
from schemas import RecipeIn, RecipeOut, PlanEntryOut, SettingsIn, SettingsOut
import ha_client
from planner import generate_week_plan, aggregate_shopping_list

app = FastAPI(title="Essensplaner")


@app.on_event("startup")
def on_startup():
    init_db()


def get_settings(db: Session) -> Settings:
    settings = db.query(Settings).get(1)
    if not settings:
        settings = Settings(
            id=1,
            calendar_entity=ha_client.DEFAULT_CALENDAR_ENTITY,
            todo_entity=ha_client.DEFAULT_TODO_ENTITY,
        )
        db.add(settings)
        db.commit()
        db.refresh(settings)
    return settings


# ---------- Einstellungen ----------

@app.get("/api/settings", response_model=SettingsOut)
async def read_settings(db: Session = Depends(get_db)):
    settings = get_settings(db)
    calendars = await ha_client.list_entities("calendar")
    todo_lists = await ha_client.list_entities("todo")
    return SettingsOut(
        calendar_entity=settings.calendar_entity,
        todo_entity=settings.todo_entity,
        available_calendars=calendars,
        available_todo_lists=todo_lists,
    )


@app.post("/api/settings", response_model=SettingsOut)
async def save_settings(payload: SettingsIn, db: Session = Depends(get_db)):
    settings = get_settings(db)
    settings.calendar_entity = payload.calendar_entity
    settings.todo_entity = payload.todo_entity
    db.commit()
    calendars = await ha_client.list_entities("calendar")
    todo_lists = await ha_client.list_entities("todo")
    return SettingsOut(
        calendar_entity=settings.calendar_entity,
        todo_entity=settings.todo_entity,
        available_calendars=calendars,
        available_todo_lists=todo_lists,
    )


# ---------- Rezepte ----------

@app.get("/api/recipes", response_model=list[RecipeOut])
def list_recipes(db: Session = Depends(get_db)):
    return db.query(Recipe).all()


@app.post("/api/recipes", response_model=RecipeOut)
def create_recipe(recipe: RecipeIn, db: Session = Depends(get_db)):
    db_recipe = Recipe(
        title=recipe.title,
        base_servings=recipe.base_servings,
        instructions=recipe.instructions,
        is_favorite=recipe.is_favorite,
        tags=recipe.tags,
    )
    db_recipe.ingredients = [
        Ingredient(name=i.name, amount=i.amount, unit=i.unit) for i in recipe.ingredients
    ]
    db.add(db_recipe)
    db.commit()
    db.refresh(db_recipe)
    return db_recipe


@app.put("/api/recipes/{recipe_id}", response_model=RecipeOut)
def update_recipe(recipe_id: int, recipe: RecipeIn, db: Session = Depends(get_db)):
    db_recipe = db.query(Recipe).get(recipe_id)
    if not db_recipe:
        raise HTTPException(404, "Rezept nicht gefunden")
    db_recipe.title = recipe.title
    db_recipe.base_servings = recipe.base_servings
    db_recipe.instructions = recipe.instructions
    db_recipe.is_favorite = recipe.is_favorite
    db_recipe.tags = recipe.tags
    db_recipe.ingredients = [
        Ingredient(name=i.name, amount=i.amount, unit=i.unit) for i in recipe.ingredients
    ]
    db.commit()
    db.refresh(db_recipe)
    return db_recipe


@app.delete("/api/recipes/{recipe_id}")
def delete_recipe(recipe_id: int, db: Session = Depends(get_db)):
    db_recipe = db.query(Recipe).get(recipe_id)
    if not db_recipe:
        raise HTTPException(404, "Rezept nicht gefunden")
    db.delete(db_recipe)
    db.commit()
    return {"status": "ok"}


# ---------- Foto-Import (Platzhalter für Vision-Erkennung) ----------

@app.post("/api/recipes/import-photo")
async def import_recipe_photo():
    """
    TODO: Foto entgegennehmen, per Claude Vision (Anthropic API) in strukturierte
    Rezeptdaten umwandeln und als Entwurf zurückgeben (Review vor dem Speichern,
    besonders wichtig bei handschriftlichen Rezepten).
    """
    raise HTTPException(501, "Noch nicht implementiert – Platzhalter für Vision-Import")


# ---------- Wochenplan ----------

@app.post("/api/plan/generate", response_model=list[PlanEntryOut])
async def generate_plan(start: str, db: Session = Depends(get_db)):
    start_date = date.fromisoformat(start)
    try:
        entries = generate_week_plan(db, start_date)
    except ValueError as e:
        raise HTTPException(400, str(e))

    # in Home-Assistant-Kalender schreiben
    settings = get_settings(db)
    for entry in entries:
        await ha_client.upsert_calendar_event(
            settings.calendar_entity, entry.date.isoformat(), entry.recipe.title
        )

    return [
        PlanEntryOut(date=e.date.isoformat(), recipe_id=e.recipe_id, recipe_title=e.recipe.title)
        for e in entries
    ]


@app.get("/api/plan", response_model=list[PlanEntryOut])
def get_plan(start: str, db: Session = Depends(get_db)):
    start_date = date.fromisoformat(start)
    entries = (
        db.query(PlanEntry)
        .filter(PlanEntry.date >= start_date)
        .order_by(PlanEntry.date)
        .limit(7)
        .all()
    )
    return [
        PlanEntryOut(date=e.date.isoformat(), recipe_id=e.recipe_id, recipe_title=e.recipe.title)
        for e in entries
    ]


@app.put("/api/plan/{entry_date}")
async def swap_day(entry_date: str, recipe_id: int, db: Session = Depends(get_db)):
    """Tauscht das Gericht eines einzelnen Tages (z.B. ausgelöst über das HA-Dashboard)."""
    d = date.fromisoformat(entry_date)
    entry = db.query(PlanEntry).filter(PlanEntry.date == d).first()
    if not entry:
        raise HTTPException(404, "Kein Plan-Eintrag für dieses Datum")
    entry.recipe_id = recipe_id
    db.commit()
    settings = get_settings(db)
    await ha_client.upsert_calendar_event(settings.calendar_entity, entry_date, entry.recipe.title)
    return {"status": "ok"}


# ---------- Einkaufsliste ----------

@app.post("/api/shopping-list/push")
async def push_shopping_list(start: str, db: Session = Depends(get_db)):
    start_date = date.fromisoformat(start)
    entries = (
        db.query(PlanEntry)
        .filter(PlanEntry.date >= start_date)
        .order_by(PlanEntry.date)
        .limit(7)
        .all()
    )
    if not entries:
        raise HTTPException(400, "Kein Wochenplan vorhanden")

    items = aggregate_shopping_list(db, entries)
    settings = get_settings(db)
    await ha_client.add_shopping_items(settings.todo_entity, items)
    return {"items_added": items}


app.mount("/", StaticFiles(directory="static", html=True), name="static")
