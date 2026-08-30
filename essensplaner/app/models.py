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


class Settings(Base):
    """Einzige Konfigurationszeile (id=1): welche HA-Kalender-/To-do-Entity genutzt wird."""
    __tablename__ = "settings"

    id = Column(Integer, primary_key=True, default=1)
    calendar_entity = Column(String, nullable=True)
    todo_entity = Column(String, nullable=True)
    anthropic_api_key = Column(String, nullable=True)


class PlanEntry(Base):
    """Ein geplantes Hauptgericht für einen bestimmten Tag."""
    __tablename__ = "plan_entries"

    id = Column(Integer, primary_key=True, index=True)
    date = Column(Date, nullable=False, unique=True)
    recipe_id = Column(Integer, ForeignKey("recipes.id"))

    recipe = relationship("Recipe")


class FridgeItem(Base):
    """Aktuell im Kühlschrank vorhandener Artikel (manuell erfasst, später ggf. per Fotoerkennung)."""
    __tablename__ = "fridge_items"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    amount = Column(Float, nullable=True)
    unit = Column(String, nullable=True)


class FridgeStaple(Base):
    """Artikel, die immer im Kühlschrank sein sollten ('Standard'/Favorit) –
    werden auch angezeigt, wenn gerade kein passender FridgeItem-Bestand existiert."""
    __tablename__ = "fridge_staples"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False, unique=True)
    unit = Column(String, nullable=True)
