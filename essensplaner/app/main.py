import base64
from datetime import date
from pathlib import Path

import anthropic
from fastapi import FastAPI, Depends, HTTPException, UploadFile, File
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

import database
from database import init_db, get_db
from models import Recipe, Ingredient, PlanEntry, Settings, FridgeItem, FridgeStaple
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
    FridgeItemIn,
    FridgeItemOut,
    FridgeStapleIn,
)
import ha_client
from planner import generate_week_plan, aggregate_shopping_list

app = FastAPI(title="Essensplaner")

IMAGES_DIR = Path(database.DB_PATH).parent / "images"
IMAGES_DIR.mkdir(parents=True, exist_ok=True)
IMAGE_EXTENSIONS = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/heic": ".heic",
    "image/heif": ".heif",
}


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

async def _list_entities_safe(domain: str) -> list[dict]:
    """Wie ha_client.list_entities, aber ohne die Einstellungsseite lahmzulegen,
    wenn Home Assistant gerade nicht erreichbar ist (z.B. lokales Testen)."""
    try:
        return await ha_client.list_entities(domain)
    except Exception:
        return []


@app.get("/api/settings", response_model=SettingsOut)
async def read_settings(db: Session = Depends(get_db)):
    settings = get_settings(db)
    calendars = await _list_entities_safe("calendar")
    todo_lists = await _list_entities_safe("todo")
    return SettingsOut(
        calendar_entity=settings.calendar_entity,
        todo_entity=settings.todo_entity,
        anthropic_api_key_set=bool(settings.anthropic_api_key),
        available_calendars=calendars,
        available_todo_lists=todo_lists,
    )


@app.post("/api/settings", response_model=SettingsOut)
async def save_settings(payload: SettingsIn, db: Session = Depends(get_db)):
    settings = get_settings(db)
    settings.calendar_entity = payload.calendar_entity
    settings.todo_entity = payload.todo_entity
    if payload.anthropic_api_key is not None:
        settings.anthropic_api_key = payload.anthropic_api_key or None
    db.commit()
    calendars = await _list_entities_safe("calendar")
    todo_lists = await _list_entities_safe("todo")
    return SettingsOut(
        calendar_entity=settings.calendar_entity,
        todo_entity=settings.todo_entity,
        anthropic_api_key_set=bool(settings.anthropic_api_key),
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


@app.post("/api/recipes/{recipe_id}/image", response_model=RecipeOut)
async def upload_recipe_image(recipe_id: int, file: UploadFile = File(...), db: Session = Depends(get_db)):
    db_recipe = db.query(Recipe).get(recipe_id)
    if not db_recipe:
        raise HTTPException(404, "Rezept nicht gefunden")

    media_type = file.content_type or ""
    ext = IMAGE_EXTENSIONS.get(media_type)
    if not ext:
        raise HTTPException(400, "Bitte ein Bild hochladen (JPEG, PNG, WebP, HEIC).")

    for old_file in IMAGES_DIR.glob(f"{recipe_id}.*"):
        old_file.unlink(missing_ok=True)

    dest = IMAGES_DIR / f"{recipe_id}{ext}"
    dest.write_bytes(await file.read())

    db_recipe.image_path = f"/recipe-images/{recipe_id}{ext}"
    db.commit()
    db.refresh(db_recipe)
    return db_recipe


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


# ---------- Foto-Import (Vision-Erkennung) ----------

RECIPE_EXTRACTION_TOOL = {
    "name": "recipe_data",
    "description": (
        "Strukturierte Rezeptdaten, die aus dem Foto einer Rezeptkarte oder eines "
        "handschriftlichen Rezepts erkannt wurden."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "Titel des Rezepts"},
            "base_servings": {
                "type": "integer",
                "description": "Anzahl Portionen laut Rezept, falls angegeben, sonst 4",
            },
            "instructions": {"type": "string", "description": "Zubereitungsschritte als Fließtext"},
            "tags": {
                "type": "string",
                "description": "Kommagetrennte Schlagworte, z.B. 'vegetarisch,schnell'; leerer String wenn keine erkennbar",
            },
            "ingredients": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "amount": {"type": ["number", "null"]},
                        "unit": {
                            "type": ["string", "null"],
                            "description": "z.B. g, kg, ml, l, Stück, EL, TL",
                        },
                    },
                    "required": ["name"],
                },
            },
        },
        "required": ["title", "ingredients", "instructions"],
    },
}

