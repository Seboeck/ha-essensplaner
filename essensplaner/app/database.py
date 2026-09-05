import os
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from models import Base, Offer, WatchlistItem, OfferSourceConfig

# /share übersteht Add-on-Deinstallation/-Neuinstallation (anders als /data,
# das der Supervisor beim Deinstallieren absichtlich löscht).
DB_PATH = os.environ.get("DB_PATH", "/share/essensplaner/essensplaner.db")
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
engine = create_engine(f"sqlite:///{DB_PATH}", connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


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
    Base.metadata.create_all(bind=engine)
    _migrate_add_missing_columns()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
