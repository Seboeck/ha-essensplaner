from unittest.mock import AsyncMock, patch

import ha_client


async def _call():
    await ha_client.notify("3 neue Angebote")


def test_notify_calls_persistent_notification_service():
    with patch("ha_client._post", new_callable=AsyncMock) as mock_post:
        import asyncio
        asyncio.run(_call())
        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        assert args[0] == "/api/services/persistent_notification/create"
        assert args[1]["notification_id"] == "essensplaner_offers"
