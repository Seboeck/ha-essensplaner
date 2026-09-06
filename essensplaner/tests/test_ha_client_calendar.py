import json
from unittest.mock import AsyncMock, MagicMock, patch
import asyncio

import ha_client


def _mk_ws_mock(recv_sequence):
    """Baut ein Mock-Objekt für `websockets.connect(...)` als async
    Context-Manager, dessen `recv()` nacheinander die gegebenen (bereits
    JSON-serialisierten) Nachrichten liefert. `websockets.connect(...)`
    selbst ist synchron aufrufbar und liefert einen async Context-Manager
    zurück (kein `await` vor `connect(...)` nötig, nur vor `__aenter__`)."""
    ws = AsyncMock()
    ws.recv = AsyncMock(side_effect=[json.dumps(m) for m in recv_sequence])
    ws.send = AsyncMock()
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=ws)
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm, ws


def _successful_ws_delete_sequence():
    return [
        {"type": "auth_required"},
        {"type": "auth_ok"},
        {"id": 1, "type": "result", "success": True, "result": None},
    ]


def test_upsert_calendar_event_deletes_via_websocket_before_creating():
    """calendar.delete_event existiert nicht als REST-Service - Löschen
    muss über die WebSocket-API laufen (siehe Fix zu Finding 1 aus dem
    externen Review, live gegen eine echte HA-Instanz verifiziert:
    `ha_list_services(domain="calendar")` liefert nur create_event/
    get_events)."""
    existing = [{"uid": "alte-uid-123", "summary": "Altes Gericht"}]
    cm, ws = _mk_ws_mock(_successful_ws_delete_sequence())

    with patch("ha_client._get", new_callable=AsyncMock, return_value=existing), \
         patch("ha_client.websockets.connect", return_value=cm) as mock_connect, \
         patch("ha_client._post", new_callable=AsyncMock) as mock_post:
        asyncio.run(ha_client.upsert_calendar_event(
            "calendar.essensplan", "2026-09-07", "Neues Gericht", known_titles={"Altes Gericht"}
        ))

    mock_connect.assert_called_once_with(ha_client.WS_URL)
    # Auth-Handshake: type=auth mit Token, dann der eigentliche Delete-Befehl.
    sent = [json.loads(c.args[0]) for c in ws.send.call_args_list]
    assert sent[0] == {"type": "auth", "access_token": ha_client.TOKEN}
    assert sent[1]["type"] == "calendar/event/delete"
    assert sent[1]["entity_id"] == "calendar.essensplan"
    assert sent[1]["uid"] == "alte-uid-123"

    # delete_event wurde NICHT als REST-Service aufgerufen (existiert nicht).
    delete_rest_calls = [c for c in mock_post.call_args_list if c.args[0] == "/api/services/calendar/delete_event"]
    assert delete_rest_calls == []
    create_calls = [c for c in mock_post.call_args_list if c.args[0] == "/api/services/calendar/create_event"]
    assert len(create_calls) == 1
    assert create_calls[0].args[1]["summary"] == "Neues Gericht"


def test_upsert_calendar_event_skips_events_not_in_known_titles():
    """known_titles begrenzt das Löschen auf Events, deren summary zu einem
    bekannten eigenen Rezept-Titel gehört - Schutz vor versehentlichem
    Löschen fremder Termine, falls calendar_entity auf einen geteilten
    Kalender zeigt (siehe Finding 3 aus dem externen Review)."""
    existing = [{"uid": "fremder-termin", "summary": "Zahnarzttermin"}]

    with patch("ha_client._get", new_callable=AsyncMock, return_value=existing), \
         patch("ha_client.websockets.connect") as mock_connect, \
         patch("ha_client._post", new_callable=AsyncMock) as mock_post:
        asyncio.run(ha_client.upsert_calendar_event(
            "calendar.geteilt", "2026-09-07", "Neues Gericht", known_titles={"Anderes Rezept"}
        ))

    mock_connect.assert_not_called()  # kein Loesch-Versuch fuer den fremden Termin
    create_calls = [c for c in mock_post.call_args_list if c.args[0] == "/api/services/calendar/create_event"]
    assert len(create_calls) == 1


