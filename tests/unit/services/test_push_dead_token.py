"""A token that FCM reports as unregistered is deactivated. The marker is in the response body.

No database. Supabase and FCM are mocks.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.models.enums import AppKey
from app.services.notifications import send_to_user

USER_ID = "3f2b8c1e-1111-4a2b-9c3d-123456789abc"
UNREGISTERED_BODY = (
    '{"error": {"code": 404, "status": "NOT_FOUND", "details": [{"errorCode": "UNREGISTERED"}]}}'
)


def _push_client(tokens: list[dict]) -> MagicMock:
    client = MagicMock()
    chain = client.table.return_value.select.return_value.eq.return_value.eq.return_value.eq
    chain.return_value.execute.return_value = SimpleNamespace(data=tokens)
    return client


def _fcm_error(status: int, body: str) -> httpx.HTTPStatusError:
    # str() of this error does not contain the body, as with a real FCM response.
    request = httpx.Request("POST", "https://fcm.googleapis.com/v1/projects/x/messages:send")
    response = httpx.Response(status, text=body, request=request)
    return httpx.HTTPStatusError(f"Error {status}", request=request, response=response)


async def _send_with_fcm_error(error: httpx.HTTPStatusError, client: MagicMock) -> dict:
    with (
        patch(
            "app.services.notifications.push._record_notification",
            AsyncMock(return_value={"id": "n1"}),
        ),
        patch(
            "app.services.notifications.helpers.get_supabase_service_client",
            return_value=client,
        ),
        patch(
            "app.services.notifications.push.fcm.send_message",
            AsyncMock(side_effect=error),
        ),
    ):
        return await send_to_user(user_id=USER_ID, title="T", body="B", app_key=AppKey.ghar)


@pytest.mark.asyncio
async def test_unregistered_body_on_404_deactivates_the_token():
    client = _push_client([{"token": "t1", "id": "d1"}])

    result = await _send_with_fcm_error(_fcm_error(404, UNREGISTERED_BODY), client)

    assert result["failed"] == 1
    updates = [call.args[0] for call in client.table.return_value.update.call_args_list]
    assert {"is_active": False} in updates


@pytest.mark.asyncio
async def test_server_error_without_the_marker_keeps_the_token_active():
    client = _push_client([{"token": "t1", "id": "d1"}])

    await _send_with_fcm_error(_fcm_error(500, '{"error": {"status": "INTERNAL"}}'), client)

    client.table.return_value.update.assert_not_called()
