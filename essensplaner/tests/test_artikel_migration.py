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

        CREATE INDEX ix_ingredients_id ON ingredients (id);
        CREATE INDEX ix_fridge_staples_id ON fridge_staples (id);
        CREATE INDEX ix_watchlist_items_id ON watchlist_items (id);
        CREATE INDEX ix_fridge_items_id ON fridge_items (id);

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


def test_migration_resumes_after_interruption_between_create_all_and_populate(tmp_path, monkeypatch):
    """Simuliert einen Container-Neustart genau in der Luecke zwischen
    create_all() (neue, leere Tabellen bereits angelegt) und
    _populate_artikel_from_legacy_tables() (Alt-Daten noch nicht
    uebernommen). Die *_old-Tabellen mit den echten Nutzerdaten liegen in
    diesem Zustand noch unangetastet auf der Platte. Ein erneuter
    init_db()-Aufruf muss das erkennen und die Migration zu Ende fuehren,
    statt die Alt-Daten fuer immer zu ignorieren."""
    import database
    from models import Base

    db_file = tmp_path / "legacy.db"
    _create_legacy_db(db_file)

    test_engine = create_engine(f"sqlite:///{db_file}", connect_args={"check_same_thread": False})
    TestSessionLocal = sessionmaker(bind=test_engine, autoflush=False, autocommit=False)
    monkeypatch.setattr(database, "engine", test_engine)
    monkeypatch.setattr(database, "SessionLocal", TestSessionLocal)

    # Schritt 1+2 einer Migration von Hand nachstellen, Schritt 3
    # (populate) absichtlich auslassen -> exakt der "interrupted" Zustand
    # aus dem Review-Finding.
    needs_migration = database._rename_legacy_artikel_tables_if_needed()
    assert needs_migration is True
    Base.metadata.create_all(bind=test_engine)

    # Zwischenzustand verifizieren: neue Tabellen sind leer, Alt-Tabellen
    # mit den echten Daten liegen noch unangetastet vor.
    with test_engine.connect() as conn:
        from sqlalchemy import text as sa_text
        assert conn.execute(sa_text("SELECT COUNT(*) FROM ingredients")).scalar() == 0
        assert conn.execute(sa_text("SELECT COUNT(*) FROM ingredients_old")).scalar() == 2

    # Prozess "startet neu": init_db() von diesem unterbrochenen Zustand aus.
    database.init_db()

    from models import Artikel, Ingredient, FridgeStaple, WatchlistItem, FridgeItem

    db = TestSessionLocal()
    try:
        artikel_names = sorted(a.name for a in db.query(Artikel).all())
        assert artikel_names == ["Gouda", "Gouda gerieben", "Mehl"]

        gouda = db.query(Artikel).filter(Artikel.name == "Gouda").first()
        ingredients = db.query(Ingredient).filter(Ingredient.artikel_id == gouda.id).all()
        assert len(ingredients) == 2

        staple = db.query(FridgeStaple).first()
        assert staple.artikel_id == gouda.id

        watchlist = db.query(WatchlistItem).first()
        mehl = db.query(Artikel).filter(Artikel.name == "Mehl").first()
        assert watchlist.artikel_id == mehl.id

        fridge_item = db.query(FridgeItem).first()
        gouda_gerieben = db.query(Artikel).filter(Artikel.name == "Gouda gerieben").first()
        assert fridge_item.artikel_id == gouda_gerieben.id
    finally:
        db.close()

    # _old-Tabellen muessen nach abgeschlossener Migration weg sein.
    with test_engine.connect() as conn:
        from sqlalchemy import text as sa_text
        assert conn.execute(
            sa_text("SELECT name FROM sqlite_master WHERE type='table' AND name='ingredients_old'")
        ).first() is None


