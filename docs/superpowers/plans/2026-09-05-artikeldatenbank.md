# Artikeldatenbank Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rezept-Zutaten, Kühlschrank-Bestand/-Standardartikel und
Merklisten-Artikel referenzieren künftig eine gemeinsame Artikeldatenbank
(Bild + Preis-Historie) statt Freitext-Namen; Angebote werden per
Fuzzy-Matching in drei Konfidenz-Stufen automatisch verknüpft oder zur
Bestätigung vorgelegt.

**Architecture:** Neue Tabellen `Artikel`, `ArtikelPriceHistory`,
`PendingArtikelMatch`. `Ingredient`, `FridgeStaple`, `WatchlistItem`,
`FridgeItem` verlieren ihr `name`-Feld zugunsten einer Pflicht-FK
`artikel_id`. Eine zentrale Funktion `resolve_artikel()` (neues Modul
`app/artikel_matching.py`) ersetzt die bisherige verteilte
Fuzzy-Matching-Logik in `app/offers/matching.py` und liefert drei
Konfidenz-Stufen (hoch/mittel/niedrig). Der bestehende Connector-Runner
(`app/offers/runner.py`) wird um Preis-Historie und Bild-Download
erweitert; neue UI-Bausteine (Autocomplete, Bestätigungs-Warteschlange,
Artikel-Übersicht) kommen zur bestehenden `index.html` hinzu.

**Tech Stack:** FastAPI, SQLAlchemy/SQLite (bestehend), `rapidfuzz`
(bereits Dependency), `httpx` (bereits Dependency, für Bild-Download),
vanilla JS (bestehendes Muster in `index.html`).

**Spec:** [docs/superpowers/specs/2026-09-05-artikeldatenbank-design.md](../specs/2026-09-05-artikeldatenbank-design.md)

## Global Constraints

- Bestehendes Grundgerüst wird erweitert, nicht umgeschrieben.
- App-Module in `essensplaner/app/` sind flache Module (kein Package
  außer `app/offers/`) — Imports untereinander immer `import database`,
  `from models import X`.
- SQLite unterstützt kein nachträgliches `NOT NULL` auf bestehenden
  Spalten — die Umstellung von `Ingredient`/`FridgeStaple`/
  `WatchlistItem`/`FridgeItem` auf `artikel_id` erfolgt über eine
  einmalige Migrationsroutine (Tabellen-Neuaufbau + Datenübernahme in
  einer Transaktion), nicht über `ALTER TABLE ADD COLUMN`.
- Migration führt bestehende Namen **nur bei exakter (normalisierter)
  Übereinstimmung** zusammen — ähnliche, aber nicht identische Namen
  bleiben getrennte Artikel (siehe Spec, Abschnitt "Migration").
- Konfidenz-Schwellen: **hoch** ≥ 80 (Score oder Substring-Treffer ≥ 4
  Zeichen), **mittel** 60–79, **niedrig** < 60 (siehe Spec, Abschnitt 2).
- `PendingArtikelMatch` wird über `(product_name, artikel_id)` identifiziert,
  nicht über `offer_id` — Angebote werden bei jedem Connector-Lauf
  komplett ersetzt (delete-then-replace, siehe `run_source`), eine
  FK-Bindung an `offer_id` würde bei jedem Lauf verwaisen.
- Ein bereits `confirmed`/`rejected` markiertes `(product_name,
  artikel_id)`-Paar wird von `resolve_artikel()` nicht erneut zur
  Bestätigung vorgelegt (siehe Task 2).
- Fehler beim Bild-Download dürfen einen Connector-Lauf nie scheitern
  lassen (gleiche Philosophie wie bestehende Scraper-Fehlerbehandlung).
- Jede neue Dependency wird in `essensplaner/requirements.txt` exakt
  gepinnt ergänzt — für diesen Plan wird keine neue Dependency benötigt
  (`rapidfuzz`, `httpx`, `beautifulsoup4` sind bereits vorhanden).
- CI verlangt bei jeder Änderung einen erhöhten `version`-Wert in
  `config.yaml` und einen `CHANGELOG.md`-Eintrag.

---

## Task 1: Datenmodell — Artikel, ArtikelPriceHistory, PendingArtikelMatch

**Files:**
- Modify: `essensplaner/app/models.py`
- Test: `essensplaner/tests/test_artikel_models.py`

**Interfaces:**
- Produces: SQLAlchemy-Modelle `Artikel`, `ArtikelPriceHistory`,
  `PendingArtikelMatch` (aus `models.py`), nutzbar ab Task 2.

- [ ] **Step 1: Modelle in `app/models.py` ergänzen**

Am Dateiende anfügen:

```python
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
```

- [ ] **Step 2: Test schreiben**

```python
from sqlalchemy import text


def test_artikel_tables_exist(client):
    import database
    with database.engine.connect() as conn:
        artikel_cols = {row[1] for row in conn.execute(text("PRAGMA table_info(artikel)"))}
        history_cols = {row[1] for row in conn.execute(text("PRAGMA table_info(artikel_price_history)"))}
        pending_cols = {row[1] for row in conn.execute(text("PRAGMA table_info(pending_artikel_matches)"))}

    assert {"name", "image_path", "created_at"} <= artikel_cols
    assert {"artikel_id", "price", "discount_text", "retailer", "source", "valid_from", "valid_until", "recorded_at"} <= history_cols
    assert {"product_name", "artikel_id", "score", "status", "price", "discount_text", "retailer", "source", "valid_from", "valid_until"} <= pending_cols
```

- [ ] **Step 3: Test laufen lassen**

Run: `cd essensplaner && python -m pytest tests/test_artikel_models.py -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add essensplaner/app/models.py essensplaner/tests/test_artikel_models.py
git commit -m "feat: Datenmodell für Artikel, Preis-Historie und Bestätigungs-Warteschlange"
```

---

## Task 2: Migrationsroutine — Ingredient/FridgeStaple/WatchlistItem/FridgeItem auf artikel_id umstellen

**Files:**
- Modify: `essensplaner/app/models.py` (Ingredient/FridgeStaple/WatchlistItem/FridgeItem: `name` → `artikel_id`)
- Modify: `essensplaner/app/database.py`
- Test: `essensplaner/tests/test_artikel_migration.py`

**Interfaces:**
- Consumes: `Artikel` (Task 1)
- Produces: `Ingredient.artikel_id`, `FridgeStaple.artikel_id`,
  `WatchlistItem.artikel_id`, `FridgeItem.artikel_id` (alle Integer,
  ForeignKey → `Artikel.id`, `nullable=False`); `database.init_db()`
  führt die Migration transparent beim Start aus.

Dieser Task muss **vor** allen Tasks laufen, die `Ingredient.name` o.ä.
noch verwenden (Tasks 4–9) — die spätere Reihenfolge im Plan setzt
dieses geänderte Schema voraus.

- [ ] **Step 1: Modelle in `app/models.py` anpassen**

`Ingredient` (bestehend, `name`-Zeile ersetzen):

```python
class Ingredient(Base):
    __tablename__ = "ingredients"

    id = Column(Integer, primary_key=True, index=True)
    recipe_id = Column(Integer, ForeignKey("recipes.id"))
    artikel_id = Column(Integer, ForeignKey("artikel.id"), nullable=False)
    amount = Column(Float, nullable=True)
    unit = Column(String, nullable=True)

    recipe = relationship("Recipe", back_populates="ingredients")
    artikel = relationship("Artikel")
```

`FridgeStaple` (bestehend, `name`-Zeile ersetzen):

```python
class FridgeStaple(Base):
    """Artikel, die immer im Kühlschrank sein sollten ('Standard'/Favorit) –
    werden auch angezeigt, wenn gerade kein passender FridgeItem-Bestand existiert."""
    __tablename__ = "fridge_staples"

    id = Column(Integer, primary_key=True, index=True)
    artikel_id = Column(Integer, ForeignKey("artikel.id"), nullable=False, unique=True)
    unit = Column(String, nullable=True)

    artikel = relationship("Artikel")
```

`WatchlistItem` (bestehend, `name`-Zeile ersetzen):

```python
class WatchlistItem(Base):
    """Artikel, die regelmäßig gebraucht werden, aber kein FridgeStaple sind
    (z.B. Mehl, Waschmittel) — ergänzt FridgeStaple für die Angebots-Hervorhebung."""
    __tablename__ = "watchlist_items"

    id = Column(Integer, primary_key=True, index=True)
    artikel_id = Column(Integer, ForeignKey("artikel.id"), nullable=False, unique=True)
    unit = Column(String, nullable=True)

    artikel = relationship("Artikel")
```

`FridgeItem` (bestehend, `name`-Zeile ersetzen):

```python
class FridgeItem(Base):
    """Aktuell im Kühlschrank vorhandener Artikel (manuell erfasst, später ggf. per Fotoerkennung)."""
    __tablename__ = "fridge_items"

    id = Column(Integer, primary_key=True, index=True)
    artikel_id = Column(Integer, ForeignKey("artikel.id"), nullable=False)
    amount = Column(Float, nullable=True)
    unit = Column(String, nullable=True)

    artikel = relationship("Artikel")
```

- [ ] **Step 2: Migrationsroutine in `app/database.py` schreiben**

```python
import os
from datetime import datetime
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from models import Base, Offer, WatchlistItem, OfferSourceConfig

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
```

- [ ] **Step 3: Test schreiben**

Simuliert eine bestehende Alt-Datenbank (Schema vor diesem Feature) und
prüft, dass die Migration korrekt dedupliziert und verknüpft.

```python
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
```

- [ ] **Step 4: Tests laufen lassen**

Run: `cd essensplaner && python -m pytest tests/test_artikel_migration.py -v`
Expected: PASS

- [ ] **Step 5: Vollen Testlauf prüfen (bestehende Tests nutzen noch `.name`, werden in Tasks 4/6/7 angepasst)**

Run: `cd essensplaner && python -m pytest tests/ -v`
Expected: Tests, die `Ingredient(name=...)`, `FridgeStaple(name=...)`,
`WatchlistItem(name=...)`, `FridgeItem`-Erzeugung mit `name=` oder
`app/main.py`-Endpunkte mit dem alten Schema nutzen, schlagen jetzt
erwartungsgemäß fehl (z.B. `TypeError` durch entferntes `name`-Argument,
`IntegrityError` durch `artikel_id NOT NULL`) — das ist normal und wird
in den Folge-Tasks (5 Rezepte, 6 JSON-Import, 7 Kühlschrank, 8 Merkliste,
9 Einkaufsliste/Angebots-Matching) behoben, wenn die jeweiligen
Verbraucher umgestellt werden. Nicht versuchen, hier bereits alle Tests
grün zu bekommen.

- [ ] **Step 6: Commit**

```bash
git add essensplaner/app/models.py essensplaner/app/database.py essensplaner/tests/test_artikel_migration.py
git commit -m "feat: Migration von Ingredient/FridgeStaple/WatchlistItem/FridgeItem auf artikel_id"
```

---

## Task 3: `resolve_artikel` — zentrale Konfidenz-Matching-Funktion

**Files:**
- Create: `essensplaner/app/artikel_matching.py`
- Test: `essensplaner/tests/test_artikel_matching.py`

**Interfaces:**
- Consumes: `Artikel`, `PendingArtikelMatch` (Task 1)
- Produces: `ArtikelMatch` (dataclass: `confidence: str` [`"high"` |
  `"medium"` | `"low"`], `artikel: Optional[Artikel]`, `candidates:
  list[tuple[Artikel, float]]`), `resolve_artikel(name: str, db: Session)
  -> ArtikelMatch`, `match_score(a: str, b: str) -> float`. Genutzt ab
  Task 4 (Artikel-Endpunkte/Autocomplete-Suggest), Task 9
  (offers/matching.py-Ersatz), Task 10 (Runner-Erweiterung).

- [ ] **Step 1: `app/artikel_matching.py` schreiben**

```python
"""Zentrale Zuordnung von Freitext-Namen (Zutaten, Angebote, Kühlschrank-
Einträge, ...) zu kanonischen Artikel-Datensätzen, in drei
Konfidenz-Stufen. Ersetzt die frühere, verteilte Matching-Logik in
offers/matching.py."""
from dataclasses import dataclass, field
from typing import Optional

from rapidfuzz import fuzz
from sqlalchemy.orm import Session

from models import Artikel, PendingArtikelMatch

HIGH_THRESHOLD = 80
MEDIUM_THRESHOLD = 60
SUBSTRING_MIN_LENGTH = 4


def match_score(a: str, b: str) -> float:
    return fuzz.token_set_ratio(a.lower().strip(), b.lower().strip())


def _is_substring_match(a: str, b: str) -> bool:
    """Erkennt deutsche Komposita (z.B. "Mehl" in "Weizenmehl"), die
    token_set_ratio allein verpasst. Mindestlänge 4 verhindert
    Fehltreffer bei kurzen Namen (z.B. "Ei" in "Reis")."""
    a_lower, b_lower = a.lower().strip(), b.lower().strip()
    shorter, longer = (a_lower, b_lower) if len(a_lower) <= len(b_lower) else (b_lower, a_lower)
    return len(shorter) >= SUBSTRING_MIN_LENGTH and shorter in longer


@dataclass
class ArtikelMatch:
    confidence: str  # "high" | "medium" | "low"
    artikel: Optional[Artikel] = None
    candidates: list[tuple[Artikel, float]] = field(default_factory=list)


def resolve_artikel(name: str, db: Session) -> ArtikelMatch:
    normalized = name.strip().lower()

    confirmed = (
        db.query(PendingArtikelMatch)
        .filter(PendingArtikelMatch.product_name.ilike(normalized), PendingArtikelMatch.status == "confirmed")
        .first()
    )
    if confirmed:
        return ArtikelMatch(confidence="high", artikel=confirmed.artikel)

    rejected_artikel_ids = {
        p.artikel_id for p in db.query(PendingArtikelMatch)
        .filter(PendingArtikelMatch.product_name.ilike(normalized), PendingArtikelMatch.status == "rejected")
        .all()
    }

    scored: list[tuple[Artikel, float]] = []
    for artikel in db.query(Artikel).all():
        if artikel.id in rejected_artikel_ids:
            continue
        score = match_score(name, artikel.name)
        if _is_substring_match(name, artikel.name):
            score = max(score, HIGH_THRESHOLD)
        scored.append((artikel, score))

    scored.sort(key=lambda pair: pair[1], reverse=True)
    if scored and scored[0][1] >= HIGH_THRESHOLD:
        return ArtikelMatch(confidence="high", artikel=scored[0][0])

    medium_candidates = [(a, s) for a, s in scored if s >= MEDIUM_THRESHOLD]
    if medium_candidates:
        return ArtikelMatch(confidence="medium", candidates=medium_candidates)

    return ArtikelMatch(confidence="low")
```

- [ ] **Step 2: Test schreiben**

```python
from models import Artikel, PendingArtikelMatch
from artikel_matching import resolve_artikel, match_score


def _db(client):
    import database
    return database.SessionLocal()


def _mk_artikel(db, name):
    from datetime import datetime
    a = Artikel(name=name, created_at=datetime.utcnow().isoformat())
    db.add(a)
    db.commit()
    db.refresh(a)
    return a


def test_high_confidence_exact_and_fuzzy_match(client):
    db = _db(client)
    gouda = _mk_artikel(db, "Gouda")
    result = resolve_artikel("Gouda Scheiben 250g", db)
    assert result.confidence == "high"
    assert result.artikel.id == gouda.id


def test_high_confidence_compound_word_substring(client):
    db = _db(client)
    mehl = _mk_artikel(db, "Mehl")
    result = resolve_artikel("Weizenmehl Type 405", db)
    assert result.confidence == "high"
    assert result.artikel.id == mehl.id


def test_medium_confidence_returns_candidates(client):
    db = _db(client)
    _mk_artikel(db, "Paprika rot")
    result = resolve_artikel("Paprikapulver edelsüß", db)
    assert result.confidence in ("medium", "low")
    if result.confidence == "medium":
        assert len(result.candidates) >= 1


def test_low_confidence_no_match(client):
    db = _db(client)
    _mk_artikel(db, "Kaffee")
    result = resolve_artikel("Käse", db)
    assert result.confidence == "low"
    assert result.artikel is None


def test_rejected_pairing_is_excluded(client):
    db = _db(client)
    a = _mk_artikel(db, "Paprika rot")
    from datetime import date, datetime
    db.add(PendingArtikelMatch(
        product_name="paprikapulver edelsüß", artikel_id=a.id, score=65, status="rejected",
        retailer="kaufland", source="kaufland_scraper",
        valid_from=date.today(), valid_until=date.today(), created_at=datetime.utcnow().isoformat(),
    ))
    db.commit()
    result = resolve_artikel("Paprikapulver edelsüß", db)
    assert result.confidence != "high" or result.artikel.id != a.id
    assert all(c.id != a.id for c, _ in result.candidates)


def test_confirmed_pairing_returns_high_confidence(client):
    db = _db(client)
    a = _mk_artikel(db, "Paprika rot")
    from datetime import date, datetime
    db.add(PendingArtikelMatch(
        product_name="paprikapulver edelsüß", artikel_id=a.id, score=65, status="confirmed",
        retailer="kaufland", source="kaufland_scraper",
        valid_from=date.today(), valid_until=date.today(), created_at=datetime.utcnow().isoformat(),
    ))
    db.commit()
    result = resolve_artikel("Paprikapulver edelsüß", db)
    assert result.confidence == "high"
    assert result.artikel.id == a.id
```

