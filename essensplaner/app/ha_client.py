"""
Kommunikation mit der Home Assistant Core API über den Supervisor-Proxy.
Nutzt den automatisch bereitgestellten SUPERVISOR_TOKEN (siehe config.yaml: homeassistant_api: true).
"""
import os
import httpx

HA_URL = os.environ.get("HA_URL", "http://supervisor/core")
TOKEN = os.environ.get("SUPERVISOR_TOKEN", "")
CALENDAR_ENTITY = os.environ.get("CALENDAR_ENTITY", "calendar.essensplan")
TODO_ENTITY = os.environ.get("TODO_ENTITY", "todo.einkaufen")

HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "Content-Type": "application/json",
}


async def _post(path: str, payload: dict):
    async with httpx.AsyncClient() as client:
        resp = await client.post(f"{HA_URL}{path}", headers=HEADERS, json=payload, timeout=10)
        resp.raise_for_status()
        return resp.json() if resp.content else None


async def upsert_calendar_event(date_str: str, title: str):
    """Legt für einen Tag ein Kalender-Event mit dem Rezeptnamen an (Local Calendar Integration)."""
    payload = {
        "entity_id": CALENDAR_ENTITY,
        "summary": title,
        "start_date": date_str,
        "end_date": date_str,
    }
    return await _post("/api/services/calendar/create_event", payload)


async def add_shopping_items(items: list[str]):
    """Fügt Zutaten als Einträge in die Bring!-synchronisierte To-do-Liste ein."""
    results = []
    for item in items:
        payload = {"entity_id": TODO_ENTITY, "item": item}
        results.append(await _post("/api/services/todo/add_item", payload))
    return results


async def set_day_options(input_select_entity: str, options: list[str]):
    """Aktualisiert die Auswahlmöglichkeiten eines input_select-Helpers (z.B. für schnelles Tauschen im Dashboard)."""
    payload = {"entity_id": input_select_entity, "options": options}
    return await _post("/api/services/input_select/set_options", payload)
