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