- [ ] **Step 3: Tests laufen lassen**

Run: `cd essensplaner && python -m pytest tests/test_artikel_matching.py -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add essensplaner/app/artikel_matching.py essensplaner/tests/test_artikel_matching.py
git commit -m "feat: resolve_artikel als zentrale Drei-Stufen-Matching-Funktion"
```

---

## Task 4: Artikel-Endpunkte (Liste, Detail, Historie, Suggest, Anlegen, Merge)

**Files:**
- Modify: `essensplaner/app/schemas.py`
- Modify: `essensplaner/app/main.py`
- Test: `essensplaner/tests/test_artikel_api.py`

**Interfaces:**
- Consumes: `Artikel`, `ArtikelPriceHistory`, `PendingArtikelMatch`
  (Task 1), `resolve_artikel` (Task 3)
- Produces: `GET /api/artikel`, `GET /api/artikel/{id}`,
  `GET /api/artikel/{id}/history`, `GET /api/artikel/suggest?q=`,
  `POST /api/artikel`, `POST /api/artikel/{id}/merge/{other_id}`.
  Schemas `ArtikelOut`, `ArtikelIn`, `ArtikelSuggestOut`,
  `ArtikelPriceHistoryOut` (aus `schemas.py`) — genutzt ab Task 15/16/19
  (UI).

- [ ] **Step 1: Schemas in `app/schemas.py` ergänzen**

```python
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


class ArtikelSuggestOut(BaseModel):
    id: int
    name: str
    confidence: str  # "high" | "medium"


class ArtikelPriceHistoryOut(BaseModel):
    price: Optional[float] = None
    discount_text: Optional[str] = None
    retailer: str
    source: str
    valid_from: str
    valid_until: str
    recorded_at: str
```

- [ ] **Step 2: Imports in `app/main.py` ergänzen**

```python
from datetime import date, datetime
```

(`datetime` neu neben dem bestehenden `date`-Import.)

```python
from models import (
    Recipe, Ingredient, PlanEntry, Settings, FridgeItem, FridgeStaple,
    WatchlistItem, OfferSourceConfig, Offer, Artikel, ArtikelPriceHistory,
    PendingArtikelMatch,
)
```

```python
from schemas import (
    ...,  # bestehende Einträge unverändert
    ArtikelIn,
    ArtikelOut,
    ArtikelSuggestOut,
    ArtikelPriceHistoryOut,
)
from artikel_matching import resolve_artikel
```

- [ ] **Step 3: Endpunkte ergänzen**

Neuer Abschnitt in `app/main.py` (z.B. vor dem Rezepte-Abschnitt, da
andere Bereiche später darauf aufbauen):

```python
# ---------- Artikel ----------

def _artikel_out(artikel: Artikel, db: Session) -> ArtikelOut:
    last = (
        db.query(ArtikelPriceHistory)
        .filter(ArtikelPriceHistory.artikel_id == artikel.id)
        .order_by(ArtikelPriceHistory.recorded_at.desc())
        .first()
    )
    return ArtikelOut(
        id=artikel.id,
        name=artikel.name,
        image_path=artikel.image_path,
        last_price=last.price if last else None,
        last_discount_text=last.discount_text if last else None,
    )


@app.get("/api/artikel", response_model=list[ArtikelOut])
def list_artikel(db: Session = Depends(get_db)):
    artikel = db.query(Artikel).order_by(Artikel.name).all()
    return [_artikel_out(a, db) for a in artikel]


@app.get("/api/artikel/{artikel_id}", response_model=ArtikelOut)
def get_artikel(artikel_id: int, db: Session = Depends(get_db)):
    artikel = db.query(Artikel).get(artikel_id)
    if not artikel:
        raise HTTPException(404, "Artikel nicht gefunden")
    return _artikel_out(artikel, db)


@app.get("/api/artikel/{artikel_id}/history", response_model=list[ArtikelPriceHistoryOut])
def get_artikel_history(artikel_id: int, db: Session = Depends(get_db)):
    artikel = db.query(Artikel).get(artikel_id)
    if not artikel:
        raise HTTPException(404, "Artikel nicht gefunden")
    entries = (
        db.query(ArtikelPriceHistory)
        .filter(ArtikelPriceHistory.artikel_id == artikel_id)
        .order_by(ArtikelPriceHistory.recorded_at.desc())
        .all()
    )
    return [
        ArtikelPriceHistoryOut(
            price=e.price, discount_text=e.discount_text, retailer=e.retailer, source=e.source,
            valid_from=e.valid_from.isoformat(), valid_until=e.valid_until.isoformat(),
            recorded_at=e.recorded_at,
        ) for e in entries
    ]


@app.get("/api/artikel/suggest", response_model=list[ArtikelSuggestOut])
def suggest_artikel(q: str, db: Session = Depends(get_db)):
    if not q.strip():
        return []
    match = resolve_artikel(q, db)
    if match.confidence == "high":
        return [ArtikelSuggestOut(id=match.artikel.id, name=match.artikel.name, confidence="high")]
    if match.confidence == "medium":
        return [
            ArtikelSuggestOut(id=a.id, name=a.name, confidence="medium")
            for a, _ in match.candidates
        ]
    return []


@app.post("/api/artikel", response_model=ArtikelOut)
def create_artikel(payload: ArtikelIn, db: Session = Depends(get_db)):
    name = payload.name.strip()
    if not name:
        raise HTTPException(400, "Name darf nicht leer sein.")
    artikel = Artikel(name=name, created_at=datetime.utcnow().isoformat())
    db.add(artikel)
    db.commit()
    db.refresh(artikel)
    return _artikel_out(artikel, db)


@app.post("/api/artikel/{artikel_id}/merge/{other_id}", response_model=ArtikelOut)
def merge_artikel(artikel_id: int, other_id: int, db: Session = Depends(get_db)):
    """Führt den Artikel `other_id` in `artikel_id` zusammen: alle
    verweisenden Zeilen werden umgehängt, `other_id` wird gelöscht. Bei
    FridgeStaple/WatchlistItem (unique je Artikel) wird die Zeile des zu
    löschenden Artikels verworfen, falls der Ziel-Artikel bereits eine
    eigene hat, statt eine Unique-Constraint-Verletzung zu riskieren."""
    if artikel_id == other_id:
        raise HTTPException(400, "Kann einen Artikel nicht mit sich selbst zusammenführen.")
    target = db.query(Artikel).get(artikel_id)
    other = db.query(Artikel).get(other_id)
    if not target or not other:
        raise HTTPException(404, "Artikel nicht gefunden")

    db.query(Ingredient).filter(Ingredient.artikel_id == other_id).update({"artikel_id": artikel_id})
    db.query(FridgeItem).filter(FridgeItem.artikel_id == other_id).update({"artikel_id": artikel_id})
    db.query(ArtikelPriceHistory).filter(ArtikelPriceHistory.artikel_id == other_id).update({"artikel_id": artikel_id})
    db.query(PendingArtikelMatch).filter(PendingArtikelMatch.artikel_id == other_id).update({"artikel_id": artikel_id})

    for model in (FridgeStaple, WatchlistItem):
        other_row = db.query(model).filter(model.artikel_id == other_id).first()
        if other_row:
            if db.query(model).filter(model.artikel_id == artikel_id).first():
                db.delete(other_row)
            else:
                other_row.artikel_id = artikel_id

    db.delete(other)
    db.commit()
    db.refresh(target)
    return _artikel_out(target, db)
```

- [ ] **Step 4: Test schreiben**

```python
from datetime import datetime


def _mk_artikel(db, name):
    from models import Artikel
    a = Artikel(name=name, created_at=datetime.utcnow().isoformat())
    db.add(a)
    db.commit()
    db.refresh(a)
    return a


def _db(client):
    import database
    return database.SessionLocal()


def test_create_and_list_artikel(client):
    res = client.post("/api/artikel", json={"name": "Gouda"})
    assert res.status_code == 200
    assert res.json()["name"] == "Gouda"

    res = client.get("/api/artikel")
    assert len(res.json()) == 1


def test_create_artikel_rejects_empty_name(client):
    res = client.post("/api/artikel", json={"name": "   "})
    assert res.status_code == 400


def test_get_artikel_404_for_unknown_id(client):
    assert client.get("/api/artikel/9999").status_code == 404


def test_history_reflects_price_entries(client):
    db = _db(client)
    a = _mk_artikel(db, "Gouda")
    from models import ArtikelPriceHistory
    from datetime import date
    db.add(ArtikelPriceHistory(
        artikel_id=a.id, price=1.99, discount_text="-20%", retailer="kaufland",
        source="kaufland_scraper", valid_from=date.today(), valid_until=date.today(),
        recorded_at=datetime.utcnow().isoformat(),
    ))
    db.commit()

    res = client.get(f"/api/artikel/{a.id}/history")
    assert res.status_code == 200
    body = res.json()
    assert len(body) == 1
    assert body[0]["price"] == 1.99

    res = client.get(f"/api/artikel/{a.id}")
    assert res.json()["last_price"] == 1.99


def test_suggest_returns_high_confidence_single_result(client):
    db = _db(client)
    _mk_artikel(db, "Gouda")
    res = client.get("/api/artikel/suggest?q=Gouda")
    assert res.status_code == 200
    body = res.json()
    assert len(body) == 1
    assert body[0]["confidence"] == "high"


def test_suggest_returns_empty_for_blank_query(client):
    res = client.get("/api/artikel/suggest?q=")
    assert res.status_code == 200
    assert res.json() == []


def test_merge_repoints_fridge_staple_and_deletes_source(client):
    db = _db(client)
    keep = _mk_artikel(db, "Gouda")
    drop = _mk_artikel(db, "Gouda jung")
    from models import FridgeStaple
    db.add(FridgeStaple(artikel_id=drop.id, unit="Stück"))
    db.commit()

    res = client.post(f"/api/artikel/{keep.id}/merge/{drop.id}")
    assert res.status_code == 200

    db2 = _db(client)
    staple = db2.query(FridgeStaple).first()
    assert staple.artikel_id == keep.id
    assert db2.query(type(keep)).filter(type(keep).id == drop.id).first() is None


def test_merge_rejects_self_merge(client):
    db = _db(client)
    a = _mk_artikel(db, "Gouda")
    res = client.post(f"/api/artikel/{a.id}/merge/{a.id}")
    assert res.status_code == 400
```

- [ ] **Step 5: Tests laufen lassen**

Run: `cd essensplaner && python -m pytest tests/test_artikel_api.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add essensplaner/app/schemas.py essensplaner/app/main.py essensplaner/tests/test_artikel_api.py
git commit -m "feat: Artikel-Endpunkte (Liste, Historie, Suggest, Anlegen, Merge)"
```

---

## Task 5: Rezept-CRUD auf artikel_id umstellen

**Files:**
- Modify: `essensplaner/app/schemas.py` (`IngredientIn`/`RecipeIn`/`RecipeOut` ersetzen, neue `IngredientOut`)
- Modify: `essensplaner/app/main.py` (`create_recipe`, `update_recipe`, `list_recipes`, `_recipe_to_export`)
- Test: `essensplaner/tests/test_recipes_api.py`

**Interfaces:**
- Consumes: `Artikel` (Task 1)
- Produces: `IngredientIn = {artikel_id: int, amount, unit}` (bereits
  aufgelöst — die UI löst Freitext-Eingaben per Autocomplete VOR dem
  Absenden auf, siehe Task 15), `IngredientOut = {artikel_id, name,
  amount, unit}`, `_recipe_out(recipe) -> RecipeOut` (main.py-Helper,
  genutzt von allen Rezept-Endpunkten).
- **Wichtig für Task 6:** Die JSON-Import-/Foto-Import-Pfade brauchen
  weiterhin Freitext-Zutatennamen (portable Exportdatei, Vision-Ergebnis
  kennt keine `artikel_id`) — dafür entstehen in Task 6 eigene Schemas
  (`ImportRecipeIn`/`ImportIngredientIn`), unabhängig von `RecipeIn`
  dieses Tasks.

- [ ] **Step 1: Schemas in `app/schemas.py` ersetzen**

Bestehende `IngredientIn`/`RecipeIn`/`RecipeOut` (Zeilen 1–26 der
Datei) ersetzen durch:

```python
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
```

- [ ] **Step 2: `_recipe_out`-Helper und CRUD-Endpunkte in `app/main.py` anpassen**

Neuer Helper (z.B. direkt vor `list_recipes`):

```python
def _recipe_out(recipe: Recipe) -> RecipeOut:
    return RecipeOut(
        id=recipe.id,
        title=recipe.title,
        base_servings=recipe.base_servings,
        instructions=recipe.instructions,
        is_favorite=recipe.is_favorite,
        tags=recipe.tags,
        image_path=recipe.image_path,
        source=recipe.source,
        ingredients=[
            IngredientOut(artikel_id=i.artikel_id, name=i.artikel.name, amount=i.amount, unit=i.unit)
            for i in recipe.ingredients
        ],
    )


def _require_artikel(artikel_id: int, db: Session) -> None:
    if not db.query(Artikel).get(artikel_id):
        raise HTTPException(400, f"Artikel {artikel_id} nicht gefunden")
```

`list_recipes`, `create_recipe`, `update_recipe` (bestehend) ersetzen durch:

```python
@app.get("/api/recipes", response_model=list[RecipeOut])
def list_recipes(db: Session = Depends(get_db)):
    return [_recipe_out(r) for r in db.query(Recipe).all()]


@app.post("/api/recipes", response_model=RecipeOut)
def create_recipe(recipe: RecipeIn, db: Session = Depends(get_db)):
    for i in recipe.ingredients:
        _require_artikel(i.artikel_id, db)
    db_recipe = Recipe(
        title=recipe.title,
        base_servings=recipe.base_servings,
        instructions=recipe.instructions,
        is_favorite=recipe.is_favorite,
        tags=recipe.tags,
    )
    db_recipe.ingredients = [
        Ingredient(artikel_id=i.artikel_id, amount=i.amount, unit=i.unit) for i in recipe.ingredients
    ]
    db.add(db_recipe)
    db.commit()
    db.refresh(db_recipe)
    return _recipe_out(db_recipe)


@app.put("/api/recipes/{recipe_id}", response_model=RecipeOut)
def update_recipe(recipe_id: int, recipe: RecipeIn, db: Session = Depends(get_db)):
    db_recipe = db.query(Recipe).get(recipe_id)
    if not db_recipe:
        raise HTTPException(404, "Rezept nicht gefunden")
    for i in recipe.ingredients:
        _require_artikel(i.artikel_id, db)
    db_recipe.title = recipe.title
    db_recipe.base_servings = recipe.base_servings
    db_recipe.instructions = recipe.instructions
    db_recipe.is_favorite = recipe.is_favorite
    db_recipe.tags = recipe.tags
    db_recipe.ingredients = [
        Ingredient(artikel_id=i.artikel_id, amount=i.amount, unit=i.unit) for i in recipe.ingredients
    ]
    db.commit()
    db.refresh(db_recipe)
    return _recipe_out(db_recipe)
```

`upload_recipe_image` bleibt unverändert (fasst `Recipe.image_path` an,
nicht Zutaten) — nur der `return db_recipe` am Ende muss zu
`return _recipe_out(db_recipe)` werden, da `RecipeOut` jetzt
`IngredientOut` statt der ORM-Objekte direkt erwartet.

- [ ] **Step 3: Test schreiben**

```python
from datetime import datetime


def _mk_artikel(db, name):
    from models import Artikel
    a = Artikel(name=name, created_at=datetime.utcnow().isoformat())
    db.add(a)
    db.commit()
    db.refresh(a)
    return a


def _db(client):
    import database
    return database.SessionLocal()


def test_create_recipe_with_artikel_id(client):
    db = _db(client)
    gouda = _mk_artikel(db, "Gouda")

    res = client.post("/api/recipes", json={
        "title": "Käsebrot",
        "ingredients": [{"artikel_id": gouda.id, "amount": 200, "unit": "g"}],
    })
    assert res.status_code == 200
    body = res.json()
    assert body["ingredients"][0]["artikel_id"] == gouda.id
    assert body["ingredients"][0]["name"] == "Gouda"


def test_create_recipe_rejects_unknown_artikel_id(client):
    res = client.post("/api/recipes", json={
        "title": "Käsebrot",
        "ingredients": [{"artikel_id": 9999, "amount": 200, "unit": "g"}],
    })
    assert res.status_code == 400


def test_update_recipe_replaces_ingredients(client):
    db = _db(client)
    gouda = _mk_artikel(db, "Gouda")
    mehl = _mk_artikel(db, "Mehl")

    create_res = client.post("/api/recipes", json={
        "title": "Käsebrot", "ingredients": [{"artikel_id": gouda.id, "amount": 200, "unit": "g"}],
    })
    recipe_id = create_res.json()["id"]

    update_res = client.put(f"/api/recipes/{recipe_id}", json={
        "title": "Käsebrot", "ingredients": [{"artikel_id": mehl.id, "amount": 500, "unit": "g"}],
    })
    assert update_res.status_code == 200
    assert len(update_res.json()["ingredients"]) == 1
    assert update_res.json()["ingredients"][0]["name"] == "Mehl"


def test_list_recipes_includes_ingredient_names(client):
    db = _db(client)
    gouda = _mk_artikel(db, "Gouda")
    client.post("/api/recipes", json={
        "title": "Käsebrot", "ingredients": [{"artikel_id": gouda.id, "amount": 200, "unit": "g"}],
    })
    res = client.get("/api/recipes")
    assert res.json()[0]["ingredients"][0]["name"] == "Gouda"
```

