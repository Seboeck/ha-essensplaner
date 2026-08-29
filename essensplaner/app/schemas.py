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
