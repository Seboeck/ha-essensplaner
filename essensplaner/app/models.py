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
    plz = Column(String, nullable=True)
    kaufland_store_url = Column(String, nullable=True)
    edeka_store_url = Column(String, nullable=True)


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


class Offer(Base):
    """Ein einzelnes Angebot aus einem Connector-Lauf."""
    __tablename__ = "offers"

    id = Column(Integer, primary_key=True, index=True)
    retailer = Column(String, nullable=False)  # kaufland | edeka
    source = Column(String, nullable=False)  # kaufland_scraper | edeka_scraper | marktguru
    product_name = Column(String, nullable=False)
    description = Column(String, nullable=True)
    price = Column(Float, nullable=True)
    discount_text = Column(String, nullable=True)
    valid_from = Column(Date, nullable=False)
    valid_until = Column(Date, nullable=False)
    notified_at = Column(String, nullable=True)  # ISO-Timestamp oder NULL
    scraped_at = Column(String, nullable=False)  # ISO-Timestamp


class WatchlistItem(Base):
    """Artikel, die regelmäßig gebraucht werden, aber kein FridgeStaple sind
    (z.B. Mehl, Waschmittel) — ergänzt FridgeStaple für die Angebots-Hervorhebung."""
    __tablename__ = "watchlist_items"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False, unique=True)
    unit = Column(String, nullable=True)


class OfferSourceConfig(Base):
    """Pro Angebots-Quelle: aktiviert, Zeitplan, letzter Lauf."""
    __tablename__ = "offer_source_configs"

    id = Column(Integer, primary_key=True, index=True)
    source = Column(String, nullable=False, unique=True)  # kaufland_scraper | edeka_scraper | marktguru
    enabled = Column(Boolean, default=True)
    schedule_weekday = Column(Integer, nullable=True)  # 0=Montag..6=Sonntag
    schedule_hour = Column(Integer, nullable=True)  # 0-23
    last_run_at = Column(String, nullable=True)  # ISO-Timestamp
    last_status = Column(String, nullable=True)  # "ok" oder Fehlertext


class Artikel(Base):
    """Kanonischer Artikel-Datensatz: verbindet Rezept-Zutaten,
    Kühlschrank-Bestand/-Standardartikel und Merklisten-Artikel mit
    Bild und Preis-Historie aus Angeboten."""
    __tablename__ = "artikel"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    image_path = Column(String, nullable=True)
    created_at = Column(String, nullable=False)  # ISO-Timestamp


class ArtikelPriceHistory(Base):
    """Ein Preis-/Rabatt-Eintrag zu einem Artikel, aus einem Angebots-
    Treffer mit hoher Konfidenz."""
    __tablename__ = "artikel_price_history"

    id = Column(Integer, primary_key=True, index=True)
    artikel_id = Column(Integer, ForeignKey("artikel.id"), nullable=False)
    price = Column(Float, nullable=True)
    discount_text = Column(String, nullable=True)
    retailer = Column(String, nullable=False)
    source = Column(String, nullable=False)
    valid_from = Column(Date, nullable=False)
    valid_until = Column(Date, nullable=False)
    recorded_at = Column(String, nullable=False)  # ISO-Timestamp

    artikel = relationship("Artikel")


class PendingArtikelMatch(Base):
    """Ein Angebots-Produktname, der nur mit mittlerer Konfidenz zu einem
    Artikel passt — wartet auf Bestätigung/Ablehnung durch den Nutzer.
    Identität über (product_name, artikel_id), NICHT offer_id: Angebote
    werden bei jedem Connector-Lauf komplett ersetzt (siehe run_source),
    eine FK auf offer_id würde bei jedem Lauf verwaisen."""
    __tablename__ = "pending_artikel_matches"

    id = Column(Integer, primary_key=True, index=True)
    product_name = Column(String, nullable=False)
    artikel_id = Column(Integer, ForeignKey("artikel.id"), nullable=False)
    score = Column(Float, nullable=False)
    status = Column(String, nullable=False, default="open")  # open | confirmed | rejected
    price = Column(Float, nullable=True)
    discount_text = Column(String, nullable=True)
    retailer = Column(String, nullable=False)
    source = Column(String, nullable=False)
    valid_from = Column(Date, nullable=False)
    valid_until = Column(Date, nullable=False)
    created_at = Column(String, nullable=False)  # ISO-Timestamp

    artikel = relationship("Artikel")