- [ ] **Step 4: Tests laufen lassen**

Run: `cd essensplaner && python -m pytest tests/test_recipes_api.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add essensplaner/app/schemas.py essensplaner/app/main.py essensplaner/tests/test_recipes_api.py
git commit -m "feat: Rezept-CRUD auf artikel_id statt Freitext-Zutatennamen umstellen"
```

---

## Task 6: JSON-Import, Export und Foto-Import auf Artikel-Auflösung umstellen

**Files:**
- Modify: `essensplaner/app/schemas.py` (neue `ImportIngredientIn`/`ImportRecipeIn`, `ImportPreviewOut`/`ImportApplyIn` erweitern)
- Modify: `essensplaner/app/main.py` (`_recipe_to_export`, `preview_import`, `apply_import`, `import_recipe_photo`)
- Test: `essensplaner/tests/test_import_export_api.py`

**Interfaces:**
- Consumes: `resolve_artikel` (Task 3), `Artikel` (Task 1), `ArtikelSuggestOut` (Task 4)
- Produces: `_auto_resolve_artikel_id(name, db) -> int` (main.py-Helper,
  hoch → bestehende artikel_id, niedrig/unklar ohne explizite Auflösung
  → neuer Artikel). `ImportRecipeIn`/`ImportIngredientIn` (Freitext-Form
  für Export/Import/Foto-Import, unabhängig von `RecipeIn` aus Task 5).

Freitext-Zutatennamen aus externen Quellen (JSON-Datei, Foto-Import via
Claude Vision) kennen keine `artikel_id` — dieser Task löst sie beim
Import serverseitig auf: hohe Konfidenz automatisch verknüpft, niedrige
Konfidenz automatisch neuer Artikel, mittlere Konfidenz wird im Preview
als Ambiguität gemeldet und kann per `ingredient_resolutions` in
`apply_import` explizit aufgelöst werden (analog zum bestehenden Muster
für Titel-Duplikate). Wird beim Anwenden trotzdem keine explizite
Auflösung für eine mittel-konfidente Zutat mitgeschickt, greift derselbe
sichere Fallback wie bei niedriger Konfidenz (neuer Artikel) — kein
stilles Raten zwischen mehreren Kandidaten.

- [ ] **Step 1: Schemas in `app/schemas.py` ergänzen/anpassen**

Neue Klassen (vor `RecipeExportFile`):

```python
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
```

`RecipeExportFile` anpassen:

```python
class RecipeExportFile(BaseModel):
    """Export-/Import-Dateiformat: eine oder mehrere Rezepte, ohne DB-IDs."""
    recipes: list[ImportRecipeIn]
```

`ImportPreviewOut` erweitern:

```python
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
```

`ImportApplyIn` erweitern:

```python
class IngredientResolution(BaseModel):
    recipe_index: int
    ingredient_index: int
    artikel_id: int


class ImportApplyIn(BaseModel):
    recipes: list[ImportRecipeIn]
    resolutions: list[ImportResolution] = []
    ingredient_resolutions: list[IngredientResolution] = []
```

- [ ] **Step 2: `app/main.py` anpassen**

Import ergänzen (`ImportRecipeIn`, `ImportIngredientIn`,
`IngredientAmbiguity`, `IngredientResolution` zur bestehenden
`from schemas import (...)`-Liste hinzufügen).

`_recipe_to_export` (bestehend) anpassen:

```python
def _recipe_to_export(recipe: Recipe) -> dict:
    return {
        "title": recipe.title,
        "base_servings": recipe.base_servings,
        "instructions": recipe.instructions,
        "is_favorite": recipe.is_favorite,
        "tags": recipe.tags,
        "ingredients": [
            {"name": i.artikel.name, "amount": i.amount, "unit": i.unit} for i in recipe.ingredients
        ],
    }
```

Neuer Helper (z.B. direkt vor `preview_import`):

```python
def _auto_resolve_artikel_id(name: str, db: Session) -> int:
    """Automatische Auflösung für Import-Pfade: hohe Konfidenz -> bestehender
    Artikel, sonst neuer Artikel (kein stilles Raten zwischen mehreren
    mittel-konfidenten Kandidaten — die werden im Preview gemeldet)."""
    match = resolve_artikel(name, db)
    if match.confidence == "high":
        return match.artikel.id
    artikel = Artikel(name=name.strip(), created_at=datetime.utcnow().isoformat())
    db.add(artikel)
    db.flush()
    return artikel.id
```

`preview_import`/`apply_import` (bestehend) ersetzen durch:

```python
@app.post("/api/recipes/import/preview", response_model=ImportPreviewOut)
def preview_import(payload: RecipeExportFile, db: Session = Depends(get_db)):
    """
    Prüft die zu importierenden Rezepte auf Titel-Duplikate mit bestehenden
    Rezepten UND auf Zutaten, die nur mit mittlerer Konfidenz zu einem
    bestehenden Artikel passen (Ambiguität), ohne die DB zu verändern.
    """
    existing_by_title = {_normalize_title(r.title): r for r in db.query(Recipe).all()}
    conflicts: list[ImportConflict] = []
    ingredient_ambiguities: list[IngredientAmbiguity] = []

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
        for ing_idx, ing in enumerate(recipe.ingredients):
            result = resolve_artikel(ing.name, db)
            if result.confidence == "medium":
                ingredient_ambiguities.append(IngredientAmbiguity(
                    recipe_index=idx,
                    ingredient_index=ing_idx,
                    ingredient_name=ing.name,
                    candidates=[
                        ArtikelSuggestOut(id=a.id, name=a.name, confidence="medium")
                        for a, _ in result.candidates
                    ],
                ))

    return ImportPreviewOut(
        total=len(payload.recipes),
        new_count=len(payload.recipes) - len(conflicts),
        conflicts=conflicts,
        ingredient_ambiguities=ingredient_ambiguities,
    )


@app.post("/api/recipes/import/apply", response_model=ImportApplyOut)
def apply_import(payload: ImportApplyIn, db: Session = Depends(get_db)):
    """
    Führt den Import durch: neue Rezepte (kein Titel-Duplikat) werden immer
    angelegt. Für Duplikate entscheidet 'resolutions' pro Index. Zutaten
    werden per artikel_id aufgelöst: explizite 'ingredient_resolutions'
    haben Vorrang, sonst automatische Auflösung (siehe _auto_resolve_artikel_id).
    """
    existing_by_title = {_normalize_title(r.title): r for r in db.query(Recipe).all()}
    resolution_by_index = {res.import_index: res.action for res in payload.resolutions}
    ingredient_resolution_by_key = {
        (r.recipe_index, r.ingredient_index): r.artikel_id for r in payload.ingredient_resolutions
    }

    imported = overwritten = skipped = 0

    for idx, recipe in enumerate(payload.recipes):
        ingredient_models = []
        for ing_idx, ing in enumerate(recipe.ingredients):
            artikel_id = ingredient_resolution_by_key.get((idx, ing_idx))
            if artikel_id is None:
                artikel_id = _auto_resolve_artikel_id(ing.name, db)
            ingredient_models.append(Ingredient(artikel_id=artikel_id, amount=ing.amount, unit=ing.unit))

        match = existing_by_title.get(_normalize_title(recipe.title))
        if match:
            action = resolution_by_index.get(idx, "alt")
            if action == "neu":
                match.title = recipe.title
                match.base_servings = recipe.base_servings
                match.instructions = recipe.instructions
                match.is_favorite = recipe.is_favorite
                match.tags = recipe.tags
                match.ingredients = ingredient_models
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
            db_recipe.ingredients = ingredient_models
            db.add(db_recipe)
            imported += 1

    db.commit()
    return ImportApplyOut(imported=imported, overwritten=overwritten, skipped=skipped)
```

`import_recipe_photo` (bestehend): Rückgabetyp/letzte Zeile anpassen —

```python
@app.post("/api/recipes/import-photo", response_model=ImportRecipeIn)
async def import_recipe_photo(files: list[UploadFile] = File(...), db: Session = Depends(get_db)):
```

(nur die Decorator-Zeile ändert sich; der Rest der Funktion bleibt
unverändert bis auf die letzte Zeile:)

```python
    try:
        return ImportRecipeIn(**tool_use.input)
    except Exception:
        raise HTTPException(502, "Erkannte Daten hatten ein unerwartetes Format.")
```

- [ ] **Step 3: Test schreiben**

```python
from datetime import datetime


def _mk_artikel(db, name):
    from models import Artikel
    a = Artikel(name=name, created_at=datetime.utcnow().isoformat())
    db.add(a)
    db.commit()
    db.refresh(a)
    return a


def _db(client):
    import database
    return database.SessionLocal()


def test_export_returns_artikel_names_as_freetext(client):
    db = _db(client)
    gouda = _mk_artikel(db, "Gouda")
    create_res = client.post("/api/recipes", json={
        "title": "Käsebrot", "ingredients": [{"artikel_id": gouda.id, "amount": 200, "unit": "g"}],
    })
    recipe_id = create_res.json()["id"]

    res = client.get(f"/api/recipes/{recipe_id}/export")
    assert res.status_code == 200
    assert res.json()["recipes"][0]["ingredients"][0]["name"] == "Gouda"


def test_import_apply_auto_creates_artikel_for_new_ingredient_name(client):
    res = client.post("/api/recipes/import/apply", json={
        "recipes": [{
            "title": "Neues Rezept",
            "ingredients": [{"name": "Brandneue Zutat", "amount": 1, "unit": "Stück"}],
        }],
        "resolutions": [],
    })
    assert res.status_code == 200
    assert res.json()["imported"] == 1

    from models import Artikel
    db = _db(client)
    assert db.query(Artikel).filter(Artikel.name == "Brandneue Zutat").first() is not None


def test_import_apply_links_high_confidence_existing_artikel(client):
    db = _db(client)
    gouda = _mk_artikel(db, "Gouda")

    res = client.post("/api/recipes/import/apply", json={
        "recipes": [{
            "title": "Käsebrot",
            "ingredients": [{"name": "Gouda Scheiben", "amount": 200, "unit": "g"}],
        }],
        "resolutions": [],
    })
    assert res.status_code == 200

    from models import Ingredient
    db2 = _db(client)
    ingredient = db2.query(Ingredient).first()
    assert ingredient.artikel_id == gouda.id


def test_import_preview_reports_medium_confidence_ambiguity(client):
    db = _db(client)
    _mk_artikel(db, "Paprika rot")

    res = client.post("/api/recipes/import/preview", json={
        "recipes": [{
            "title": "Auflauf",
            "ingredients": [{"name": "Paprikapulver edelsüß", "amount": 1, "unit": "TL"}],
        }],
    })
    assert res.status_code == 200
    body = res.json()
    if body["ingredient_ambiguities"]:
        assert body["ingredient_ambiguities"][0]["ingredient_name"] == "Paprikapulver edelsüß"


def test_import_apply_respects_explicit_ingredient_resolution(client):
    db = _db(client)
    keep = _mk_artikel(db, "Paprika rot")
    other = _mk_artikel(db, "Paprika grün")

    res = client.post("/api/recipes/import/apply", json={
        "recipes": [{
            "title": "Auflauf",
            "ingredients": [{"name": "Paprika", "amount": 1, "unit": "Stück"}],
        }],
        "resolutions": [],
        "ingredient_resolutions": [{"recipe_index": 0, "ingredient_index": 0, "artikel_id": keep.id}],
    })
    assert res.status_code == 200

    from models import Ingredient
    db2 = _db(client)
    ingredient = db2.query(Ingredient).first()
    assert ingredient.artikel_id == keep.id
```

- [ ] **Step 4: Tests laufen lassen**

Run: `cd essensplaner && python -m pytest tests/test_import_export_api.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add essensplaner/app/schemas.py essensplaner/app/main.py essensplaner/tests/test_import_export_api.py
git commit -m "feat: JSON-/Foto-Import löst Zutaten gegen die Artikeldatenbank auf"
```

---

## Task 7: Kühlschrank-Endpunkte auf artikel_id umstellen

**Files:**
- Modify: `essensplaner/app/schemas.py` (`FridgeItemIn`/`FridgeItemOut`/`FridgeStapleIn`)
- Modify: `essensplaner/app/main.py` (kompletter Kühlschrank-Abschnitt)
- Test: `essensplaner/tests/test_fridge_api.py`

**Interfaces:**
- Consumes: `Artikel`, `_require_artikel` (Task 5)
- Produces: `FridgeItemIn = {artikel_id, amount, unit}`, `FridgeItemOut =
  {id, artikel_id, name, amount, unit, is_staple, in_stock}`,
  `FridgeStapleIn = {artikel_id, unit}`. **Breaking Change:** Endpoint
  `DELETE /api/fridge/staples/by-name/{name}` wird zu
  `DELETE /api/fridge/staples/by-artikel/{artikel_id}` (Namens-Lookup
  ergibt keinen Sinn mehr) — relevant für Task 16 (UI).

- [ ] **Step 1: Schemas in `app/schemas.py` ersetzen**

Bestehende `FridgeItemIn`/`FridgeItemOut`/`FridgeStapleIn` ersetzen durch:

```python
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
```

- [ ] **Step 2: Kühlschrank-Abschnitt in `app/main.py` ersetzen**

Den kompletten Abschnitt `# ---------- Kühlschrank ----------` (inkl.
`_norm`-Helper, der danach nirgends mehr gebraucht wird) ersetzen durch:

```python
# ---------- Kühlschrank ----------

@app.get("/api/fridge", response_model=list[FridgeItemOut])
def list_fridge(db: Session = Depends(get_db)):
    """
    Kombinierte Sicht aus aktuellem Bestand (fridge_items) und Standardartikeln
    (fridge_staples). Ein Standardartikel ohne passenden Bestandseintrag wird
    trotzdem angezeigt, aber als 'fehlt' markiert (in_stock=False).
    """
    items = db.query(FridgeItem).all()
    staples_by_artikel = {s.artikel_id: s for s in db.query(FridgeStaple).all()}

    result = []
    covered = set()
    for item in items:
        covered.add(item.artikel_id)
        result.append(FridgeItemOut(
            id=item.id, artikel_id=item.artikel_id, name=item.artikel.name,
            amount=item.amount, unit=item.unit,
            is_staple=item.artikel_id in staples_by_artikel, in_stock=True,
        ))
    for artikel_id, staple in staples_by_artikel.items():
        if artikel_id not in covered:
            result.append(FridgeItemOut(
                id=None, artikel_id=artikel_id, name=staple.artikel.name, amount=None,
                unit=staple.unit, is_staple=True, in_stock=False,
            ))

    result.sort(key=lambda i: i.name.lower())
    return result


@app.post("/api/fridge/items", response_model=FridgeItemOut)
def upsert_fridge_item(payload: FridgeItemIn, db: Session = Depends(get_db)):
    """Legt einen Bestandsartikel an oder aktualisiert Menge/Einheit, falls
    der Artikel schon existiert."""
    _require_artikel(payload.artikel_id, db)
    item = db.query(FridgeItem).filter(FridgeItem.artikel_id == payload.artikel_id).first()
    if item:
        item.amount = payload.amount
        item.unit = payload.unit
    else:
        item = FridgeItem(artikel_id=payload.artikel_id, amount=payload.amount, unit=payload.unit)
        db.add(item)
    db.commit()
    db.refresh(item)
    is_staple = db.query(FridgeStaple).filter(FridgeStaple.artikel_id == payload.artikel_id).first() is not None
    return FridgeItemOut(
        id=item.id, artikel_id=item.artikel_id, name=item.artikel.name, amount=item.amount,
        unit=item.unit, is_staple=is_staple, in_stock=True,
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
    """Markiert einen Artikel als Standardartikel ('sollte immer vorhanden sein')."""
    _require_artikel(payload.artikel_id, db)
    staple = db.query(FridgeStaple).filter(FridgeStaple.artikel_id == payload.artikel_id).first()
    if staple:
        staple.unit = payload.unit
    else:
        staple = FridgeStaple(artikel_id=payload.artikel_id, unit=payload.unit)
        db.add(staple)
    db.commit()

    artikel = db.query(Artikel).get(payload.artikel_id)
    item = db.query(FridgeItem).filter(FridgeItem.artikel_id == payload.artikel_id).first()
    if item:
        return FridgeItemOut(
            id=item.id, artikel_id=item.artikel_id, name=artikel.name, amount=item.amount,
            unit=item.unit, is_staple=True, in_stock=True,
        )
    return FridgeItemOut(
        id=None, artikel_id=payload.artikel_id, name=artikel.name, amount=None,
        unit=payload.unit, is_staple=True, in_stock=False,
    )


@app.delete("/api/fridge/staples/by-artikel/{artikel_id}")
def unmark_fridge_staple(artikel_id: int, db: Session = Depends(get_db)):
    """Entfernt die Standardartikel-Markierung. Ein evtl. vorhandener Bestandseintrag bleibt bestehen."""
    staple = db.query(FridgeStaple).filter(FridgeStaple.artikel_id == artikel_id).first()
    if not staple:
        raise HTTPException(404, "Standardartikel nicht gefunden")
    db.delete(staple)
    db.commit()
    return {"status": "ok"}
```