RECIPE_EXTRACTION_SYSTEM_PROMPT = (
    "Du liest Kochrezepte von Fotos (gedruckte Rezeptkarten oder Handschrift) oder PDFs und "
    "gibst sie strukturiert zurück. Bei Unsicherheiten (v.a. bei Handschrift) wähle die "
    "plausibelste Lesart – die Daten werden vor dem Speichern von einem Menschen geprüft. "
    "Mengen als Zahl im amount-Feld (z.B. 0.5 für 1/2), die Einheit separat im unit-Feld. "
    "base_servings: Zahl laut Rezept, sonst 4. Falls mehrere Bilder oder Seiten angehängt "
    "sind, gehören sie zu ein und demselben Rezept (z.B. Vorder-/Rückseite einer Karte oder "
    "ein mehrseitiges Rezept) – kombiniere sie zu einem einzigen Ergebnis."
)

# Anthropic-Vision unterstützt sowohl Bilder als auch PDFs (als "document"-Content-Block) und
# mehrere Dateien in einer Anfrage – nützlich, wenn ein Rezept nicht auf eine Seite/ein Foto passt.
IMPORT_MEDIA_TYPES = {
    "image/jpeg": "image",
    "image/png": "image",
    "image/webp": "image",
    "image/heic": "image",
    "image/heif": "image",
    "application/pdf": "document",
}


@app.post("/api/recipes/import-photo", response_model=RecipeIn)
async def import_recipe_photo(files: list[UploadFile] = File(...), db: Session = Depends(get_db)):
    """
    Nimmt ein oder mehrere Fotos/PDFs einer Rezeptkarte oder eines handschriftlichen Rezepts
    entgegen (z.B. mehrere Seiten, wenn ein Rezept nicht auf ein Bild passt), erkennt die
    Daten per Claude Vision und gibt sie als Entwurf zurück – Review vor dem Speichern ist
    Pflicht (besonders wichtig bei handschriftlichen Rezepten).
    """
    settings = get_settings(db)
    if not settings.anthropic_api_key:
        raise HTTPException(400, "Bitte zuerst einen Anthropic API-Key in den Einstellungen hinterlegen.")
    if not files:
        raise HTTPException(400, "Bitte mindestens ein Bild oder PDF hochladen.")

    content_blocks = []
    for file in files:
        media_type = file.content_type or ""
        block_type = IMPORT_MEDIA_TYPES.get(media_type)
        if not block_type:
            raise HTTPException(
                400,
                f"Nicht unterstützter Dateityp bei '{file.filename}': {media_type or 'unbekannt'}. "
                "Erlaubt sind Bilder (JPEG, PNG, WebP, HEIC) und PDF.",
            )
        data_b64 = base64.standard_b64encode(await file.read()).decode("utf-8")
        content_blocks.append({
            "type": block_type,
            "source": {"type": "base64", "media_type": media_type, "data": data_b64},
        })
    content_blocks.append({
        "type": "text",
        "text": "Erkenne dieses Rezept und gib die strukturierten Daten zurück.",
    })

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    try:
        response = client.messages.create(
            model="claude-sonnet-5",
            max_tokens=2000,
            thinking={"type": "disabled"},
            tools=[RECIPE_EXTRACTION_TOOL],
            tool_choice={"type": "tool", "name": "recipe_data"},
            system=RECIPE_EXTRACTION_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": content_blocks}],
        )
    except anthropic.AuthenticationError:
        raise HTTPException(401, "Anthropic API-Key ist ungültig.")
    except anthropic.RateLimitError:
        raise HTTPException(429, "Rate-Limit bei der Anthropic API erreicht, bitte kurz warten.")
    except anthropic.APIStatusError as e:
        raise HTTPException(502, f"Fehler bei der Anthropic API: {e.message}")
    except anthropic.APIConnectionError:
        raise HTTPException(502, "Anthropic API nicht erreichbar.")

    tool_use = next((b for b in response.content if b.type == "tool_use"), None)
    if not tool_use:
        raise HTTPException(502, "Konnte keine Rezeptdaten aus dem Foto erkennen.")

    try:
        return RecipeIn(**tool_use.input)
    except Exception:
        raise HTTPException(502, "Erkannte Daten hatten ein unerwartetes Format.")


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


# ---------- Kühlschrank ----------

def _norm(name: str) -> str:
    return name.strip().lower()


