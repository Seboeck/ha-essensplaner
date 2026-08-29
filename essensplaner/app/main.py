from datetime import date
from fastapi import FastAPI, Depends, HTTPException
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

from database import init_db, get_db
from models import Recipe, Ingredient, PlanEntry, Settings
from schemas import (
    RecipeIn,
    RecipeOut,
    PlanEntryOut,
    SettingsIn,
    SettingsOut,
    RecipeExportFile,
    ImportPreviewOut,
    ImportConflict,
    ImportApplyIn,
    ImportApplyOut,
)
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


# ---------- Export / Import ----------

def _normalize_title(title: str) -> str:
    return title.strip().lower()


def _recipe_to_export(recipe: Recipe) -> dict:
    return {
        "title": recipe.title,
        "base_servings": recipe.base_servings,
        "instructions": recipe.instructions,
        "is_favorite": recipe.is_favorite,
        "tags": recipe.tags,
        "ingredients": [
            {"name": i.name, "amount": i.amount, "unit": i.unit} for i in recipe.ingredients
        ],
    }


@app.get("/api/recipes/export", response_model=RecipeExportFile)
def export_all_recipes(db: Session = Depends(get_db)):
    """Exportiert alle Rezepte als importierbare JSON-Datei."""
    recipes = db.query(Recipe).all()
    return {"recipes": [_recipe_to_export(r) for r in recipes]}


@app.get("/api/recipes/{recipe_id}/export", response_model=RecipeExportFile)
def export_one_recipe(recipe_id: int, db: Session = Depends(get_db)):
    """Exportiert ein einzelnes Rezept als importierbare JSON-Datei."""
    recipe = db.query(Recipe).get(recipe_id)
    if not recipe:
        raise HTTPException(404, "Rezept nicht gefunden")
    return {"recipes": [_recipe_to_export(recipe)]}


@app.post("/api/recipes/import/preview", response_model=ImportPreviewOut)
def preview_import(payload: RecipeExportFile, db: Session = Depends(get_db)):
    """
    Prüft die zu importierenden Rezepte auf Titel-Duplikate mit bestehenden
    Rezepten, ohne die DB zu verändern. Der Client löst die Konflikte auf
    (alt behalten oder neu übernehmen) und ruft danach /import/apply auf.
    """
    existing_by_title = {_normalize_title(r.title): r for r in db.query(Recipe).all()}
    conflicts: list[ImportConflict] = []
    for idx, recipe in enumerate(payload.recipes):
        match = existing_by_title.get(_normalize_title(recipe.title))
        if match:
            conflicts.append(
                ImportConflict(
                    import_index=idx,
                    imported_title=recipe.title,
                    existing_id=match.id,
                    existing_title=match.title,
                )
            )
    return ImportPreviewOut(
        total=len(payload.recipes),
        new_count=len(payload.recipes) - len(conflicts),
        conflicts=conflicts,
    )


@app.post("/api/recipes/import/apply", response_model=ImportApplyOut)
def apply_import(payload: ImportApplyIn, db: Session = Depends(get_db)):
    """
    Führt den Import durch: neue Rezepte (kein Titel-Duplikat) werden immer
    angelegt. Für Duplikate entscheidet 'resolutions' pro Index:
    action="neu" überschreibt das bestehende Rezept mit den Importdaten,
    action="alt" (oder keine Angabe) behält das bestehende Rezept unverändert.
    """
    existing_by_title = {_normalize_title(r.title): r for r in db.query(Recipe).all()}
    resolution_by_index = {res.import_index: res.action for res in payload.resolutions}

    imported = overwritten = skipped = 0

    for idx, recipe in enumerate(payload.recipes):
        match = existing_by_title.get(_normalize_title(recipe.title))
        if match:
            action = resolution_by_index.get(idx, "alt")
            if action == "neu":
                match.title = recipe.title
                match.base_servings = recipe.base_servings
                match.instructions = recipe.instructions
                match.is_favorite = recipe.is_favorite
                match.tags = recipe.tags
                match.ingredients = [
                    Ingredient(name=i.name, amount=i.amount, unit=i.unit)
                    for i in recipe.ingredients
                ]
                overwritten += 1
            else:
                skipped += 1
        else:
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
            imported += 1

    db.commit()
    return ImportApplyOut(imported=imported, overwritten=overwritten, skipped=skipped)


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
