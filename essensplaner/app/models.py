from sqlalchemy import Column, Integer, String, Float, Boolean, Date, ForeignKey, Text
from sqlalchemy.orm import relationship, declarative_base

Base = declarative_base()


class Recipe(Base):
    __tablename__ = "recipes"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, nullable=False)
    base_servings = Column(Integer, default=4)  # 2 Erwachsene + 2 Kinder
    instructions = Column(Text, default="")
    image_path = Column(String, nullable=True)
    is_favorite = Column(Boolean, default=False)
    source = Column(String, default="manual")  # manual | photo_print | photo_handwritten
    tags = Column(String, default="")  # kommagetrennt, z.B. "vegetarisch,schnell"

    ingredients = relationship("Ingredient", back_populates="recipe", cascade="all, delete-orphan")


class Ingredient(Base):
    __tablename__ = "ingredients"

    id = Column(Integer, primary_key=True, index=True)
    recipe_id = Column(Integer, ForeignKey("recipes.id"))
    name = Column(String, nullable=False)
    amount = Column(Float, nullable=True)
    unit = Column(String, nullable=True)  # g, kg, ml, l, Stück, EL, TL, ...

    recipe = relationship("Recipe", back_populates="ingredients")


class PlanEntry(Base):
    """Ein geplantes Hauptgericht für einen bestimmten Tag."""
    __tablename__ = "plan_entries"

    id = Column(Integer, primary_key=True, index=True)
    date = Column(Date, nullable=False, unique=True)
    recipe_id = Column(Integer, ForeignKey("recipes.id"))

    recipe = relationship("Recipe")