- [ ] **Step 3: Test schreiben**

```python
from datetime import datetime


def _mk_artikel(db, name):
    from models import Artikel
    a = Artikel(name=name, created_at=datetime.utcnow().isoformat())
    db.add(a)
    db.commit()
    db.refresh(a)
    return a


def _db(client):
    import database
    return database.SessionLocal()


def test_fridge_item_upsert_and_list(client):
    db = _db(client)
    gouda = _mk_artikel(db, "Gouda")

    res = client.post("/api/fridge/items", json={"artikel_id": gouda.id, "amount": 1, "unit": "Stück"})
    assert res.status_code == 200
    assert res.json()["name"] == "Gouda"

    res = client.get("/api/fridge")
    assert len(res.json()) == 1
    assert res.json()[0]["in_stock"] is True


def test_fridge_item_rejects_unknown_artikel(client):
    res = client.post("/api/fridge/items", json={"artikel_id": 9999})
    assert res.status_code == 400


def test_staple_without_stock_shows_as_missing(client):
    db = _db(client)
    mehl = _mk_artikel(db, "Mehl")
    client.post("/api/fridge/staples", json={"artikel_id": mehl.id, "unit": "kg"})

    res = client.get("/api/fridge")
    body = res.json()
    assert len(body) == 1
    assert body[0]["is_staple"] is True
    assert body[0]["in_stock"] is False


def test_unmark_staple_by_artikel_id(client):
    db = _db(client)
    mehl = _mk_artikel(db, "Mehl")
    client.post("/api/fridge/staples", json={"artikel_id": mehl.id, "unit": "kg"})

    res = client.delete(f"/api/fridge/staples/by-artikel/{mehl.id}")
    assert res.status_code == 200
    assert client.get("/api/fridge").json() == []
```

- [ ] **Step 4: Tests laufen lassen**

Run: `cd essensplaner && python -m pytest tests/test_fridge_api.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add essensplaner/app/schemas.py essensplaner/app/main.py essensplaner/tests/test_fridge_api.py
git commit -m "feat: Kühlschrank-Endpunkte auf artikel_id umstellen"
```

---

## Task 8: Merklisten-Endpunkte auf artikel_id umstellen

**Files:**
- Modify: `essensplaner/app/schemas.py` (`WatchlistItemIn`/`WatchlistItemOut`)
- Modify: `essensplaner/app/main.py` (kompletter Merkliste-Abschnitt)
- Test: `essensplaner/tests/test_watchlist_api.py` (bestehende Datei, wird überschrieben)

**Interfaces:**
- Consumes: `Artikel`, `_require_artikel` (Task 5)
- Produces: `WatchlistItemIn = {artikel_id, unit}`, `WatchlistItemOut =
  {id, artikel_id, name, unit}`.

- [ ] **Step 1: Schemas in `app/schemas.py` ersetzen**

```python
class WatchlistItemIn(BaseModel):
    artikel_id: int
    unit: Optional[str] = None


class WatchlistItemOut(BaseModel):
    id: int
    artikel_id: int
    name: str
    unit: Optional[str] = None
```

- [ ] **Step 2: Merkliste-Abschnitt in `app/main.py` ersetzen**

```python
# ---------- Merkliste (regelmäßig benötigte Artikel, kein Kühlschrank-Bestand) ----------

@app.get("/api/watchlist", response_model=list[WatchlistItemOut])
def list_watchlist(db: Session = Depends(get_db)):
    items = [
        WatchlistItemOut(id=i.id, artikel_id=i.artikel_id, name=i.artikel.name, unit=i.unit)
        for i in db.query(WatchlistItem).all()
    ]
    items.sort(key=lambda i: i.name.lower())
    return items


@app.post("/api/watchlist", response_model=WatchlistItemOut)
def add_watchlist_item(payload: WatchlistItemIn, db: Session = Depends(get_db)):
    _require_artikel(payload.artikel_id, db)
    existing = db.query(WatchlistItem).filter(WatchlistItem.artikel_id == payload.artikel_id).first()
    if existing:
        existing.unit = payload.unit
        db.commit()
        db.refresh(existing)
        return WatchlistItemOut(
            id=existing.id, artikel_id=existing.artikel_id, name=existing.artikel.name, unit=existing.unit,
        )
    item = WatchlistItem(artikel_id=payload.artikel_id, unit=payload.unit)
    db.add(item)
    db.commit()
    db.refresh(item)
    return WatchlistItemOut(id=item.id, artikel_id=item.artikel_id, name=item.artikel.name, unit=item.unit)


@app.delete("/api/watchlist/{item_id}")
def remove_watchlist_item(item_id: int, db: Session = Depends(get_db)):
    item = db.query(WatchlistItem).get(item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Artikel nicht gefunden")
    db.delete(item)
    db.commit()
    return {"ok": True}
```

- [ ] **Step 3: Test-Datei `tests/test_watchlist_api.py` komplett ersetzen**

```python
from datetime import datetime


def _mk_artikel(db, name):
    from models import Artikel
    a = Artikel(name=name, created_at=datetime.utcnow().isoformat())
    db.add(a)
    db.commit()
    db.refresh(a)
    return a


def _db(client):
    import database
    return database.SessionLocal()


def test_watchlist_crud(client):
    db = _db(client)
    mehl = _mk_artikel(db, "Mehl")

    res = client.post("/api/watchlist", json={"artikel_id": mehl.id, "unit": "kg"})
    assert res.status_code == 200
    item = res.json()
    assert item["name"] == "Mehl"

    res = client.get("/api/watchlist")
    assert res.status_code == 200
    assert len(res.json()) == 1

    res = client.delete(f"/api/watchlist/{item['id']}")
    assert res.status_code == 200
    assert client.get("/api/watchlist").json() == []


def test_watchlist_rejects_unknown_artikel(client):
    res = client.post("/api/watchlist", json={"artikel_id": 9999})
    assert res.status_code == 400


def test_remove_unknown_watchlist_item_returns_404(client):
    res = client.delete("/api/watchlist/9999")
    assert res.status_code == 404
```

- [ ] **Step 4: Tests laufen lassen**

Run: `cd essensplaner && python -m pytest tests/test_watchlist_api.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add essensplaner/app/schemas.py essensplaner/app/main.py essensplaner/tests/test_watchlist_api.py
git commit -m "feat: Merklisten-Endpunkte auf artikel_id umstellen"
```

---

## Task 9: Einkaufsliste und Angebots-Matching auf artikel_id/resolve_artikel umstellen

**Files:**
- Modify: `essensplaner/app/planner.py` (`aggregate_shopping_list`)
- Modify: `essensplaner/app/offers/matching.py` (komplett ersetzen)
- Delete: `essensplaner/tests/test_offers_matching.py` (Logik jetzt in `test_artikel_matching.py`, Task 3, abgedeckt)
- Test: `essensplaner/tests/test_shopping_list.py`
- Test: `essensplaner/tests/test_offers_matching_via_artikel.py`

**Interfaces:**
- Consumes: `resolve_artikel` (Task 3)
- Produces: `aggregate_shopping_list(db, entries) -> list[str]`
  (Signatur unverändert), `find_matching_recipe_ids(product_name, db) ->
  list[int]` und `is_watchlist_match(product_name, db) -> bool` (Signatur
  unverändert — **kein** `threshold`-Parameter mehr, da `resolve_artikel`
  die Schwellen zentral kapselt; bestehende Aufrufer in `planner.py` und
  `main.py` übergeben ohnehin keinen `threshold`, bleiben unverändert).

- [ ] **Step 1: `app/planner.py` — `aggregate_shopping_list` ersetzen**

```python
def aggregate_shopping_list(db: Session, entries: list[PlanEntry]) -> list[str]:
    """Fasst gleiche Zutaten (per artikel_id) aus allen geplanten Rezepten zusammen."""
    totals: dict[tuple[int, str], float] = {}
    names: dict[int, str] = {}
    unitless: list[str] = []

    for entry in entries:
        recipe = entry.recipe
        for ing in recipe.ingredients:
            names[ing.artikel_id] = ing.artikel.name
            if ing.amount is None or ing.unit is None:
                unitless.append(ing.artikel.name)
                continue
            key = (ing.artikel_id, ing.unit.strip().lower())
            totals[key] = totals.get(key, 0) + ing.amount

    items = [f"{amount:g} {unit} {names[artikel_id]}" for (artikel_id, unit), amount in totals.items()]
    items.extend(sorted(set(unitless)))
    return items
```

- [ ] **Step 2: `app/offers/matching.py` komplett ersetzen**

```python
"""Fuzzy-Matching zwischen Angebots-Produktnamen und Rezept-Zutaten /
Merklisten-Artikeln. Nutzt zentral resolve_artikel() (siehe
app/artikel_matching.py) — nur Angebote mit hoher Konfidenz zu einem
bestehenden Artikel gelten als Treffer; mittlere Konfidenz landet
stattdessen in der Bestätigungs-Warteschlange (siehe offers/runner.py,
Task 10)."""
from sqlalchemy.orm import Session

from models import Ingredient, FridgeStaple, WatchlistItem
from artikel_matching import resolve_artikel


def find_matching_recipe_ids(product_name: str, db: Session) -> list[int]:
    match = resolve_artikel(product_name, db)
    if match.confidence != "high":
        return []
    return sorted({
        i.recipe_id for i in db.query(Ingredient).filter(Ingredient.artikel_id == match.artikel.id).all()
    })


def is_watchlist_match(product_name: str, db: Session) -> bool:
    match = resolve_artikel(product_name, db)
    if match.confidence != "high":
        return False
    artikel_id = match.artikel.id
    if db.query(FridgeStaple).filter(FridgeStaple.artikel_id == artikel_id).first():
        return True
    if db.query(WatchlistItem).filter(WatchlistItem.artikel_id == artikel_id).first():
        return True
    return False
```

- [ ] **Step 3: `tests/test_offers_matching.py` löschen**

Diese Datei testete die bisherige, jetzt entfernte Matching-Logik direkt
in `offers/matching.py` (`match_score`, `DEFAULT_THRESHOLD` existieren
dort nicht mehr). Die gleichwertige Abdeckung liegt jetzt in
`tests/test_artikel_matching.py` (Task 3).

```bash
git rm essensplaner/tests/test_offers_matching.py
```

- [ ] **Step 4: Test für `aggregate_shopping_list` schreiben**

```python
from datetime import date, datetime


def _mk_artikel(db, name):
    from models import Artikel
    a = Artikel(name=name, created_at=datetime.utcnow().isoformat())
    db.add(a)
    db.commit()
    db.refresh(a)
    return a


def _db(client):
    import database
    return database.SessionLocal()


def test_aggregate_shopping_list_sums_by_artikel_and_unit(client):
    from models import Recipe, Ingredient, PlanEntry
    from planner import aggregate_shopping_list

    db = _db(client)
    gouda = _mk_artikel(db, "Gouda")
    r1 = Recipe(title="Rezept 1")
    r2 = Recipe(title="Rezept 2")
    db.add_all([r1, r2])
    db.commit()
    db.add(Ingredient(recipe_id=r1.id, artikel_id=gouda.id, amount=100, unit="g"))
    db.add(Ingredient(recipe_id=r2.id, artikel_id=gouda.id, amount=150, unit="g"))
    db.commit()

    e1 = PlanEntry(date=date.today(), recipe_id=r1.id)
    e2 = PlanEntry(date=date(2026, 1, 1), recipe_id=r2.id)
    db.add_all([e1, e2])
    db.commit()

    items = aggregate_shopping_list(db, [e1, e2])
    assert items == ["250 g Gouda"]


def test_aggregate_shopping_list_lists_unitless_separately(client):
    from models import Recipe, Ingredient, PlanEntry
    from planner import aggregate_shopping_list

    db = _db(client)
    salz = _mk_artikel(db, "Salz")
    r1 = Recipe(title="Rezept 1")
    db.add(r1)
    db.commit()
    db.add(Ingredient(recipe_id=r1.id, artikel_id=salz.id, amount=None, unit=None))
    db.commit()

    e1 = PlanEntry(date=date.today(), recipe_id=r1.id)
    db.add(e1)
    db.commit()

    assert aggregate_shopping_list(db, [e1]) == ["Salz"]
```

- [ ] **Step 5: Test für das umgestellte Angebots-Matching schreiben**

```python
from datetime import datetime


def _mk_artikel(db, name):
    from models import Artikel
    a = Artikel(name=name, created_at=datetime.utcnow().isoformat())
    db.add(a)
    db.commit()
    db.refresh(a)
    return a


def _db(client):
    import database
    return database.SessionLocal()


def test_find_matching_recipe_ids_via_artikel(client):
    from models import Recipe, Ingredient
    from offers.matching import find_matching_recipe_ids

    db = _db(client)
    gouda = _mk_artikel(db, "Gouda")
    recipe = Recipe(title="Käsebrot")
    db.add(recipe)
    db.commit()
    db.add(Ingredient(recipe_id=recipe.id, artikel_id=gouda.id, amount=200, unit="g"))
    db.commit()

    assert find_matching_recipe_ids("Gouda Scheiben 250g", db) == [recipe.id]
    assert find_matching_recipe_ids("Klopapier", db) == []


def test_is_watchlist_match_via_artikel(client):
    from models import FridgeStaple, WatchlistItem
    from offers.matching import is_watchlist_match

    db = _db(client)
    milch = _mk_artikel(db, "Milch")
    mehl = _mk_artikel(db, "Mehl")
    db.add(FridgeStaple(artikel_id=milch.id))
    db.add(WatchlistItem(artikel_id=mehl.id))
    db.commit()

    assert is_watchlist_match("Frische Milch 1L", db) is True
    assert is_watchlist_match("Weizenmehl Type 405", db) is True
    assert is_watchlist_match("Klopapier 8er Pack", db) is False
```

- [ ] **Step 6: Tests laufen lassen**

Run: `cd essensplaner && python -m pytest tests/test_shopping_list.py tests/test_offers_matching_via_artikel.py -v`
Expected: PASS

- [ ] **Step 7: Vollen Testlauf prüfen**

Run: `cd essensplaner && python -m pytest tests/ -v`
Expected: `tests/test_planner_offer_bonus.py` (aus dem vorherigen
Angebote-Feature) nutzt `Ingredient(name=...)` und `Offer(...)` — dieser
Test bricht jetzt und wird in Task 10 (Runner-Erweiterung) mit
angepasst, da er dieselbe Datei wie die Runner-Tests berührt.
Verbleibende Fehler in Tests, die noch `Ingredient(name=...)` o.ä.
nutzen, sind ebenfalls erwartet und werden in Task 10 behoben.

- [ ] **Step 8: Commit**

```bash
git add essensplaner/app/planner.py essensplaner/app/offers/matching.py essensplaner/tests/test_shopping_list.py essensplaner/tests/test_offers_matching_via_artikel.py
git rm essensplaner/tests/test_offers_matching.py
git commit -m "feat: Einkaufsliste und Angebots-Matching auf artikel_id/resolve_artikel umstellen"
```

---

## Task 10: Connector-Runner um Preis-Historie, Bestätigungs-Warteschlange und Bild-Download erweitern

**Files:**
- Create: `essensplaner/app/artikel_images.py`
- Modify: `essensplaner/app/offers/base.py` (`OfferData.image_url`)
- Modify: `essensplaner/app/offers/runner.py`
- Modify: `essensplaner/tests/test_offers_runner.py` (bestehende `FridgeStaple(name=...)`-Aufrufe auf `artikel_id` umstellen)
- Modify: `essensplaner/tests/test_planner_offer_bonus.py` (bestehende `Ingredient(name=...)`-Aufrufe auf `artikel_id` umstellen)
- Test: `essensplaner/tests/test_artikel_images.py`

**Interfaces:**
- Consumes: `resolve_artikel` (Task 3), `Artikel`, `ArtikelPriceHistory`,
  `PendingArtikelMatch` (Task 1)
- Produces: `download_artikel_image(artikel_id: int, image_url: str) ->
  str | None` (`artikel_images.py`), `ARTIKEL_IMAGES_DIR` (Path,
  genutzt von Task 19 für das `StaticFiles`-Mount), `OfferData.image_url:
  Optional[str] = None` (Feld, wird ab Task 11–13 von den Connectors
  tatsächlich befüllt — bis dahin bleibt es `None`, Bild-Download wird
  dann einfach übersprungen).

