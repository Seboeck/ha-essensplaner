import sqlite3
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


def _create_legacy_db(path: Path):
    conn = sqlite3.connect(str(path))
    conn.executescript("""
        CREATE TABLE recipes (id INTEGER PRIMARY KEY, title TEXT NOT NULL, base_servings INTEGER,
            instructions TEXT, image_path TEXT, is_favorite BOOLEAN, source TEXT, tags TEXT);
        CREATE TABLE ingredients (id INTEGER PRIMARY KEY, recipe_id INTEGER, name TEXT NOT NULL,
            amount REAL, unit TEXT);
        CREATE TABLE fridge_staples (id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, unit TEXT);
        CREATE TABLE watchlist_items (id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, unit TEXT);
        CREATE TABLE fridge_items (id INTEGER PRIMARY KEY, name TEXT NOT NULL, amount REAL, unit TEXT);
        CREATE TABLE settings (id INTEGER PRIMARY KEY);

        INSERT INTO recipes (id, title, base_servings, instructions, is_favorite, source, tags)
            VALUES (1, 'Kaesebrot', 4, '', 0, 'manual', '');
        INSERT INTO ingredients (id, recipe_id, name, amount, unit) VALUES (1, 1, 'Gouda', 200, 'g');
        INSERT INTO ingredients (id, recipe_id, name, amount, unit) VALUES (2, 1, 'gouda', 1, 'Stueck');
        INSERT INTO fridge_staples (id, name, unit) VALUES (1, 'Gouda', 'Stueck');
        INSERT INTO watchlist_items (id, name, unit) VALUES (1, 'Mehl', NULL);
        INSERT INTO fridge_items (id, name, amount, unit) VALUES (1, 'Gouda gerieben', 100, 'g');
    """)
    conn.commit()
    conn.close()


def test_migration_deduplicates_exact_names_across_tables(tmp_path, monkeypatch):
    import database

    db_file = tmp_path / "legacy.db"
    _create_legacy_db(db_file)

    test_engine = create_engine(f"sqlite:///{db_file}", connect_args={"check_same_thread": False})
    TestSessionLocal = sessionmaker(bind=test_engine, autoflush=False, autocommit=False)
    monkeypatch.setattr(database, "engine", test_engine)
    monkeypatch.setattr(database, "SessionLocal", TestSessionLocal)

    database.init_db()

    from models import Artikel, Ingredient, FridgeStaple, WatchlistItem, FridgeItem

    db = TestSessionLocal()
    try:
        artikel_names = sorted(a.name for a in db.query(Artikel).all())
        # "Gouda" (Ingredient x2 exakt gleich normalisiert + FridgeStaple) -> EIN Artikel
        # "Gouda gerieben" (aehnlich, nicht identisch) -> eigener Artikel, NICHT zusammengefuehrt
        assert artikel_names == ["Gouda", "Gouda gerieben", "Mehl"]

        gouda = db.query(Artikel).filter(Artikel.name == "Gouda").first()
        ingredients = db.query(Ingredient).filter(Ingredient.artikel_id == gouda.id).all()
        assert len(ingredients) == 2  # beide "Gouda"/"gouda"-Zeilen zeigen auf denselben Artikel

        staple = db.query(FridgeStaple).first()
        assert staple.artikel_id == gouda.id  # dieselbe Artikel-Referenz wie die Ingredient-Zeilen

        watchlist = db.query(WatchlistItem).first()
        mehl = db.query(Artikel).filter(Artikel.name == "Mehl").first()
        assert watchlist.artikel_id == mehl.id

        fridge_item = db.query(FridgeItem).first()
        gouda_gerieben = db.query(Artikel).filter(Artikel.name == "Gouda gerieben").first()
        assert fridge_item.artikel_id == gouda_gerieben.id
    finally:
        db.close()


def test_migration_is_idempotent_noop_on_fresh_or_already_migrated_db(client):
    """Der `client`-Fixture-DB (bereits im neuen Schema erstellt) darf ein
    zweiter init_db()-Aufruf nichts kaputt machen."""
    import database
    database.init_db()  # zweiter Aufruf, darf nicht scheitern
    from models import Artikel
    db = database.SessionLocal()
    try:
        assert db.query(Artikel).count() == 0  # frische Test-DB, keine Legacy-Daten zum Migrieren
    finally:
        db.close()
