from unittest.mock import AsyncMock, patch

import ha_client


async def _call():
    await ha_client.notify("3 neue Angebote")


async def _call_with_source(source):
    await ha_client.notify("3 neue Angebote", source=source)


def test_notify_calls_persistent_notification_service():
    with patch("ha_client._post", new_callable=AsyncMock) as mock_post:
        import asyncio
        asyncio.run(_call())
        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        assert args[0] == "/api/services/persistent_notification/create"
        assert args[1]["notification_id"] == "essensplaner_offers"


def test_notify_uses_source_specific_notification_id():
    """Ohne quellenspezifische notification_id überschreibt persistent_notification.create
    die Benachrichtigung einer Quelle mit der einer anderen, wenn mehrere Connector-Läufe
    (z.B. alle drei Angebots-Quellen sonntags 03:00) Treffer melden."""
    import asyncio
    with patch("ha_client._post", new_callable=AsyncMock) as mock_post:
        asyncio.run(_call_with_source("kaufland_scraper"))
        args, kwargs = mock_post.call_args
        kaufland_id = args[1]["notification_id"]

    with patch("ha_client._post", new_callable=AsyncMock) as mock_post:
        asyncio.run(_call_with_source("edeka_scraper"))
        args, kwargs = mock_post.call_args
        edeka_id = args[1]["notification_id"]

    assert kaufland_id != edeka_id
    assert "kaufland_scraper" in kaufland_id
    assert "edeka_scraper" in edeka_id