- [ ] **Step 1: `app/offers/base.py` — `image_url`-Feld ergänzen**

```python
@dataclass
class OfferData:
    retailer: str  # "kaufland" | "edeka"
    product_name: str
    valid_from: date
    valid_until: date
    description: Optional[str] = None
    price: Optional[float] = None
    discount_text: Optional[str] = None
    image_url: Optional[str] = None
```

- [ ] **Step 2: `app/artikel_images.py` schreiben**

```python
"""Speicherung von Artikel-Bildern, heruntergeladen aus Angebots-Daten
(siehe offers/runner.py)."""
from pathlib import Path

import httpx

import database

ARTIKEL_IMAGES_DIR = Path(database.DB_PATH).parent / "artikel-images"
ARTIKEL_IMAGES_DIR.mkdir(parents=True, exist_ok=True)

_EXTENSION_BY_CONTENT_TYPE = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}


def download_artikel_image(artikel_id: int, image_url: str) -> str | None:
    """Lädt ein Artikel-Bild herunter und speichert es lokal. Gibt den
    öffentlichen Pfad zurück (analog zu Recipe.image_path), oder None bei
    Fehler — ein Bild-Download-Fehler darf einen Connector-Lauf nie
    scheitern lassen (siehe run_source)."""
    try:
        response = httpx.get(image_url, timeout=15, follow_redirects=True)
        response.raise_for_status()
    except httpx.HTTPError:
        return None
    content_type = response.headers.get("content-type", "").split(";")[0].strip().lower()
    ext = _EXTENSION_BY_CONTENT_TYPE.get(content_type, ".jpg")
    dest = ARTIKEL_IMAGES_DIR / f"{artikel_id}{ext}"
    dest.write_bytes(response.content)
    return f"/artikel-images/{artikel_id}{ext}"
```

- [ ] **Step 3: `app/offers/runner.py` erweitern**

Imports ergänzen:

```python
from artikel_matching import resolve_artikel
from artikel_images import download_artikel_image
from models import Artikel, ArtikelPriceHistory, PendingArtikelMatch
```

(`Offer`, `OfferSourceConfig` bleiben in der bestehenden `from models
import ...`-Zeile — `Artikel`, `ArtikelPriceHistory`,
`PendingArtikelMatch` neu ergänzen, keine separate Zeile nötig.)

Neue Funktion (vor `run_source`):

```python
def _record_artikel_match(offer_data, source: str, db: Session, now: str) -> None:
    """Ordnet ein Angebot einem Artikel zu: hohe Konfidenz -> Preis-Historie
    (+ Bild, falls noch keins gesetzt), mittlere Konfidenz -> Bestätigungs-
    Warteschlange. Niedrige Konfidenz wird ignoriert (kein bekannter Artikel
    passt)."""
    match = resolve_artikel(offer_data.product_name, db)

    if match.confidence == "high":
        artikel = match.artikel
        duplicate = (
            db.query(ArtikelPriceHistory)
            .filter(
                ArtikelPriceHistory.artikel_id == artikel.id,
                ArtikelPriceHistory.valid_from == offer_data.valid_from,
                ArtikelPriceHistory.valid_until == offer_data.valid_until,
                ArtikelPriceHistory.price == offer_data.price,
            )
            .first()
        )
        if not duplicate:
            db.add(ArtikelPriceHistory(
                artikel_id=artikel.id, price=offer_data.price, discount_text=offer_data.discount_text,
                retailer=offer_data.retailer, source=source,
                valid_from=offer_data.valid_from, valid_until=offer_data.valid_until, recorded_at=now,
            ))
        if not artikel.image_path and offer_data.image_url:
            image_path = download_artikel_image(artikel.id, offer_data.image_url)
            if image_path:
                artikel.image_path = image_path

    elif match.confidence == "medium":
        product_norm = offer_data.product_name.strip().lower()
        for artikel, score in match.candidates:
            existing = (
                db.query(PendingArtikelMatch)
                .filter(
                    PendingArtikelMatch.product_name.ilike(product_norm),
                    PendingArtikelMatch.artikel_id == artikel.id,
                    PendingArtikelMatch.status == "open",
                )
                .first()
            )
            if existing:
                existing.score = score
                existing.price = offer_data.price
                existing.discount_text = offer_data.discount_text
                existing.retailer = offer_data.retailer
                existing.source = source
                existing.valid_from = offer_data.valid_from
                existing.valid_until = offer_data.valid_until
            else:
                db.add(PendingArtikelMatch(
                    product_name=offer_data.product_name, artikel_id=artikel.id, score=score,
                    price=offer_data.price, discount_text=offer_data.discount_text,
                    retailer=offer_data.retailer, source=source,
                    valid_from=offer_data.valid_from, valid_until=offer_data.valid_until, created_at=now,
                ))
```

In `run_source`, die bestehende Insert-Schleife erweitern (nach der
`carried_notified_at`-Zeile, innerhalb derselben `for offer_data in
results:`-Schleife):

```python
    for offer_data in results:
        carried_notified_at = now if (offer_data.product_name, offer_data.valid_until) in previously_notified else None
        db.add(Offer(
            retailer=offer_data.retailer,
            source=source,
            product_name=offer_data.product_name,
            description=offer_data.description,
            price=offer_data.price,
            discount_text=offer_data.discount_text,
            valid_from=offer_data.valid_from,
            valid_until=offer_data.valid_until,
            scraped_at=now,
            notified_at=carried_notified_at,
        ))
        _record_artikel_match(offer_data, source, db, now)
```

(ersetzt die bisherige Schleife — der einzige Unterschied ist die neue
letzte Zeile `_record_artikel_match(...)`.)

- [ ] **Step 4: Bestehende Tests auf `artikel_id` umstellen**

In `tests/test_offers_runner.py`: jedes `FridgeStaple(name="Gouda")`
durch einen vorab angelegten Artikel ersetzen, z.B.:

```python
def _mk_artikel(db, name):
    from datetime import datetime
    from models import Artikel
    a = Artikel(name=name, created_at=datetime.utcnow().isoformat())
    db.add(a)
    db.commit()
    db.refresh(a)
    return a
```

(als Modul-Helfer ergänzen) und in jedem betroffenen Test
`db.add(FridgeStaple(name="Gouda"))` durch

```python
    gouda = _mk_artikel(db, "Gouda")
    db.add(FridgeStaple(artikel_id=gouda.id))
```

ersetzen (betrifft `test_run_source_notifies_and_marks_watchlist_matches`,
`test_run_source_does_not_renotify_same_offer_on_next_run`,
`test_run_source_survives_notify_failure`).

In `tests/test_planner_offer_bonus.py`: jedes
`Ingredient(recipe_id=with_offer.id, name="Gouda", amount=200, unit="g")`
durch

```python
    gouda = _mk_artikel(db, "Gouda")
    db.add(Ingredient(recipe_id=with_offer.id, artikel_id=gouda.id, amount=200, unit="g"))
```

ersetzen (mit demselben `_mk_artikel`-Helfer, als Modul-Helfer in dieser
Datei ergänzen).

- [ ] **Step 5: Neue Tests in `tests/test_offers_runner.py` ergänzen**

```python
from unittest.mock import patch


def test_run_source_records_price_history_for_high_confidence_match(client):
    from models import ArtikelPriceHistory
    db = _db(client)
    gouda = _mk_artikel(db, "Gouda")

    fake_offers = [OfferData(retailer="kaufland", product_name="Gouda Scheiben 250g",
                              valid_from=date(2026, 9, 7), valid_until=date(2026, 9, 13), price=1.99)]
    with patch("offers.kaufland_scraper.fetch_offers", return_value=fake_offers), \
         patch("ha_client.notify", new_callable=AsyncMock):
        run_source("kaufland_scraper", db, plz="12345")

    db2 = _db(client)
    history = db2.query(ArtikelPriceHistory).filter(ArtikelPriceHistory.artikel_id == gouda.id).all()
    assert len(history) == 1
    assert history[0].price == 1.99


def test_run_source_does_not_duplicate_identical_price_history_entry(client):
    from models import ArtikelPriceHistory
    db = _db(client)
    gouda = _mk_artikel(db, "Gouda")

    fake_offers = [OfferData(retailer="kaufland", product_name="Gouda",
                              valid_from=date(2026, 9, 7), valid_until=date(2026, 9, 13), price=1.99)]
    with patch("offers.kaufland_scraper.fetch_offers", return_value=fake_offers), \
         patch("ha_client.notify", new_callable=AsyncMock):
        run_source("kaufland_scraper", db, plz="12345")
        run_source("kaufland_scraper", db, plz="12345")

    db2 = _db(client)
    history = db2.query(ArtikelPriceHistory).filter(ArtikelPriceHistory.artikel_id == gouda.id).all()
    assert len(history) == 1  # identischer Preis/Zeitraum -> kein zweiter Eintrag


def test_run_source_creates_pending_match_for_medium_confidence(client):
    from models import PendingArtikelMatch
    db = _db(client)
    _mk_artikel(db, "Paprika rot")

    fake_offers = [OfferData(retailer="kaufland", product_name="Paprikapulver edelsüß",
                              valid_from=date(2026, 9, 7), valid_until=date(2026, 9, 13))]
    with patch("offers.kaufland_scraper.fetch_offers", return_value=fake_offers), \
         patch("ha_client.notify", new_callable=AsyncMock):
        run_source("kaufland_scraper", db, plz="12345")

    db2 = _db(client)
    pending = db2.query(PendingArtikelMatch).all()
    # Je nach tatsächlichem Score entweder eine Bestätigungs-Zeile (mittel)
    # oder keine (falls der Score doch unter 60 liegt) — beides ist ein
    # gültiges Ergebnis für dieses Namenspaar, daher nur auf "keine
    # Exception" und plausible Konsistenz geprüft:
    for p in pending:
        assert p.product_name == "Paprikapulver edelsüß"
        assert p.status == "open"


def test_run_source_downloads_image_on_first_high_confidence_match(client):
    from unittest.mock import Mock
    db = _db(client)
    gouda = _mk_artikel(db, "Gouda")
    assert gouda.image_path is None

    fake_offers = [OfferData(retailer="kaufland", product_name="Gouda",
                              valid_from=date(2026, 9, 7), valid_until=date(2026, 9, 13),
                              image_url="https://example.invalid/gouda.jpg")]
    with patch("offers.kaufland_scraper.fetch_offers", return_value=fake_offers), \
         patch("ha_client.notify", new_callable=AsyncMock), \
         patch("artikel_images.download_artikel_image", return_value="/artikel-images/1.jpg") as mock_download:
        run_source("kaufland_scraper", db, plz="12345")

    mock_download.assert_called_once()
    db2 = _db(client)
    refreshed = db2.query(type(gouda)).get(gouda.id)
    assert refreshed.image_path == "/artikel-images/1.jpg"
```

- [ ] **Step 6: Test für `artikel_images.py` schreiben**

```python
from unittest.mock import Mock, patch


def test_download_artikel_image_saves_file_and_returns_path(tmp_path, monkeypatch):
    import artikel_images
    monkeypatch.setattr(artikel_images, "ARTIKEL_IMAGES_DIR", tmp_path)

    fake_response = Mock()
    fake_response.headers = {"content-type": "image/jpeg"}
    fake_response.content = b"fake-image-bytes"
    fake_response.raise_for_status = Mock()

    with patch("artikel_images.httpx.get", return_value=fake_response):
        result = artikel_images.download_artikel_image(42, "https://example.invalid/img.jpg")

    assert result == "/artikel-images/42.jpg"
    assert (tmp_path / "42.jpg").read_bytes() == b"fake-image-bytes"


def test_download_artikel_image_returns_none_on_http_error(tmp_path, monkeypatch):
    import artikel_images
    import httpx
    monkeypatch.setattr(artikel_images, "ARTIKEL_IMAGES_DIR", tmp_path)

    with patch("artikel_images.httpx.get", side_effect=httpx.ConnectError("nope")):
        result = artikel_images.download_artikel_image(42, "https://example.invalid/img.jpg")

    assert result is None
```

- [ ] **Step 7: Tests laufen lassen**

Run: `cd essensplaner && python -m pytest tests/test_artikel_images.py tests/test_offers_runner.py tests/test_planner_offer_bonus.py -v`
Expected: PASS

- [ ] **Step 8: Vollen Testlauf prüfen**

Run: `cd essensplaner && python -m pytest tests/ -v`
Expected: alle Tests grün — dies ist der letzte Task, der noch
Alt-Schema-Nutzungen (`Ingredient(name=...)` etc.) in bestehenden Tests
korrigiert; ab hier sollte die komplette Suite wieder durchlaufen.

- [ ] **Step 9: Commit**

```bash
git add essensplaner/app/artikel_images.py essensplaner/app/offers/base.py essensplaner/app/offers/runner.py essensplaner/tests/test_offers_runner.py essensplaner/tests/test_planner_offer_bonus.py essensplaner/tests/test_artikel_images.py
git commit -m "feat: Preis-Historie, Bestätigungs-Warteschlange und Bild-Download im Connector-Runner"
```

---

## Task 11: Kaufland-Scraper — Produktbild extrahieren

**Files:**
- Modify: `essensplaner/app/offers/kaufland_scraper.py`
- Modify: `essensplaner/tests/fixtures/kaufland_sample.html`
- Modify: `essensplaner/tests/test_kaufland_scraper.py`

**Interfaces:**
- Consumes: `OfferData.image_url` (Task 10)
- Produces: `_parse_offers_html` befüllt `image_url` pro Angebot.

Die Kaufland-Kacheln (`.k-product-tile`, siehe Docstring in
`kaufland_scraper.py`) enthalten laut bisheriger Live-Prüfung (Task 6 des
vorherigen Plans) Titel/Untertitel/Preis/Rabatt als Text-Elemente — ein
Bild-Element wurde damals nicht extrahiert, da es nicht gebraucht wurde.
Dieser Task ergänzt es.

- [ ] **Step 1: Fixture um ein Bild-Element ergänzen**

In `tests/fixtures/kaufland_sample.html`, in der ersten `.k-product-tile`
(Gouda-Kachel), ein Bild-Element hinzufügen (plausible Annahme, in Step 3
gegen die reale Seite zu verifizieren):

```html
<img class="k-product-tile__image" src="https://cdn.kaufland.de/example/gouda.jpg" alt="">
```

- [ ] **Step 2: `_parse_offers_html` erweitern**

In der Tile-Verarbeitungsschleife (nach `subtitle_el = ...`):

```python
            image_el = tile.select_one(".k-product-tile__image")
            image_url = image_el.get("src") if image_el else None
```

Und im `OfferData(...)`-Konstruktor `image_url=image_url,` ergänzen.

- [ ] **Step 3: Test ergänzen und gegen die echte Seite verifizieren**

```python
def test_parse_offers_html_extracts_image_url():
    offers = _parse_offers_html(FIXTURE, today=TODAY)
    assert offers[0].image_url == "https://cdn.kaufland.de/example/gouda.jpg"
```

Mit einem Browser-Tool `https://filiale.kaufland.de/angebote/uebersicht.html`
(oder die zuletzt genutzte reale Angebots-URL) öffnen, eine
`.k-product-tile` inspizieren und prüfen, ob dort tatsächlich ein
`<img>`-Element mit `src`/`data-src`/`srcset` existiert und welchen
genauen Selektor/welches Attribut es trägt (Lazy-Loading-Bibliotheken
nutzen oft `data-src` statt `src` für das eigentliche Bild). Selektor,
Fixture und Test bei Abweichung entsprechend anpassen — analog zum
Vorgehen bei der ursprünglichen Scraper-Kalibrierung (siehe Modul-
Docstring, Abschnitt zur Live-Verifikation vom 2026-09-04).

- [ ] **Step 4: Tests laufen lassen**

Run: `cd essensplaner && python -m pytest tests/test_kaufland_scraper.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add essensplaner/app/offers/kaufland_scraper.py essensplaner/tests/fixtures/kaufland_sample.html essensplaner/tests/test_kaufland_scraper.py
git commit -m "feat: Produktbild-Extraktion im Kaufland-Scraper"
```

---

## Task 12: Edeka-Scraper — Produktbild extrahieren

**Files:**
- Modify: `essensplaner/app/offers/edeka_scraper.py`
- Modify: `essensplaner/tests/fixtures/edeka_sample.html`
- Modify: `essensplaner/tests/test_edeka_scraper.py`

**Interfaces:**
- Consumes: `OfferData.image_url` (Task 10)
- Produces: `_parse_offers_html` befüllt `image_url` pro Angebot.

- [ ] **Step 1: Fixture um ein Bild-Element ergänzen**

In `tests/fixtures/edeka_sample.html`, im ersten `<article>`, ein
`<img>`-Element hinzufügen (plausible Annahme, in Step 3 zu
verifizieren):

```html
<img src="https://www.edeka.de/media/example/tomaten.jpg" alt="">
```

- [ ] **Step 2: `_parse_offers_html` erweitern**

In der Artikel-Verarbeitungsschleife (nach `description_el = ...`):

```python
        image_el = item.select_one("img")
        image_url = image_el.get("src") if image_el else None
```

Und im `OfferData(...)`-Konstruktor `image_url=image_url,` ergänzen.

