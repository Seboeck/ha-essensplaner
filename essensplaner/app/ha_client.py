"""
Kommunikation mit der Home Assistant Core API über den Supervisor-Proxy.
Nutzt den automatisch bereitgestellten SUPERVISOR_TOKEN (siehe config.yaml: homeassistant_api: true).
"""
import os
from datetime import date, timedelta

import httpx

HA_URL = os.environ.get("HA_URL", "http://supervisor/core")
TOKEN = os.environ.get("SUPERVISOR_TOKEN", "")
DEFAULT_CALENDAR_ENTITY = os.environ.get("CALENDAR_ENTITY", "calendar.essensplan")
DEFAULT_TODO_ENTITY = os.environ.get("TODO_ENTITY", "todo.einkaufen")

HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "Content-Type": "application/json",
}


async def _post(path: str, payload: dict):
    async with httpx.AsyncClient() as client:
        resp = await client.post(f"{HA_URL}{path}", headers=HEADERS, json=payload, timeout=10)
        resp.raise_for_status()
        return resp.json() if resp.content else None


async def _get(path: str, params: dict | None = None):
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{HA_URL}{path}", headers=HEADERS, params=params, timeout=10)
        resp.raise_for_status()
        return resp.json()


async def list_entities(domain: str) -> list[dict]:
    """Listet alle Entities einer Domain (z.B. 'calendar', 'todo') aus Home Assistant."""
    states = await _get("/api/states")
    result = []
    for s in states:
        entity_id = s.get("entity_id", "")
        if entity_id.startswith(f"{domain}."):
            friendly_name = s.get("attributes", {}).get("friendly_name", entity_id)
            result.append({"entity_id": entity_id, "friendly_name": friendly_name})
    return sorted(result, key=lambda e: e["friendly_name"].lower())


async def upsert_calendar_event(calendar_entity: str, date_str: str, title: str):
    """Legt für einen Tag ein Kalender-Event mit dem Rezeptnamen an (Local
    Calendar Integration). Ersetzt ein bereits vorhandenes Essensplaner-
    Event für denselben Tag, damit erneutes Generieren/Tauschen keine
    doppelten Termine erzeugt."""
    start_dt = date.fromisoformat(date_str)
    end_date_str = (start_dt + timedelta(days=1)).isoformat()

    try:
        existing_events = await _get(
            f"/api/calendars/{calendar_entity}",
            params={"start": f"{date_str}T00:00:00", "end": f"{end_date_str}T00:00:00"},
        )
    except httpx.HTTPError:
        existing_events = []  # Abfrage fehlgeschlagen -> trotzdem versuchen, neues Event anzulegen

    for ev in existing_events or []:
        uid = ev.get("uid")
        if uid:
            try:
                await _post("/api/services/calendar/delete_event", {"entity_id": calendar_entity, "uid": uid})
            except httpx.HTTPError:
                pass  # Event evtl. schon weg oder Löschen nicht unterstützt -- Neuanlage trotzdem versuchen

    payload = {
        "entity_id": calendar_entity,
        "summary": title,
        "start_date": date_str,
        "end_date": end_date_str,
    }
    return await _post("/api/services/calendar/create_event", payload)


async def add_shopping_items(todo_entity: str, items: list[str]):
    """Fügt Zutaten als Einträge in die (ggf. Bring!-synchronisierte) To-do-Liste ein."""
    results = []
    for item in items:
        payload = {"entity_id": todo_entity, "item": item}
        results.append(await _post("/api/services/todo/add_item", payload))
    return results


async def set_day_options(input_select_entity: str, options: list[str]):
    """Aktualisiert die Auswahlmöglichkeiten eines input_select-Helpers (z.B. für schnelles Tauschen im Dashboard)."""
    payload = {"entity_id": input_select_entity, "options": options}
    return await _post("/api/services/input_select/set_options", payload)


async def notify(message: str, title: str = "Essensplaner: Angebote", source: str | None = None):
    """Sammel-Benachrichtigung über persistent_notification (kein Empfänger-
    Setup nötig, funktioniert ohne konfigurierte mobile_app-Integration).

    `source` macht die notification_id je Angebots-Quelle eindeutig: ohne das
    würde `persistent_notification.create` bei gleicher id die Benachrichtigung
    einer anderen Quelle überschreiben (z.B. wenn mehrere Connector-Läufe am
    selben Termin ausgeführt werden)."""
    notification_id = f"essensplaner_offers_{source}" if source else "essensplaner_offers"
    payload = {"title": title, "message": message, "notification_id": notification_id}
    return await _post("/api/services/persistent_notification/create", payload)
