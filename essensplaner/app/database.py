import os
from datetime import datetime
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from models import Base, Offer, WatchlistItem, OfferSourceConfig

# /share übersteht Add-on-Deinstallation/-Neuinstallation (anders als /data,
# das der Supervisor beim Deinstallieren absichtlich löscht).
DB_PATH = os.environ.get("DB_PATH", "/share/essensplaner/essensplaner.db")
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
engine = create_engine(f"sqlite:///{DB_PATH}", connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

_LEGACY_ARTIKEL_TABLES = ["ingredients", "fridge_staples", "watchlist_items", "fridge_items"]


def _table_exists(conn, name: str) -> bool:
    return conn.execute(
        text("SELECT name FROM sqlite_master WHERE type='table' AND name=:n"), {"n": name}
    ).first() is not None


def _table_has_column(conn, table: str, column: str) -> bool:
    return column in {row[1] for row in conn.execute(text(f"PRAGMA table_info({table})"))}


def _rename_legacy_artikel_tables_if_needed() -> bool:
    """Prüft, ob die alte Freitext-Spalte `name` auf `ingredients` noch
    existiert (Neuinstallationen und bereits migrierte DBs haben sie
    nicht mehr). Falls ja: alle vier betroffenen Tabellen umbenennen,
    damit create_all() sie gleich darauf im neuen Schema (mit artikel_id)
    neu anlegt. Gibt True zurück, wenn eine Migration nötig ist (dann muss
    später _populate_artikel_from_legacy_tables() aufgerufen werden)."""
    with engine.begin() as conn:
        if not _table_exists(conn, "ingredients") or not _table_has_column(conn, "ingredients", "name"):
            return False
        for table in _LEGACY_ARTIKEL_TABLES:
            conn.execute(text(f"ALTER TABLE {table} RENAME TO {table}_old"))
    return True


def _populate_artikel_from_legacy_tables():
    """Übernimmt Daten aus den umbenannten Alt-Tabellen in die neuen,
    artikel_id-basierten Tabellen. Für jeden (normalisiert) eindeutigen
    Namen über ALLE vier Alt-Tabellen hinweg wird genau ein Artikel
    angelegt — gleicher Name in mehreren Tabellen/Zeilen erhält denselben
    Artikel (siehe Spec, Abschnitt 'Migration'). Nur exakte Übereinstimmung
    wird zusammengeführt, ähnliche Namen bleiben getrennte Artikel."""
    with engine.begin() as conn:
        now = datetime.utcnow().isoformat()
        artikel_by_norm: dict[str, int] = {}

        def get_or_create_artikel(name: str) -> int:
            norm = name.strip().lower()
            if norm in artikel_by_norm:
                return artikel_by_norm[norm]
            result = conn.execute(
                text("INSERT INTO artikel (name, image_path, created_at) VALUES (:name, NULL, :now)"),
                {"name": name.strip(), "now": now},
            )
            artikel_id = result.lastrowid
            artikel_by_norm[norm] = artikel_id
            return artikel_id

        for row in conn.execute(text("SELECT id, recipe_id, name, amount, unit FROM ingredients_old")):
            artikel_id = get_or_create_artikel(row.name)
            conn.execute(
                text("INSERT INTO ingredients (id, recipe_id, artikel_id, amount, unit) "
                     "VALUES (:id, :recipe_id, :artikel_id, :amount, :unit)"),
                {"id": row.id, "recipe_id": row.recipe_id, "artikel_id": artikel_id, "amount": row.amount, "unit": row.unit},
            )

        for row in conn.execute(text("SELECT id, name, unit FROM fridge_staples_old")):
            artikel_id = get_or_create_artikel(row.name)
            conn.execute(
                text("INSERT INTO fridge_staples (id, artikel_id, unit) VALUES (:id, :artikel_id, :unit)"),
                {"id": row.id, "artikel_id": artikel_id, "unit": row.unit},
            )

        for row in conn.execute(text("SELECT id, name, unit FROM watchlist_items_old")):
            artikel_id = get_or_create_artikel(row.name)
            conn.execute(
                text("INSERT INTO watchlist_items (id, artikel_id, unit) VALUES (:id, :artikel_id, :unit)"),
                {"id": row.id, "artikel_id": artikel_id, "unit": row.unit},
            )

        for row in conn.execute(text("SELECT id, name, amount, unit FROM fridge_items_old")):
            artikel_id = get_or_create_artikel(row.name)
            conn.execute(
                text("INSERT INTO fridge_items (id, artikel_id, amount, unit) VALUES (:id, :artikel_id, :amount, :unit)"),
                {"id": row.id, "artikel_id": artikel_id, "amount": row.amount, "unit": row.unit},
            )

        for table in _LEGACY_ARTIKEL_TABLES:
            conn.execute(text(f"DROP TABLE {table}_old"))


def _migrate_add_missing_columns():
    """Ergänzt Spalten, die create_all() bei bereits bestehenden Tabellen nicht nachträgt."""
    with engine.connect() as conn:
        existing = {row[1] for row in conn.execute(text("PRAGMA table_info(settings)"))}
        if "anthropic_api_key" not in existing:
            conn.execute(text("ALTER TABLE settings ADD COLUMN anthropic_api_key VARCHAR"))
            conn.commit()
        for column, coltype in [
            ("plz", "VARCHAR"),
            ("kaufland_store_url", "VARCHAR"),
            ("edeka_store_url", "VARCHAR"),
        ]:
            if column not in existing:
                conn.execute(text(f"ALTER TABLE settings ADD COLUMN {column} {coltype}"))
                conn.commit()


def init_db():
    needs_artikel_migration = _rename_legacy_artikel_tables_if_needed()
    Base.metadata.create_all(bind=engine)
    _migrate_add_missing_columns()
    if needs_artikel_migration:
        _populate_artikel_from_legacy_tables()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