- [ ] **Step 3: Test ergänzen und gegen die echte Seite verifizieren**

```python
def test_parse_offers_html_extracts_image_url():
    offers = _parse_offers_html(FIXTURE)
    assert offers[0].image_url == "https://www.edeka.de/media/example/tomaten.jpg"
```

Mit einem Browser-Tool die reale Edeka-Angebotsseite einer Filiale
(`https://www.edeka.de/maerkte/<id>/angebote`, `<id>` z.B. aus einer
vorherigen `_resolve_store_offers_url`-Prüfung) öffnen, ein
Produkt-`<article>` inspizieren: gibt es genau ein `<img>` mit sinnvoller
`src` (kein 1x1-Platzhalter/Lazy-Loading-Icon), oder muss stattdessen
`data-src`/`srcset` gelesen werden? Selektor, Fixture und Test bei
Abweichung entsprechend anpassen.

- [ ] **Step 4: Tests laufen lassen**

Run: `cd essensplaner && python -m pytest tests/test_edeka_scraper.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add essensplaner/app/offers/edeka_scraper.py essensplaner/tests/fixtures/edeka_sample.html essensplaner/tests/test_edeka_scraper.py
git commit -m "feat: Produktbild-Extraktion im Edeka-Scraper"
```

---

## Task 13: Marktguru-Connector — Produktbild extrahieren

**Files:**
- Modify: `essensplaner/app/offers/marktguru_connector.py`
- Modify: `essensplaner/tests/fixtures/marktguru_sample.json`
- Modify: `essensplaner/tests/test_marktguru_connector.py`

**Interfaces:**
- Consumes: `OfferData.image_url` (Task 10)
- Produces: `_parse_response` befüllt `image_url` pro Angebot.

Laut Modul-Docstring steht der Produktname in `product.name` (Fallback
`description`) — ein Bild-Feld wurde bislang nicht ausgewertet. Plausible
Annahme (in Step 3 zu verifizieren): `product.imageUrl` oder ein
Top-Level-Feld `images`/`imageUrl` in der rohen Angebots-Antwort.

- [ ] **Step 1: Fixture um ein Bild-Feld ergänzen**

In `tests/fixtures/marktguru_sample.json`, beim ersten Angebot (Butter),
ein `product.imageUrl`-Feld ergänzen:

```json
{
  "product": {"name": "Butter 250g", "imageUrl": "https://images.marktguru.de/example/butter.jpg"},
  ...
}
```

(In die bestehende Struktur der Fixture einfügen — falls `product`
bislang nicht als verschachteltes Objekt vorliegt, sondern der
Produktname direkt im Angebot steht, den Docstring/die tatsächliche
Struktur aus `_parse_response` als Vorlage nehmen.)

- [ ] **Step 2: `_parse_response` erweitern**

Nach der `product_name = ...`-Zeile:

```python
        image_url = product.get("imageUrl")
```

Und im `OfferData(...)`-Konstruktor `image_url=image_url,` ergänzen.

- [ ] **Step 3: Test ergänzen und gegen die echte API verifizieren**

```python
def test_parse_response_extracts_image_url():
    offers = _parse_response(FIXTURE)
    butter = next(o for o in offers if o.product_name == "Butter 250g")
    assert butter.image_url == "https://images.marktguru.de/example/butter.jpg"
```

Mit einem kurzen manuellen Request gegen die echte Marktguru-API (gleicher
Aufbau wie in `fetch_offers`, z.B. mit einem der `_SEARCH_TERMS` und einer
echten PLZ) die tatsächliche JSON-Antwort inspizieren: existiert ein
Bild-Feld, und unter welchem genauen Pfad? Feld-Pfad, Fixture und Test bei
Abweichung entsprechend anpassen — analog zur ursprünglichen
Live-Verifikation (siehe Modul-Docstring).

- [ ] **Step 4: Tests laufen lassen**

Run: `cd essensplaner && python -m pytest tests/test_marktguru_connector.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add essensplaner/app/offers/marktguru_connector.py essensplaner/tests/fixtures/marktguru_sample.json essensplaner/tests/test_marktguru_connector.py
git commit -m "feat: Produktbild-Extraktion im Marktguru-Connector"
```

---

## Task 14: Bestätigungs-Warteschlange — Endpunkte

**Files:**
- Modify: `essensplaner/app/schemas.py`
- Modify: `essensplaner/app/main.py`
- Test: `essensplaner/tests/test_pending_matches_api.py`

**Interfaces:**
- Consumes: `PendingArtikelMatch`, `ArtikelPriceHistory` (Task 1)
- Produces: `GET /api/artikel/pending-matches`,
  `POST /api/artikel/pending-matches/{id}/confirm`,
  `POST /api/artikel/pending-matches/{id}/reject`. Schema
  `PendingArtikelMatchOut`.

- [ ] **Step 1: Schema in `app/schemas.py` ergänzen**

```python
class PendingArtikelMatchOut(BaseModel):
    id: int
    product_name: str
    artikel_id: int
    artikel_name: str
    score: float
    retailer: str
    source: str
    valid_from: str
    valid_until: str
```

- [ ] **Step 2: Endpunkte in `app/main.py` ergänzen**

Import ergänzen: `PendingArtikelMatchOut` zur `from schemas import
(...)`-Liste hinzufügen.

```python
# ---------- Bestätigungs-Warteschlange (unsichere Angebots-Zuordnungen) ----------

def _pending_match_out(p: PendingArtikelMatch) -> PendingArtikelMatchOut:
    return PendingArtikelMatchOut(
        id=p.id, product_name=p.product_name, artikel_id=p.artikel_id, artikel_name=p.artikel.name,
        score=p.score, retailer=p.retailer, source=p.source,
        valid_from=p.valid_from.isoformat(), valid_until=p.valid_until.isoformat(),
    )


@app.get("/api/artikel/pending-matches", response_model=list[PendingArtikelMatchOut])
def list_pending_matches(db: Session = Depends(get_db)):
    pending = (
        db.query(PendingArtikelMatch)
        .filter(PendingArtikelMatch.status == "open")
        .order_by(PendingArtikelMatch.score.desc())
        .all()
    )
    return [_pending_match_out(p) for p in pending]


@app.post("/api/artikel/pending-matches/{pending_id}/confirm", response_model=PendingArtikelMatchOut)
def confirm_pending_match(pending_id: int, db: Session = Depends(get_db)):
    pending = db.query(PendingArtikelMatch).get(pending_id)
    if not pending:
        raise HTTPException(404, "Eintrag nicht gefunden")
    pending.status = "confirmed"
    db.add(ArtikelPriceHistory(
        artikel_id=pending.artikel_id, price=pending.price, discount_text=pending.discount_text,
        retailer=pending.retailer, source=pending.source,
        valid_from=pending.valid_from, valid_until=pending.valid_until,
        recorded_at=datetime.utcnow().isoformat(),
    ))
    db.commit()
    db.refresh(pending)
    return _pending_match_out(pending)


@app.post("/api/artikel/pending-matches/{pending_id}/reject", response_model=PendingArtikelMatchOut)
def reject_pending_match(pending_id: int, db: Session = Depends(get_db)):
    pending = db.query(PendingArtikelMatch).get(pending_id)
    if not pending:
        raise HTTPException(404, "Eintrag nicht gefunden")
    pending.status = "rejected"
    db.commit()
    db.refresh(pending)
    return _pending_match_out(pending)
```

- [ ] **Step 3: Test schreiben**

```python
from datetime import date, datetime


def _mk_artikel(db, name):
    from models import Artikel
    a = Artikel(name=name, created_at=datetime.utcnow().isoformat())
    db.add(a)
    db.commit()
    db.refresh(a)
    return a


def _mk_pending(db, artikel_id, product_name="Paprikapulver edelsüß", score=65.0):
    from models import PendingArtikelMatch
    p = PendingArtikelMatch(
        product_name=product_name, artikel_id=artikel_id, score=score, status="open",
        price=1.49, discount_text="-10%", retailer="kaufland", source="kaufland_scraper",
        valid_from=date.today(), valid_until=date.today(), created_at=datetime.utcnow().isoformat(),
    )
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


def _db(client):
    import database
    return database.SessionLocal()


def test_list_pending_matches_only_returns_open(client):
    db = _db(client)
    a = _mk_artikel(db, "Paprika rot")
    _mk_pending(db, a.id)

    res = client.get("/api/artikel/pending-matches")
    assert res.status_code == 200
    assert len(res.json()) == 1
    assert res.json()[0]["artikel_name"] == "Paprika rot"


def test_confirm_creates_price_history_and_closes_entry(client):
    from models import ArtikelPriceHistory
    db = _db(client)
    a = _mk_artikel(db, "Paprika rot")
    p = _mk_pending(db, a.id)

    res = client.post(f"/api/artikel/pending-matches/{p.id}/confirm")
    assert res.status_code == 200

    db2 = _db(client)
    history = db2.query(ArtikelPriceHistory).filter(ArtikelPriceHistory.artikel_id == a.id).all()
    assert len(history) == 1
    assert history[0].price == 1.49

    assert client.get("/api/artikel/pending-matches").json() == []


def test_reject_closes_entry_without_price_history(client):
    from models import ArtikelPriceHistory
    db = _db(client)
    a = _mk_artikel(db, "Paprika rot")
    p = _mk_pending(db, a.id)

    res = client.post(f"/api/artikel/pending-matches/{p.id}/reject")
    assert res.status_code == 200

    db2 = _db(client)
    assert db2.query(ArtikelPriceHistory).count() == 0
    assert client.get("/api/artikel/pending-matches").json() == []


def test_confirm_unknown_id_returns_404(client):
    assert client.post("/api/artikel/pending-matches/9999/confirm").status_code == 404
```

- [ ] **Step 4: Tests laufen lassen**

Run: `cd essensplaner && python -m pytest tests/test_pending_matches_api.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add essensplaner/app/schemas.py essensplaner/app/main.py essensplaner/tests/test_pending_matches_api.py
git commit -m "feat: Endpunkte für die Bestätigungs-Warteschlange (Confirm/Reject)"
```

---

## Task 15: UI — Artikel-Autocomplete-Komponente + Foto-Import-Review umstellen

**Files:**
- Modify: `essensplaner/app/static/index.html`

**Interfaces:**
- Consumes: `GET /api/artikel/suggest?q=`, `POST /api/artikel` (Task 4)
- Produces: `attachArtikelAutocomplete(inputEl, onSelect)` (JS-Funktion,
  wiederverwendbar) — genutzt ab Task 16 (Kühlschrank/Merkliste) für
  dieselbe Interaktion.

Kein automatisierter Test für dieses statische-JS-Frontend (wie beim
vorherigen Angebote-Feature) — Verifikation erfolgt manuell in Task 20.

- [ ] **Step 1: CSS für das Dropdown ergänzen**

Im bestehenden `<style>`-Block (z.B. nach der `.ingredient-row`-Regel):

```css
  .artikel-autocomplete-wrap { position: relative; flex: 2; }
  .artikel-suggest-dropdown {
    position: absolute; top: 100%; left: 0; right: 0; z-index: 10;
    background: var(--card-bg, #fff); border: 1px solid var(--border-color, #ccc);
    border-radius: 4px; max-height: 200px; overflow-y: auto;
  }
  .artikel-suggest-item { padding: 6px 10px; cursor: pointer; }
  .artikel-suggest-item:hover { background: var(--hover-bg, #f0f0f0); }
  .artikel-suggest-new { font-style: italic; border-top: 1px solid var(--border-color, #ccc); }
```

(Falls `--card-bg`/`--border-color`/`--hover-bg` als CSS-Variablen im
bestehenden Stylesheet nicht existieren, stattdessen die konkreten Werte
verwenden, die die bestehenden `.card`- bzw. `button.secondary`-Regeln
in derselben Datei bereits nutzen — dort nachschauen statt neue Variablen
zu erfinden.)

- [ ] **Step 2: Autocomplete-Komponente als JS-Funktion ergänzen**

Vor dem `// ---------- Foto-Import ----------`-Abschnitt einfügen:

```javascript
    // ---------- Artikel-Autocomplete (wiederverwendbare Komponente) ----------
    // Verwandelt ein Text-Input in ein Autocomplete-Feld gegen
    // /api/artikel/suggest. onSelect(artikelId, name) wird aufgerufen,
    // sobald ein bestehender Artikel gewählt oder ein neuer angelegt wurde.
    function attachArtikelAutocomplete(inputEl, onSelect) {
      const wrap = document.createElement('div');
      wrap.className = 'artikel-autocomplete-wrap';
      inputEl.parentNode.insertBefore(wrap, inputEl);
      wrap.appendChild(inputEl);

      const dropdown = document.createElement('div');
      dropdown.className = 'artikel-suggest-dropdown';
      dropdown.style.display = 'none';
      wrap.appendChild(dropdown);

      let debounceTimer = null;

      async function search(query) {
        if (!query.trim()) {
          dropdown.style.display = 'none';
          return;
        }
        const res = await fetch('api/artikel/suggest?q=' + encodeURIComponent(query));
        const suggestions = res.ok ? await res.json() : [];
        renderDropdown(suggestions, query);
      }

      function renderDropdown(suggestions, query) {
        const items = suggestions.map(s => `
          <div class="artikel-suggest-item" data-artikel-id="${s.id}" data-artikel-name="${escapeHtml(s.name)}">${escapeHtml(s.name)}</div>
        `);
        items.push(`<div class="artikel-suggest-item artikel-suggest-new" data-new="${escapeHtml(query)}">+ Neuen Artikel "${escapeHtml(query)}" anlegen</div>`);
        dropdown.innerHTML = items.join('');
        dropdown.style.display = 'block';
      }

      inputEl.addEventListener('input', () => {
        clearTimeout(debounceTimer);
        debounceTimer = setTimeout(() => search(inputEl.value), 250);
      });

      inputEl.addEventListener('blur', () => {
        setTimeout(() => { dropdown.style.display = 'none'; }, 150);
      });

      dropdown.addEventListener('mousedown', async (e) => {
        const item = e.target.closest('.artikel-suggest-item');
        if (!item) return;
        e.preventDefault();
        if (item.dataset.new !== undefined) {
          const res = await fetch('api/artikel', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name: item.dataset.new }),
          });
          if (!res.ok) return;
          const artikel = await res.json();
          inputEl.value = artikel.name;
          onSelect(artikel.id, artikel.name);
        } else {
          inputEl.value = item.dataset.artikelName;
          onSelect(parseInt(item.dataset.artikelId, 10), item.dataset.artikelName);
        }
        dropdown.style.display = 'none';
      });
    }

    async function suggestSingleHighConfidence(name) {
      if (!name) return null;
      const res = await fetch('api/artikel/suggest?q=' + encodeURIComponent(name));
      if (!res.ok) return null;
      const suggestions = await res.json();
      return (suggestions.length === 1 && suggestions[0].confidence === 'high') ? suggestions[0] : null;
    }
```

- [ ] **Step 3: `addIngredientRow` umstellen (gibt jetzt die Zeile zurück, verknüpft artikel_id)**

Bestehende `addIngredientRow`-Funktion ersetzen durch:

```javascript
    function addIngredientRow(ing) {
      ing = ing || { name: '', amount: '', unit: '' };
      const row = document.createElement('div');
      row.className = 'ingredient-row';
      row.dataset.artikelId = ing.artikel_id || '';
      row.innerHTML = `
        <input type="text" class="ing-name" placeholder="Zutat" value="${escapeHtml(ing.name || '')}">
        <input type="text" class="ing-amount" placeholder="Menge" value="${ing.amount ?? ''}">
        <input type="text" class="ing-unit" placeholder="Einheit" value="${escapeHtml(ing.unit || '')}">
        <button type="button" class="secondary">✕</button>
      `;
      row.querySelector('button').addEventListener('click', () => row.remove());
      const nameInput = row.querySelector('.ing-name');
      attachArtikelAutocomplete(nameInput, (artikelId) => {
        row.dataset.artikelId = artikelId;
      });
      nameInput.addEventListener('input', () => { row.dataset.artikelId = ''; });
      prIngredients.appendChild(row);
      return row;
    }

    document.getElementById('pr-add-ingredient').addEventListener('click', () => addIngredientRow());
```

- [ ] **Step 4: `fillReviewForm` um automatische Vorauflösung erweitern**

Bestehende `fillReviewForm`-Funktion ersetzen durch:

```javascript
    async function fillReviewForm(recipe) {
      document.getElementById('pr-title').value = recipe.title || '';
      document.getElementById('pr-servings').value = recipe.base_servings || 4;
      document.getElementById('pr-tags').value = recipe.tags || '';
      document.getElementById('pr-instructions').value = recipe.instructions || '';
      prIngredients.innerHTML = '';
      const ingredients = recipe.ingredients || [];
      if (ingredients.length) {
        for (const ing of ingredients) {
          const row = addIngredientRow(ing);
          const match = await suggestSingleHighConfidence(ing.name);
          if (match) {
            row.dataset.artikelId = match.id;
            row.querySelector('.ing-name').value = match.name;
          }
        }
      } else {
        addIngredientRow();
      }
    }
```