def test_migration_does_not_collide_on_legacy_indexes(tmp_path, monkeypatch):
    """Reproduziert den Index-Namenskollisions-Absturz: SQLite benennt beim
    Umbenennen einer Tabelle ihre Indexe NICHT mit um. Ohne den Fix schlaegt
    das anschliessende create_all() mit "index ix_ingredients_id already
    exists" fehl, weil der Name noch der *_old-Tabelle gehoert."""
    import database

    db_file = tmp_path / "legacy.db"
    _create_legacy_db(db_file)

    test_engine = create_engine(f"sqlite:///{db_file}", connect_args={"check_same_thread": False})
    TestSessionLocal = sessionmaker(bind=test_engine, autoflush=False, autocommit=False)
    monkeypatch.setattr(database, "engine", test_engine)
    monkeypatch.setattr(database, "SessionLocal", TestSessionLocal)

    database.init_db()  # darf NICHT mit "index already exists" abstuerzen

    from models import Ingredient

    db = TestSessionLocal()
    try:
        assert db.query(Ingredient).count() == 2  # Migration ist trotzdem vollstaendig durchgelaufen
    finally:
        db.close()

    # Die Indexe muessen unter denselben Namen wieder existieren (jetzt auf
    # den neuen, artikel_id-basierten Tabellen).
    with test_engine.connect() as conn:
        from sqlalchemy import text as sa_text
        index_names = {
            row[0] for row in conn.execute(
                sa_text("SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'ix_%'")
            )
        }
    for expected in ("ix_ingredients_id", "ix_fridge_staples_id", "ix_watchlist_items_id", "ix_fridge_items_id"):
        assert expected in index_names


def test_migration_skips_orphaned_ingredient_instead_of_crashing(tmp_path, monkeypatch):
    """Seit PRAGMA foreign_keys=ON (siehe database.py Engine-Connect-Hook)
    wuerde eine Zutat, deren recipe_id auf kein vorhandenes Rezept zeigt
    (z.B. historischer Datenbestand von vor Fix A der Rezept-Loeschroute,
    die frueher PlanEntry-Zeilen verwaist liess, oder eine manuell
    editierte DB), die Migration mit einem IntegrityError abbrechen -
    und zwar dauerhaft, da _rename_legacy_artikel_tables_if_needed() bei
    jedem Neustart erneut denselben Populate-Schritt versucht. Diese Zeile
    muss stattdessen uebersprungen werden, die uebrige Migration muss
    trotzdem vollstaendig durchlaufen."""
    import sqlite3
    import database

    db_file = tmp_path / "legacy_orphan.db"
    conn = sqlite3.connect(str(db_file))
    conn.executescript("""
        CREATE TABLE recipes (id INTEGER PRIMARY KEY, title TEXT NOT NULL, base_servings INTEGER,
            instructions TEXT, image_path TEXT, is_favorite BOOLEAN, source TEXT, tags TEXT);
        CREATE TABLE ingredients (id INTEGER PRIMARY KEY, recipe_id INTEGER, name TEXT NOT NULL,
            amount REAL, unit TEXT);
        CREATE TABLE fridge_staples (id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, unit TEXT);
        CREATE TABLE watchlist_items (id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, unit TEXT);
        CREATE TABLE fridge_items (id INTEGER PRIMARY KEY, name TEXT NOT NULL, amount REAL, unit TEXT);
        CREATE TABLE settings (id INTEGER PRIMARY KEY);

        CREATE INDEX ix_ingredients_id ON ingredients (id);
        CREATE INDEX ix_fridge_staples_id ON fridge_staples (id);
        CREATE INDEX ix_watchlist_items_id ON watchlist_items (id);
        CREATE INDEX ix_fridge_items_id ON fridge_items (id);

        INSERT INTO recipes (id, title, base_servings, instructions, is_favorite, source, tags)
            VALUES (1, 'Kaesebrot', 4, '', 0, 'manual', '');
        -- gueltig, zeigt auf Rezept 1:
        INSERT INTO ingredients (id, recipe_id, name, amount, unit) VALUES (1, 1, 'Gouda', 200, 'g');
        -- verwaist, recipe_id 999 existiert nicht:
        INSERT INTO ingredients (id, recipe_id, name, amount, unit) VALUES (2, 999, 'Geisterzutat', 1, 'Stueck');
    """)
    conn.commit()
    conn.close()

    test_engine = create_engine(f"sqlite:///{db_file}", connect_args={"check_same_thread": False})
    TestSessionLocal = sessionmaker(bind=test_engine, autoflush=False, autocommit=False)
    monkeypatch.setattr(database, "engine", test_engine)
    monkeypatch.setattr(database, "SessionLocal", TestSessionLocal)

    database.init_db()  # darf NICHT mit IntegrityError abstuerzen

    from models import Artikel, Ingredient

    db = TestSessionLocal()
    try:
        assert db.query(Ingredient).count() == 1  # nur die gueltige Zutat wurde migriert
        assert {a.name for a in db.query(Artikel).all()} == {"Gouda"}  # "Geisterzutat" wurde uebersprungen, kein Artikel dafuer angelegt
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
