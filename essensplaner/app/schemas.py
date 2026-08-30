from typing import Optional
from pydantic import BaseModel


class IngredientIn(BaseModel):
    name: str
    amount: Optional[float] = None
    unit: Optional[str] = None


class RecipeIn(BaseModel):
    title: str
    base_servings: int = 4
    instructions: str = ""
    is_favorite: bool = False
    tags: str = ""
    ingredients: list[IngredientIn] = []


class RecipeOut(RecipeIn):
    id: int
    image_path: Optional[str] = None
    source: str = "manual"

    class Config:
        from_attributes = True


class PlanEntryOut(BaseModel):
    date: str
    recipe_id: int
    recipe_title: str


class EntityOption(BaseModel):
    entity_id: str
    friendly_name: str


class SettingsIn(BaseModel):
    calendar_entity: str
    todo_entity: str
    # None = unverändert lassen, "" = Key löschen, sonst = neuen Key setzen
    anthropic_api_key: Optional[str] = None


class SettingsOut(BaseModel):
    calendar_entity: str
    todo_entity: str
    anthropic_api_key_set: bool = False
    available_calendars: list[EntityOption] = []
    available_todo_lists: list[EntityOption] = []


class RecipeExportFile(BaseModel):
    """Export-/Import-Dateiformat: eine oder mehrere Rezepte, ohne DB-IDs."""
    recipes: list[RecipeIn]


class ImportConflict(BaseModel):
    import_index: int
    imported_title: str
    existing_id: int
    existing_title: str


class ImportPreviewOut(BaseModel):
    total: int
    new_count: int
    conflicts: list[ImportConflict]


class ImportResolution(BaseModel):
    import_index: int
    action: str  # "alt" (bestehendes Rezept behalten, Import überspringen) | "neu" (Import übernimmt)


class ImportApplyIn(BaseModel):
    recipes: list[RecipeIn]
    resolutions: list[ImportResolution] = []


class ImportApplyOut(BaseModel):
    imported: int
    overwritten: int
    skipped: int


class FridgeItemIn(BaseModel):
    name: str
    amount: Optional[float] = None
    unit: Optional[str] = None


class FridgeItemOut(BaseModel):
    id: Optional[int] = None
    name: str
    amount: Optional[float] = None
    unit: Optional[str] = None
    is_staple: bool = False
    in_stock: bool = True


class FridgeStapleIn(BaseModel):
    name: str
    unit: Optional[str] = None