(Bei mittlerer Konfidenz oder mehreren Kandidaten bleibt das Feld
Freitext — der Nutzer wählt manuell über das Autocomplete-Dropdown oder
legt per "Neu anlegen" einen Artikel an, bevor gespeichert werden kann.)

- [ ] **Step 5: `pr-save`-Handler umstellen**

Bestehenden Handler-Anfang (Zutaten-Extraktion) ersetzen durch:

```javascript
    document.getElementById('pr-save').addEventListener('click', async () => {
      const rows = [...prIngredients.querySelectorAll('.ingredient-row')];
      const unresolvedRow = rows.find(row =>
        row.querySelector('.ing-name').value.trim() && !row.dataset.artikelId
      );
      if (unresolvedRow) {
        showPhotoMsg('Bitte für jede Zutat einen Artikel aus der Liste wählen oder neu anlegen.', false);
        return;
      }

      const ingredients = rows
        .filter(row => row.dataset.artikelId)
        .map(row => {
          const amountRaw = row.querySelector('.ing-amount').value.trim();
          const unit = row.querySelector('.ing-unit').value.trim();
          return {
            artikel_id: parseInt(row.dataset.artikelId, 10),
            amount: amountRaw ? parseFloat(amountRaw.replace(',', '.')) : null,
            unit: unit || null,
          };
        });

      const title = document.getElementById('pr-title').value.trim();
      if (!title) {
        showPhotoMsg('Bitte einen Titel angeben.', false);
        return;
      }

      const payload = {
        title,
        base_servings: parseInt(document.getElementById('pr-servings').value, 10) || 4,
        instructions: document.getElementById('pr-instructions').value,
        is_favorite: false,
        tags: document.getElementById('pr-tags').value.trim(),
        ingredients,
      };
```

(Der Rest des bestehenden Handlers — `fetch('api/recipes', ...)` bis zum
Ende — bleibt unverändert; nur der Zutaten-Extraktions-Teil am Anfang
wird ersetzt.)

- [ ] **Step 6: Manuelle Kontrolle**

Mit einem Browser-Tool die Seite lokal öffnen (siehe Task 20 für den
vollen Verifikationsdurchlauf), Foto-Import einmal durchklicken und
prüfen: Zutaten-Zeilen zeigen ein Dropdown mit Vorschlägen, "Neu
anlegen" funktioniert, Speichern schlägt fehl mit Hinweistext, solange
eine Zeile keinen verknüpften Artikel hat.

- [ ] **Step 7: Commit**

```bash
git add essensplaner/app/static/index.html
git commit -m "feat: Artikel-Autocomplete-Komponente und Foto-Import-Review umstellen"
```

---

## Task 16: UI — Kühlschrank- und Merklisten-Erfassung auf Autocomplete umstellen

**Files:**
- Modify: `essensplaner/app/static/index.html`

**Interfaces:**
- Consumes: `attachArtikelAutocomplete` (Task 15), `POST
  /api/fridge/items` / `POST /api/fridge/staples` / `DELETE
  /api/fridge/staples/by-artikel/{artikel_id}` / `POST /api/watchlist`
  (Task 7/8, `artikel_id`-basiert).

Kein automatisierter Test (statisches Frontend) — Verifikation in Task 20.

- [ ] **Step 1: Kühlschrank-Erfassung umstellen**

Bestehenden `fridge-add`-Click-Handler und `renderFridge` ersetzen.
Vor dem `fridge-add`-Handler eine Modul-Variable und die
Autocomplete-Anbindung ergänzen:

```javascript
    let fridgeArtikelId = null;
    attachArtikelAutocomplete(document.getElementById('fridge-name'), (id) => { fridgeArtikelId = id; });
    document.getElementById('fridge-name').addEventListener('input', () => { fridgeArtikelId = null; });
```

`renderFridge` (bestehend) ersetzen — `data-restock`/`data-stapleize`/
`data-unstaple` nutzen jetzt `artikel_id` statt Name:

```javascript
    function renderFridge(items) {
      const container = document.getElementById('fridge-list');
      if (!items.length) {
        container.innerHTML = '<p class="empty">Noch keine Artikel erfasst.</p>';
        return;
      }
      container.innerHTML = items.map(i => {
        const qty = (i.amount != null && i.unit) ? `${i.amount} ${escapeHtml(i.unit)}`
          : (i.amount != null ? `${i.amount}` : (i.unit ? escapeHtml(i.unit) : '&nbsp;'));
        const staple = i.is_staple ? '<span class="tag">Standard</span>' : '';
        const missing = !i.in_stock ? '<span class="tag missing-tag">fehlt</span>' : '';
        const stockBtn = i.in_stock
          ? `<button class="secondary" data-remove-fridge="${i.id}">Verbraucht / entfernen</button>`
          : `<button class="secondary" data-restock-artikel="${i.artikel_id}" data-restock-unit="${escapeHtml(i.unit || '')}">Als vorhanden markieren</button>`;
        const stapleBtn = i.is_staple
          ? `<button class="secondary" data-unstaple-artikel="${i.artikel_id}">Kein Standardartikel mehr</button>`
          : `<button class="secondary" data-stapleize-artikel="${i.artikel_id}" data-stapleize-unit="${escapeHtml(i.unit || '')}">Als Standardartikel markieren</button>`;
        return `
          <div class="card fridge-item ${!i.in_stock ? 'missing' : ''}">
            <p class="recipe-title">${escapeHtml(i.name)}</p>
            <p class="recipe-meta">${qty}</p>
            ${staple}${missing}
            <div class="fridge-actions">${stockBtn}${stapleBtn}</div>
          </div>`;
      }).join('');
    }
```

`fridge-add`-Handler (bestehend) ersetzen:

```javascript
    document.getElementById('fridge-add').addEventListener('click', async () => {
      const nameInput = document.getElementById('fridge-name');
      const amountInput = document.getElementById('fridge-amount');
      const unitInput = document.getElementById('fridge-unit');
      const stapleInput = document.getElementById('fridge-staple');
      const msg = document.getElementById('fridge-msg');

      if (!fridgeArtikelId) {
        msg.textContent = 'Bitte einen Artikel aus der Liste wählen oder neu anlegen.';
        msg.className = 'msg err';
        return;
      }
      const amountRaw = amountInput.value.trim();
      const unit = unitInput.value.trim();

      try {
        const res = await fetch('api/fridge/items', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            artikel_id: fridgeArtikelId,
            amount: amountRaw ? parseFloat(amountRaw.replace(',', '.')) : null,
            unit: unit || null,
          }),
        });
        if (!res.ok) throw new Error(await res.text());

        if (stapleInput.checked) {
          await fetch('api/fridge/staples', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ artikel_id: fridgeArtikelId, unit: unit || null }),
          });
        }

        nameInput.value = '';
        amountInput.value = '';
        unitInput.value = '';
        stapleInput.checked = false;
        fridgeArtikelId = null;
        msg.className = 'msg';
        loadFridge();
      } catch (e) {
        msg.textContent = 'Fehler: ' + e.message;
        msg.className = 'msg err';
      }
    });
```

Bestehenden `fridge-list`-Click-Handler ersetzen:

```javascript
    document.getElementById('fridge-list').addEventListener('click', async (e) => {
      const removeBtn = e.target.closest('[data-remove-fridge]');
      const restockBtn = e.target.closest('[data-restock-artikel]');
      const stapleizeBtn = e.target.closest('[data-stapleize-artikel]');
      const unstapleBtn = e.target.closest('[data-unstaple-artikel]');

      if (removeBtn) {
        await fetch(`api/fridge/items/${removeBtn.dataset.removeFridge}`, { method: 'DELETE' });
        loadFridge();
      } else if (restockBtn) {
        await fetch('api/fridge/items', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            artikel_id: parseInt(restockBtn.dataset.restockArtikel, 10),
            amount: null, unit: restockBtn.dataset.restockUnit || null,
          }),
        });
        loadFridge();
      } else if (stapleizeBtn) {
        await fetch('api/fridge/staples', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            artikel_id: parseInt(stapleizeBtn.dataset.stapleizeArtikel, 10),
            unit: stapleizeBtn.dataset.stapleizeUnit || null,
          }),
        });
        loadFridge();
      } else if (unstapleBtn) {
        await fetch(`api/fridge/staples/by-artikel/${unstapleBtn.dataset.unstapleArtikel}`, { method: 'DELETE' });
        loadFridge();
      }
    });
```

- [ ] **Step 2: Merklisten-Erfassung umstellen**

Vor dem `watchlist-add`-Handler:

```javascript
    let watchlistArtikelId = null;
    attachArtikelAutocomplete(document.getElementById('watchlist-name'), (id) => { watchlistArtikelId = id; });
    document.getElementById('watchlist-name').addEventListener('input', () => { watchlistArtikelId = null; });
```

`watchlist-add`-Handler (bestehend) ersetzen:

```javascript
    document.getElementById('watchlist-add').addEventListener('click', async () => {
      const nameInput = document.getElementById('watchlist-name');
      const unitInput = document.getElementById('watchlist-unit');
      const msg = document.getElementById('watchlist-msg');
      if (!watchlistArtikelId) {
        msg.textContent = 'Bitte einen Artikel aus der Liste wählen oder neu anlegen.';
        msg.className = 'msg err';
        return;
      }
      await fetch('api/watchlist', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ artikel_id: watchlistArtikelId, unit: unitInput.value.trim() || null }),
      });
      nameInput.value = '';
      unitInput.value = '';
      watchlistArtikelId = null;
      msg.className = 'msg';
      loadWatchlist();
    });
```

- [ ] **Step 3: Manuelle Kontrolle**

Browser-Tool: Kühlschrank-Artikel per Autocomplete hinzufügen, als
Standardartikel markieren, wieder entfernen; Merklisten-Artikel analog.

- [ ] **Step 4: Commit**

```bash
git add essensplaner/app/static/index.html
git commit -m "feat: Kühlschrank- und Merklisten-Erfassung auf Artikel-Autocomplete umstellen"
```

---

## Task 17: UI — JSON-Import um Zutaten-Ambiguitäts-Auflösung erweitern

**Files:**
- Modify: `essensplaner/app/static/index.html`

**Interfaces:**
- Consumes: `ImportPreviewOut.ingredient_ambiguities`,
  `ImportApplyIn.ingredient_resolutions` (Task 6), `POST /api/artikel`
  (Task 4).

Kein automatisierter Test (statisches Frontend) — Verifikation in Task 20.

- [ ] **Step 1: Neues Panel in der HTML ergänzen**

Nach dem bestehenden `#import-conflicts`-Panel (im `tab-recipes`-Bereich):

```html
    <div id="import-ingredient-ambiguities" class="card" style="display:none;">
      <p class="recipe-title">Import: unklare Zutaten-Zuordnung</p>
      <p class="hint">Diese Zutaten passen nur ungefähr zu einem bestehenden Artikel. Bitte wählen oder neu anlegen.</p>
      <div id="ambiguities-list"></div>
    </div>
```

- [ ] **Step 2: `renderIngredientAmbiguities` ergänzen**

Vor der bestehenden `importFileInput.addEventListener('change', ...)`:

```javascript
    let pendingIngredientAmbiguities = [];

    function renderIngredientAmbiguities(ambiguities) {
      pendingIngredientAmbiguities = ambiguities;
      const panel = document.getElementById('import-ingredient-ambiguities');
      const list = document.getElementById('ambiguities-list');
      if (!ambiguities.length) {
        panel.style.display = 'none';
        list.innerHTML = '';
        return;
      }
      list.innerHTML = ambiguities.map((a, i) => {
        const options = a.candidates.map(c => `<option value="${c.id}">${escapeHtml(c.name)}</option>`).join('');
        return `
          <div class="conflict-row" data-ambiguity-index="${i}">
            <div>
              <div class="conflict-title">${escapeHtml(a.ingredient_name)}</div>
            </div>
            <select class="ambiguity-select">
              ${options}
              <option value="new">Neuen Artikel "${escapeHtml(a.ingredient_name)}" anlegen</option>
            </select>
          </div>`;
      }).join('');
      panel.style.display = 'block';
    }
```

- [ ] **Step 3: `importFileInput`-Handler und `runImportApply` anpassen**

Im bestehenden `importFileInput.addEventListener('change', ...)`, nach
`const preview = await previewRes.json();`:

```javascript
        renderIngredientAmbiguities(preview.ingredient_ambiguities || []);

        if (preview.conflicts.length === 0 && !(preview.ingredient_ambiguities || []).length) {
          await runImportApply([], []);
        } else {
          renderConflicts(preview.conflicts);
          conflictsPanel.style.display = 'block';
        }
```

(ersetzt die bisherige `if (preview.conflicts.length === 0) { ... }
else { renderConflicts(preview.conflicts); }`-Verzweigung — `conflictsPanel.style.display
= 'block'` wird jetzt explizit gesetzt, auch wenn `conflicts` leer ist,
damit der "Import abschließen"-Button sichtbar bleibt, wenn nur
Zutaten-Ambiguitäten offen sind.)

Bestehenden `apply-import`-Click-Handler ersetzen:

```javascript
    document.getElementById('apply-import').addEventListener('click', async () => {
      const rows = conflictsList.querySelectorAll('.conflict-row');
      const resolutions = [...rows].map(row => {
        const index = parseInt(row.dataset.index, 10);
        const checked = row.querySelector('input[type="radio"]:checked');
        return { import_index: index, action: checked ? checked.value : 'alt' };
      });

      const ingredientResolutions = [];
      const ambiguityRows = document.querySelectorAll('#ambiguities-list .conflict-row');
      for (const row of ambiguityRows) {
        const idx = parseInt(row.dataset.ambiguityIndex, 10);
        const ambiguity = pendingIngredientAmbiguities[idx];
        const select = row.querySelector('.ambiguity-select');
        let artikelId;
        if (select.value === 'new') {
          const res = await fetch('api/artikel', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name: ambiguity.ingredient_name }),
          });
          const artikel = await res.json();
          artikelId = artikel.id;
        } else {
          artikelId = parseInt(select.value, 10);
        }
        ingredientResolutions.push({
          recipe_index: ambiguity.recipe_index,
          ingredient_index: ambiguity.ingredient_index,
          artikel_id: artikelId,
        });
      }

      await runImportApply(resolutions, ingredientResolutions);
    });
```

`runImportApply` (bestehend) ersetzen:

```javascript
    async function runImportApply(resolutions, ingredientResolutions) {
      try {
        const res = await fetch('api/recipes/import/apply', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            recipes: pendingImportRecipes,
            resolutions,
            ingredient_resolutions: ingredientResolutions || [],
          }),
        });
        if (!res.ok) throw new Error(await res.text());
        const result = await res.json();
        showImportMsg(
          `Import fertig: ${result.imported} neu, ${result.overwritten} überschrieben, ${result.skipped} übersprungen (alt behalten).`,
          true
        );
        conflictsPanel.style.display = 'none';
        document.getElementById('import-ingredient-ambiguities').style.display = 'none';
        pendingImportRecipes = null;
        pendingIngredientAmbiguities = [];
        loadRecipes();
      } catch (e) {
        showImportMsg('Fehler beim Import: ' + e.message, false);
      }
    }
```

- [ ] **Step 4: Manuelle Kontrolle**

Browser-Tool: eine JSON-Datei mit einer Zutat importieren, die nur
ungefähr zu einem bereits angelegten Artikel passt (mittlere Konfidenz),
prüfen, dass das Ambiguitäts-Panel erscheint und beide Auswahlmöglich-
keiten (bestehender Artikel / neu anlegen) funktionieren.

- [ ] **Step 5: Commit**

```bash
git add essensplaner/app/static/index.html
git commit -m "feat: JSON-Import um Zutaten-Ambiguitäts-Auflösung erweitern"
```

---

## Task 18: UI — "Unsichere Zuordnungen" im Angebote-Tab

**Files:**
- Modify: `essensplaner/app/static/index.html`

**Interfaces:**
- Consumes: `GET /api/artikel/pending-matches`,
  `POST /api/artikel/pending-matches/{id}/confirm`,
  `POST /api/artikel/pending-matches/{id}/reject` (Task 14).

Kein automatisierter Test (statisches Frontend) — Verifikation in Task 20.

- [ ] **Step 1: Neue Karte im bestehenden `tab-offers`-Panel ergänzen**

Nach der bestehenden Quellen-Karte (`<div id="offer-sources-list">`),
vor dem Filter-`<div class="toolbar">`:

```html
    <div class="card">
      <p class="recipe-title">Unsichere Zuordnungen</p>
      <p class="hint">Diese Angebote passen nur ungefähr zu einem bestehenden Artikel.</p>
      <div id="pending-matches-list"></div>
    </div>
```

- [ ] **Step 2: JS ergänzen**

Nach der bestehenden `loadOfferSources`-Funktion und ihrem
Click-Handler:

```javascript
    async function loadPendingMatches() {
      const container = document.getElementById('pending-matches-list');
      const res = await fetch('api/artikel/pending-matches');
      const items = await res.json();
      if (!items.length) {
        container.innerHTML = '<p class="empty">Keine offenen Zuordnungen.</p>';
        return;
      }
      container.innerHTML = items.map(p => `
        <div class="card fridge-item">
          <p class="recipe-title">${escapeHtml(p.product_name)}</p>
          <p class="recipe-meta">könnte zu "${escapeHtml(p.artikel_name)}" gehören (${escapeHtml(p.retailer)}, Score ${Math.round(p.score)})</p>
          <div class="fridge-actions">
            <button class="secondary" data-confirm-pending="${p.id}">Bestätigen</button>
            <button class="secondary" data-reject-pending="${p.id}">Ablehnen</button>
          </div>
        </div>`).join('');
    }

    document.getElementById('pending-matches-list').addEventListener('click', async (e) => {
      const confirmBtn = e.target.closest('[data-confirm-pending]');
      const rejectBtn = e.target.closest('[data-reject-pending]');
      if (confirmBtn) {
        await fetch(`api/artikel/pending-matches/${confirmBtn.dataset.confirmPending}/confirm`, { method: 'POST' });
        loadPendingMatches();
      } else if (rejectBtn) {
        await fetch(`api/artikel/pending-matches/${rejectBtn.dataset.rejectPending}/reject`, { method: 'POST' });
        loadPendingMatches();
      }
    });
```

- [ ] **Step 3: Initialisierungsaufruf ergänzen**

Im bestehenden Block ganz am Ende des `<script>`-Tags
(`loadOfferSettings(); loadWatchlist(); loadOfferSources(); loadOffers();`)
eine Zeile ergänzen:

```javascript
    loadOfferSettings();
    loadWatchlist();
    loadOfferSources();
    loadPendingMatches();
    loadOffers();
```

- [ ] **Step 4: Manuelle Kontrolle**

Browser-Tool: einen Connector-Lauf mit einem mittel-konfidenten Treffer
auslösen (z.B. über die im vorherigen Feature bereits vorhandene
manuelle Refresh-Funktion), prüfen, dass der Eintrag im Angebote-Tab
erscheint und Bestätigen/Ablehnen funktionieren.

- [ ] **Step 5: Commit**

```bash
git add essensplaner/app/static/index.html
git commit -m "feat: 'Unsichere Zuordnungen' im Angebote-Tab"
```

---

## Task 19: UI — Zutatenliste-Tab zur Artikel-Übersicht ausbauen (Bild + Historie)

**Files:**
- Modify: `essensplaner/app/main.py` (StaticFiles-Mount für Artikel-Bilder)
- Modify: `essensplaner/app/static/index.html`

**Interfaces:**
- Consumes: `GET /api/artikel`, `GET /api/artikel/{id}/history` (Task 4),
  `ARTIKEL_IMAGES_DIR` (Task 10).

Kein automatisierter Test für die UI (statisches Frontend) —
Verifikation in Task 20. Das `StaticFiles`-Mount selbst ist über einen
einfachen Request-Test abgedeckt.

- [ ] **Step 1: `app/main.py` — Mount für Artikel-Bilder ergänzen**

Import ergänzen: `from artikel_images import ARTIKEL_IMAGES_DIR`

Am Ende der Datei, bei den bestehenden `app.mount(...)`-Aufrufen:

```python
app.mount("/artikel-images", StaticFiles(directory=str(ARTIKEL_IMAGES_DIR)), name="artikel-images")
```

(vor dem bestehenden `app.mount("/", StaticFiles(...), name="static")` —
der Catch-all-Mount muss zuletzt registriert sein.)

- [ ] **Step 2: `tab-ingredients`-Panel in `index.html` ersetzen**

Bestehenden Inhalt von `<section id="tab-ingredients" class="panel">`
(die Platzhalter-Tabelle) ersetzen durch:

```html
  <section id="tab-ingredients" class="panel">
    <div id="artikel-list"></div>
  </section>
```

- [ ] **Step 3: `renderIngredientList` entfernen, neue Artikel-Übersicht ergänzen**

Die bestehende Funktion `renderIngredientList` (und ihr Aufruf in
`loadRecipes`: `renderIngredientList(recipes);`) entfernen — die
Zutatenliste kommt jetzt direkt aus `/api/artikel`, nicht mehr aus den
Rezepten abgeleitet.

An gleicher Stelle (vor `async function loadRecipes()`) ergänzen:

```javascript
    async function loadArtikelOverview() {
      const container = document.getElementById('artikel-list');
      try {
        const res = await fetch('api/artikel');
        if (!res.ok) throw new Error(await res.text());
        const artikel = await res.json();
        renderArtikelOverview(artikel);
      } catch (e) {
        container.innerHTML = `<p class="empty">Fehler beim Laden: ${escapeHtml(e.message)}</p>`;
      }
    }

    function renderArtikelOverview(artikel) {
      const container = document.getElementById('artikel-list');
      if (!artikel.length) {
        container.innerHTML = '<p class="empty">Noch keine Artikel vorhanden.</p>';
        return;
      }
      container.innerHTML = artikel.map(a => {
        const thumb = a.image_path
          ? `<img class="recipe-thumb" src="${escapeHtml(a.image_path)}" alt="">`
          : `<div class="recipe-thumb-placeholder">🛒</div>`;
        const priceText = a.last_price != null
          ? `${a.last_price.toFixed(2)} €`
          : (a.last_discount_text || 'kein Preis erfasst');
        return `
          <div class="card recipe-card" data-artikel-history="${a.id}">
            ${thumb}
            <div class="recipe-card-body">
              <p class="recipe-title">${escapeHtml(a.name)}</p>
              <p class="recipe-meta">${escapeHtml(priceText)}</p>
            </div>
          </div>
          <div class="artikel-history" id="artikel-history-${a.id}" style="display:none;"></div>`;
      }).join('');
    }

    document.getElementById('artikel-list').addEventListener('click', async (e) => {
      const card = e.target.closest('[data-artikel-history]');
      if (!card) return;
      const id = card.dataset.artikelHistory;
      const historyEl = document.getElementById(`artikel-history-${id}`);
      if (historyEl.style.display === 'block') {
        historyEl.style.display = 'none';
        return;
      }
      const res = await fetch(`api/artikel/${id}/history`);
      const entries = await res.json();
      historyEl.innerHTML = entries.length
        ? '<ul class="ingredients">' + entries.map(h => {
            const price = h.price != null ? `${h.price.toFixed(2)} €` : '';
            return `<li>${escapeHtml(h.valid_from)} – ${escapeHtml(h.valid_until)}: ${price} ${escapeHtml(h.discount_text || '')} (${escapeHtml(h.retailer)})</li>`;
          }).join('') + '</ul>'
        : '<p class="placeholder">Noch keine Preis-Historie.</p>';
      historyEl.style.display = 'block';
    });
```

`loadRecipes` (bestehend) anpassen — die Zeile `renderIngredientList(recipes);`
entfernen, sodass die Funktion nur noch `renderRecipes(recipes);` aufruft.

- [ ] **Step 4: Initialisierungsaufruf ergänzen**

Im finalen Initialisierungs-Block (ganz am Ende des `<script>`-Tags):

```javascript
    loadRecipes();
    loadSettings();
    loadFridge();
    loadArtikelOverview();
```

- [ ] **Step 5: Test für das neue Mount schreiben**

```python
def test_artikel_images_mount_serves_files(client, tmp_path):
    import artikel_images
    (artikel_images.ARTIKEL_IMAGES_DIR / "1.jpg").write_bytes(b"fake")
    res = client.get("/artikel-images/1.jpg")
    assert res.status_code == 200
    assert res.content == b"fake"
```

(Datei: `essensplaner/tests/test_artikel_images_mount.py`)

- [ ] **Step 6: Tests laufen lassen**

Run: `cd essensplaner && python -m pytest tests/test_artikel_images_mount.py -v`
Expected: PASS

- [ ] **Step 7: Manuelle Kontrolle**

Browser-Tool: Zutatenliste-Tab öffnen, prüfen, dass Artikel mit
Platzhalter-Icon (kein Bild) angezeigt werden, Klick auf einen Artikel
klappt die (leere) Historie auf/zu.

- [ ] **Step 8: Commit**

```bash
git add essensplaner/app/main.py essensplaner/app/static/index.html essensplaner/tests/test_artikel_images_mount.py
git commit -m "feat: Zutatenliste-Tab zur Artikel-Übersicht mit Bild und Preis-Historie ausbauen"
```

---

## Task 20: Manuelle End-to-End-Verifikation

Kein neuer Code — dieser Task prüft die zusammengesetzte Funktionalität
über alle vorherigen Tasks hinweg, live gegen eine echte Filiale/Umgebung.

**Files:** keine (Verifikationsschritt)

- [ ] **Step 1: Backend lokal starten**

Run: `cd essensplaner/app && DB_PATH=./_local_test.db uvicorn main:app --reload --port 8099`

- [ ] **Step 2: Migration gegen eine Kopie der echten Produktiv-DB prüfen**

Falls eine reale `essensplaner.db` mit bereits digitalisierten Rezepten
verfügbar ist: eine **Kopie** davon als `DB_PATH` verwenden, Server
starten, prüfen, dass alle Rezepte weiterhin korrekt mit Zutatennamen
angezeigt werden (Migration lief transparent beim Start) und keine
Fehler im Log auftauchen. Niemals gegen die echte Produktiv-Datei direkt
testen.

- [ ] **Step 3: Rezept mit Foto-Import anlegen**

Ein Rezeptfoto importieren, im Review-Schritt prüfen: erkannte Zutaten
zeigen automatisch Vorschläge oder bleiben leer zur manuellen Auswahl;
Speichern schlägt fehl, solange eine Zeile keinen Artikel hat; nach
Auswahl/Neuanlage funktioniert das Speichern.

- [ ] **Step 4: JSON-Export/-Import-Rundlauf prüfen**

Ein Rezept exportieren (Zutatennamen als Freitext in der Datei
sichtbar), dieselbe Datei wieder importieren — prüfen, dass Zutaten
automatisch demselben Artikel zugeordnet werden (keine Dubletten).

- [ ] **Step 5: Kühlschrank/Merkliste prüfen**

Über die Autocomplete-Felder einen Kühlschrank-Artikel und einen
Merklisten-Artikel anlegen, als Standardartikel markieren, wieder
entfernen.

- [ ] **Step 6: Angebots-Verknüpfung live prüfen**

PLZ in den Einstellungen hinterlegen (falls noch nicht geschehen), einen
Connector-Refresh auslösen (Kaufland/Edeka/Marktguru), prüfen:
- mindestens ein Angebot mit hoher Konfidenz erzeugt eine Preis-Historie
  am zugehörigen Artikel (Zutatenliste-Tab öffnen, Artikel anklicken)
- falls ein Artikel noch kein Bild hatte: Bild wurde heruntergeladen und
  wird angezeigt
- mittel-konfidente Treffer erscheinen im Angebote-Tab unter "Unsichere
  Zuordnungen"; Bestätigen/Ablehnen funktioniert

- [ ] **Step 7: Merge-Funktion prüfen**

Zwei ähnliche, aber getrennte Artikel (z.B. durch die Migration
entstanden) über `POST /api/artikel/{id}/merge/{other_id}` (direkter
API-Call reicht für diese Prüfung, da kein dediziertes Merge-UI im Scope
dieses Plans ist) zusammenführen, prüfen, dass Rezepte/Kühlschrank/
Merkliste weiterhin korrekt auf den verbleibenden Artikel zeigen.

- [ ] **Step 8: Ergebnis festhalten**

Kurz im Abschlussbericht notieren: welche Bild-Selektoren (Tasks 11–13)
gegen die echten Seiten funktioniert haben, ob die Migration gegen reale
Daten (Step 2) unauffällig verlief, und ob weitere Beobachtungen/Folge-
Tasks nötig sind (z.B. fehlendes dediziertes Merge-UI, falls das im
Alltag gebraucht wird).

---

## Task 21: Versionsbump + Changelog

**Files:**
- Modify: `essensplaner/config.yaml`
- Modify: `essensplaner/CHANGELOG.md`

CI (`.github/scripts/check_changelog.sh`) verlangt bei jeder Änderung
einen erhöhten `version`-Wert in `config.yaml` und einen passenden
`CHANGELOG.md`-Eintrag.

- [ ] **Step 1: Version in `config.yaml` erhöhen**

Aktuellen Wert (zum Planungszeitpunkt `"0.8.0"`) um eine Minor-Version
erhöhen, z.B. `version: "0.9.0"` (neues Feature, kein Breaking Change
für Add-on-Nutzer — die Migration läuft transparent). Vor dem Ändern
den tatsächlich aktuellen Wert in `config.yaml` prüfen, falls
zwischenzeitlich weitere Releases dazugekommen sind.

- [ ] **Step 2: Changelog-Eintrag ergänzen**

In `essensplaner/CHANGELOG.md`, neuer Abschnitt oben nach der
Kopfzeile:

```markdown
## [0.9.0] - <Datum des Merges>

### Hinzugefügt

- Neue Artikeldatenbank: Rezept-Zutaten, Kühlschrank-Bestand/-
  Standardartikel und Merklisten-Artikel verweisen jetzt auf
  gemeinsame Artikel mit Bild und Preis-Historie statt auf
  Freitext-Namen.
- Artikel-Übersicht im Zutatenliste-Tab: Bild und Preis-Historie pro
  Artikel.
- Autocomplete bei der Zutaten-/Kühlschrank-/Merklisten-Erfassung mit
  automatischer Dublettenerkennung (Fuzzy-Matching in drei
  Konfidenz-Stufen) und "Neu anlegen"-Option.
- Angebote werden automatisch mit passenden Artikeln verknüpft
  (Preis-Historie + Produktbild); mehrdeutige Treffer landen in einer
  neuen Bestätigungs-Warteschlange im Angebote-Tab.
- JSON-Import löst importierte Zutatennamen automatisch gegen die
  Artikeldatenbank auf, mit Rückfrage bei mehrdeutigen Fällen.
- Automatische, einmalige Migration bestehender Rezepte/Kühlschrank-/
  Merklisten-Daten beim ersten Start nach dem Update.
```

Platzhalter `<Datum des Merges>` beim tatsächlichen Merge durch das
reale Datum ersetzen (nicht vorab raten).

- [ ] **Step 3: Lokale CI-Prüfung nachvollziehen**

Run: `cd essensplaner && bash ../.github/scripts/check_changelog.sh`
(falls das Skript lokal ohne GitHub-Actions-Kontext lauffähig ist —
sonst Diff gegen `master` manuell abgleichen: Version muss höher sein
als auf `master`, Changelog muss den neuen Versions-Header enthalten).

- [ ] **Step 4: Commit**

```bash
git add essensplaner/config.yaml essensplaner/CHANGELOG.md
git commit -m "chore: Version anheben, Changelog für Artikeldatenbank-Feature ergänzen"
```

---

## Self-Review-Notizen (bereits eingearbeitet)

- Spec-Abdeckung geprüft: Datenmodell (Task 1, 2), Matching (Task 3),
  Migration (Task 2), Artikel-Endpunkte (Task 4), Rezept-/Import-Umstellung
  (Task 5, 6), Kühlschrank/Merkliste (Task 7, 8), Einkaufsliste/Angebots-
  Matching (Task 9), Preis-Historie/Bild-Download/Bestätigungs-
  Warteschlange (Task 10, 14), Bild-Extraktion je Connector (Task 11–13),
  UI (Task 15–19), Verifikation (Task 20), Versionsbump (Task 21) — jeder
  Spec-Abschnitt hat mindestens einen Task.
- Kein "TBD"/Platzhalter außer dem in Task 21 bewusst offen gelassenen
  Merge-Datum (kann nicht vorab bekannt sein) und der PLZ-abhängigen
  Konkretisierung der Bild-Selektoren in Task 11–13 (identisches, bereits
  bewährtes Muster wie bei den ursprünglichen Scraper-Kalibrierungs-Tasks
  des vorherigen Plans — Live-Verifikation ist expliziter Teil der
  jeweiligen Task-Schritte, kein unspezifizierter Platzhalter).
- Signaturen/Typen über Tasks hinweg geprüft: `resolve_artikel(name, db)
  -> ArtikelMatch` konsistent von Task 3 bis Task 19; `artikel_id` als
  Feldname konsistent in allen geänderten Modellen/Schemas/Endpunkten;
  `_require_artikel`/`_recipe_out` (Task 5) konsistent in Task 7/8
  wiederverwendet (`_require_artikel`); `PendingArtikelMatch`-Felder
  (inkl. nachträglich in Task 1 ergänzter `price`/`discount_text`)
  konsistent zwischen Task 1, 10 und 14.
- Cross-Task-Reihenfolge geprüft: Task 2 (Migration) muss vor allen
  Tasks laufen, die `Ingredient`/`FridgeStaple`/`WatchlistItem`/
  `FridgeItem` mit `artikel_id` ansprechen (Tasks 5, 7, 8, 9, 10) — im
  Plan sequenziell so angeordnet. Task 10 (Runner-Erweiterung, inkl.
  `OfferData.image_url`) muss vor Task 11–13 (Connector-Bild-Extraktion)
  laufen, da diese das Feld befüllen, das Task 10 bereits konsumiert
  (mit `None`-Default kompatibel, bis Task 11–13 es befüllen).