def test_upsert_calendar_event_deletes_everything_when_known_titles_omitted():
    """Ohne known_titles (None, Standardverhalten fuer die dedizierte
    calendar.essensplan-Entity) wird weiterhin jedes Event des Tages
    geloescht, unabhaengig vom Titel."""
    existing = [{"uid": "irgendein-event", "summary": "Irgendwas"}]
    cm, ws = _mk_ws_mock(_successful_ws_delete_sequence())

    with patch("ha_client._get", new_callable=AsyncMock, return_value=existing), \
         patch("ha_client.websockets.connect", return_value=cm), \
         patch("ha_client._post", new_callable=AsyncMock):
        asyncio.run(ha_client.upsert_calendar_event("calendar.essensplan", "2026-09-07", "Neues Gericht"))

    sent = [json.loads(c.args[0]) for c in ws.send.call_args_list]
    assert sent[1]["uid"] == "irgendein-event"


def test_upsert_calendar_event_creates_when_none_exists():
    with patch("ha_client._get", new_callable=AsyncMock, return_value=[]), \
         patch("ha_client.websockets.connect") as mock_connect, \
         patch("ha_client._post", new_callable=AsyncMock) as mock_post:
        asyncio.run(ha_client.upsert_calendar_event("calendar.essensplan", "2026-09-07", "Neues Gericht"))

    mock_connect.assert_not_called()
    create_calls = [c for c in mock_post.call_args_list if c.args[0] == "/api/services/calendar/create_event"]
    assert len(create_calls) == 1


def test_upsert_calendar_event_still_creates_if_query_fails():
    # upsert_calendar_event faengt gezielt httpx.HTTPError ab (die Basisklasse
    # aller von httpx bei Netzwerk-/Transportfehlern geworfenen Exceptions,
    # z.B. httpx.ConnectError, wenn HA nicht erreichbar ist) - kein generisches
    # Exception.
    import httpx
    with patch("ha_client._get", new_callable=AsyncMock, side_effect=httpx.ConnectError("HA nicht erreichbar")), \
         patch("ha_client._post", new_callable=AsyncMock) as mock_post:
        asyncio.run(ha_client.upsert_calendar_event("calendar.essensplan", "2026-09-07", "Neues Gericht"))

    create_calls = [c for c in mock_post.call_args_list if c.args[0] == "/api/services/calendar/create_event"]
    assert len(create_calls) == 1


def test_upsert_calendar_event_still_creates_if_ws_delete_fails():
    """Selbst wenn das Loeschen eines gefundenen alten Events fehlschlaegt
    (z.B. WS-Verbindung nicht moeglich), soll trotzdem versucht werden, das
    neue Event anzulegen."""
    existing = [{"uid": "alte-uid-123", "summary": "Altes Gericht"}]

    with patch("ha_client._get", new_callable=AsyncMock, return_value=existing), \
         patch("ha_client.websockets.connect", side_effect=OSError("Verbindung fehlgeschlagen")), \
         patch("ha_client._post", new_callable=AsyncMock) as mock_post:
        asyncio.run(ha_client.upsert_calendar_event(
            "calendar.essensplan", "2026-09-07", "Neues Gericht", known_titles={"Altes Gericht"}
        ))

    create_calls = [c for c in mock_post.call_args_list if c.args[0] == "/api/services/calendar/create_event"]
    assert len(create_calls) == 1


def test_ws_command_raises_on_auth_failure():
    """_ws_command() selbst wirft bei fehlgeschlagener Authentifizierung -
    der Aufrufer (upsert_calendar_event) faengt das ab, aber die Funktion
    selbst muss den Fehler klar melden, nicht stillschweigend weiterlaufen."""
    import pytest
    cm, ws = _mk_ws_mock([{"type": "auth_required"}, {"type": "auth_invalid"}])
    with patch("ha_client.websockets.connect", return_value=cm):
        with pytest.raises(RuntimeError):
            asyncio.run(ha_client._ws_command({"type": "calendar/event/delete", "entity_id": "x", "uid": "y"}))
