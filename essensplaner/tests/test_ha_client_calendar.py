from unittest.mock import AsyncMock, patch
import asyncio
import ha_client


def test_upsert_calendar_event_deletes_existing_before_creating():
    existing = [{"uid": "alte-uid-123", "summary": "Altes Gericht"}]
    with patch("ha_client._get", new_callable=AsyncMock, return_value=existing) as mock_get, \
         patch("ha_client._post", new_callable=AsyncMock) as mock_post:
        asyncio.run(ha_client.upsert_calendar_event("calendar.essensplan", "2026-09-07", "Neues Gericht"))

    mock_get.assert_called_once()
    delete_calls = [c for c in mock_post.call_args_list if c.args[0] == "/api/services/calendar/delete_event"]
    create_calls = [c for c in mock_post.call_args_list if c.args[0] == "/api/services/calendar/create_event"]
    assert len(delete_calls) == 1
    assert delete_calls[0].args[1]["uid"] == "alte-uid-123"
    assert len(create_calls) == 1
    assert create_calls[0].args[1]["summary"] == "Neues Gericht"


def test_upsert_calendar_event_creates_when_none_exists():
    with patch("ha_client._get", new_callable=AsyncMock, return_value=[]), \
         patch("ha_client._post", new_callable=AsyncMock) as mock_post:
        asyncio.run(ha_client.upsert_calendar_event("calendar.essensplan", "2026-09-07", "Neues Gericht"))

    create_calls = [c for c in mock_post.call_args_list if c.args[0] == "/api/services/calendar/create_event"]
    assert len(create_calls) == 1


def test_upsert_calendar_event_still_creates_if_query_fails():
    # upsert_calendar_event faengt gezielt httpx.HTTPError ab (die Basisklasse
    # aller von httpx bei Netzwerk-/Transportfehlern geworfenen Exceptions,
    # z.B. httpx.ConnectError, wenn HA nicht erreichbar ist) - kein generisches
    # Exception, siehe Docstring/Fix C.
    import httpx
    with patch("ha_client._get", new_callable=AsyncMock, side_effect=httpx.ConnectError("HA nicht erreichbar")), \
         patch("ha_client._post", new_callable=AsyncMock) as mock_post:
        asyncio.run(ha_client.upsert_calendar_event("calendar.essensplan", "2026-09-07", "Neues Gericht"))

    create_calls = [c for c in mock_post.call_args_list if c.args[0] == "/api/services/calendar/create_event"]
    assert len(create_calls) == 1


def test_upsert_calendar_event_still_creates_if_delete_fails():
    """Selbst wenn das Loeschen eines gefundenen alten Events fehlschlaegt
    (z.B. Event bereits verschwunden), soll trotzdem versucht werden, das
    neue Event anzulegen."""
    existing = [{"uid": "alte-uid-123", "summary": "Altes Gericht"}]
    import httpx

    async def _post_side_effect(path, payload):
        if path == "/api/services/calendar/delete_event":
            raise httpx.HTTPError("delete fehlgeschlagen")
        return None

    with patch("ha_client._get", new_callable=AsyncMock, return_value=existing), \
         patch("ha_client._post", new_callable=AsyncMock, side_effect=_post_side_effect) as mock_post:
        asyncio.run(ha_client.upsert_calendar_event("calendar.essensplan", "2026-09-07", "Neues Gericht"))

    create_calls = [c for c in mock_post.call_args_list if c.args[0] == "/api/services/calendar/create_event"]
    assert len(create_calls) == 1