@app.get("/api/fridge", response_model=list[FridgeItemOut])
def list_fridge(db: Session = Depends(get_db)):
    """
    Kombinierte Sicht aus aktuellem Bestand (fridge_items) und Standardartikeln
    (fridge_staples). Ein Standardartikel ohne passenden Bestandseintrag wird
    trotzdem angezeigt, aber als 'fehlt' markiert (in_stock=False) – so bleibt
    sichtbar, dass er eigentlich immer vorhanden sein sollte.
    """
    items = db.query(FridgeItem).all()
    staples_by_norm = {_norm(s.name): s for s in db.query(FridgeStaple).all()}

    result = []
    covered = set()
    for item in items:
        key = _norm(item.name)
        covered.add(key)
        result.append(FridgeItemOut(
            id=item.id, name=item.name, amount=item.amount, unit=item.unit,
            is_staple=key in staples_by_norm, in_stock=True,
        ))
    for key, staple in staples_by_norm.items():
        if key not in covered:
            result.append(FridgeItemOut(
                id=None, name=staple.name, amount=None, unit=staple.unit,
                is_staple=True, in_stock=False,
            ))

    result.sort(key=lambda i: i.name.lower())
    return result


@app.post("/api/fridge/items", response_model=FridgeItemOut)
def upsert_fridge_item(payload: FridgeItemIn, db: Session = Depends(get_db)):
    """Legt einen Bestandsartikel an oder aktualisiert Menge/Einheit, falls der Name schon existiert."""
    name = payload.name.strip()
    if not name:
        raise HTTPException(400, "Name darf nicht leer sein.")
    item = db.query(FridgeItem).filter(FridgeItem.name.ilike(name)).first()
    if item:
        item.amount = payload.amount
        item.unit = payload.unit
    else:
        item = FridgeItem(name=name, amount=payload.amount, unit=payload.unit)
        db.add(item)
    db.commit()
    db.refresh(item)
    is_staple = db.query(FridgeStaple).filter(FridgeStaple.name.ilike(name)).first() is not None
    return FridgeItemOut(
        id=item.id, name=item.name, amount=item.amount, unit=item.unit,
        is_staple=is_staple, in_stock=True,
    )


@app.delete("/api/fridge/items/{item_id}")
def remove_fridge_item(item_id: int, db: Session = Depends(get_db)):
    """Entfernt einen Bestandsartikel (z.B. weil aufgebraucht). Eine evtl. Standardartikel-
    Markierung bleibt bestehen, der Artikel erscheint danach als 'fehlt'."""
    item = db.query(FridgeItem).get(item_id)
    if not item:
        raise HTTPException(404, "Artikel nicht gefunden")
    db.delete(item)
    db.commit()
    return {"status": "ok"}


@app.post("/api/fridge/staples", response_model=FridgeItemOut)
def mark_fridge_staple(payload: FridgeStapleIn, db: Session = Depends(get_db)):
    """Markiert einen Artikelnamen als Standardartikel ('sollte immer vorhanden sein')."""
    name = payload.name.strip()
    if not name:
        raise HTTPException(400, "Name darf nicht leer sein.")
    staple = db.query(FridgeStaple).filter(FridgeStaple.name.ilike(name)).first()
    if staple:
        staple.unit = payload.unit
    else:
        staple = FridgeStaple(name=name, unit=payload.unit)
        db.add(staple)
    db.commit()

    item = db.query(FridgeItem).filter(FridgeItem.name.ilike(name)).first()
    if item:
        return FridgeItemOut(id=item.id, name=item.name, amount=item.amount, unit=item.unit, is_staple=True, in_stock=True)
    return FridgeItemOut(id=None, name=name, amount=None, unit=payload.unit, is_staple=True, in_stock=False)


@app.delete("/api/fridge/staples/by-name/{name}")
def unmark_fridge_staple(name: str, db: Session = Depends(get_db)):
    """Entfernt die Standardartikel-Markierung. Ein evtl. vorhandener Bestandseintrag bleibt bestehen."""
    staple = db.query(FridgeStaple).filter(FridgeStaple.name.ilike(name)).first()
    if not staple:
        raise HTTPException(404, "Standardartikel nicht gefunden")
    db.delete(staple)
    db.commit()
    return {"status": "ok"}


app.mount("/recipe-images", StaticFiles(directory=str(IMAGES_DIR)), name="recipe-images")
app.mount("/", StaticFiles(directory="static", html=True), name="static")
