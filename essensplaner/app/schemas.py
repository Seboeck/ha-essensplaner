from typing import Optional
from pydantic import BaseModel


class IngredientIn(BaseModel):
    """Zutat für Anlegen/Bearbeiten eines Rezepts — artikel_id ist
    bereits per Autocomplete in der UI aufgelöst (siehe Task 15)."""
    artikel_id: int
    amount: Optional[float] = None
    unit: Optional[str] = None


class IngredientOut(BaseModel):
    artikel_id: int
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


class RecipeOut(BaseModel):
    id: int
    title: str
    base_servings: int
    instructions: str
    is_favorite: bool
    tags: str
    image_path: Optional[str] = None
    source: str = "manual"
    ingredients: list[IngredientOut] = []

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
    plz: Optional[str] = None
    kaufland_store_url: Optional[str] = None
    edeka_store_url: Optional[str] = None


class SettingsOut(BaseModel):
    calendar_entity: str
    todo_entity: str
    anthropic_api_key_set: bool = False
    plz: Optional[str] = None
    kaufland_store_url: Optional[str] = None
    edeka_store_url: Optional[str] = None
    available_calendars: list[EntityOption] = []
    available_todo_lists: list[EntityOption] = []


class ArtikelSuggestOut(BaseModel):
    id: int
    name: str
    confidence: str  # "high" | "medium"


class ImportIngredientIn(BaseModel):
    """Freitext-Zutat, wie sie aus einer JSON-Import-Datei oder dem
    Foto-Import kommt — noch nicht mit einem Artikel verknüpft."""
    name: str
    amount: Optional[float] = None
    unit: Optional[str] = None


class ImportRecipeIn(BaseModel):
    """Rezept mit Freitext-Zutaten (Export-/Import-Dateiformat und
    Foto-Import-Ergebnis)."""
    title: str
    base_servings: int = 4
    instructions: str = ""
    is_favorite: bool = False
    tags: str = ""
    ingredients: list[ImportIngredientIn] = []


class RecipeExportFile(BaseModel):
    """Export-/Import-Dateiformat: eine oder mehrere Rezepte, ohne DB-IDs."""
    recipes: list[ImportRecipeIn]


class ImportConflict(BaseModel):
    import_index: int
    imported_title: str
    existing_id: int
    existing_title: str


class IngredientAmbiguity(BaseModel):
    recipe_index: int
    ingredient_index: int
    ingredient_name: str
    candidates: list[ArtikelSuggestOut]


class ImportPreviewOut(BaseModel):
    total: int
    new_count: int
    conflicts: list[ImportConflict]
    ingredient_ambiguities: list[IngredientAmbiguity] = []


class ImportResolution(BaseModel):
    import_index: int
    action: str  # "alt" (bestehendes Rezept behalten, Import überspringen) | "neu" (Import übernimmt)


class IngredientResolution(BaseModel):
    recipe_index: int
    ingredient_index: int
    artikel_id: int


class ImportApplyIn(BaseModel):
    recipes: list[ImportRecipeIn]
    resolutions: list[ImportResolution] = []
    ingredient_resolutions: list[IngredientResolution] = []


class ImportApplyOut(BaseModel):
    imported: int
    overwritten: int
    skipped: int


class FridgeItemIn(BaseModel):
    artikel_id: int
    amount: Optional[float] = None
    unit: Optional[str] = None


class FridgeItemOut(BaseModel):
    id: Optional[int] = None
    artikel_id: int
    name: str
    amount: Optional[float] = None
    unit: Optional[str] = None
    is_staple: bool = False
    in_stock: bool = True


class FridgeStapleIn(BaseModel):
    artikel_id: int
    unit: Optional[str] = None


class WatchlistItemIn(BaseModel):
    name: str
    unit: Optional[str] = None


class WatchlistItemOut(BaseModel):
    id: int
    name: str
    unit: Optional[str] = None

    class Config:
        from_attributes = True


class OfferOut(BaseModel):
    id: int
    retailer: str
    source: str
    product_name: str
    description: Optional[str] = None
    price: Optional[float] = None
    discount_text: Optional[str] = None
    valid_from: str
    valid_until: str
    matched_watchlist: bool = False
    matched_recipe_ids: list[int] = []

    class Config:
        from_attributes = True


class OfferSourceConfigOut(BaseModel):
    source: str
    enabled: bool
    schedule_weekday: Optional[int] = None
    schedule_hour: Optional[int] = None
    last_run_at: Optional[str] = None
    last_status: Optional[str] = None

    class Config:
        from_attributes = True


class OfferSourceConfigUpdateIn(BaseModel):
    enabled: Optional[bool] = None
    schedule_weekday: Optional[int] = None
    schedule_hour: Optional[int] = None


class ArtikelIn(BaseModel):
    name: str


class ArtikelOut(BaseModel):
    id: int
    name: str
    image_path: Optional[str] = None
    last_price: Optional[float] = None
    last_discount_text: Optional[str] = None

    class Config:
        from_attributes = True


class ArtikelPriceHistoryOut(BaseModel):
    price: Optional[float] = None
    discount_text: Optional[str] = None
    retailer: str
    source: str
    valid_from: str
    valid_until: str
    recorded_at: str
