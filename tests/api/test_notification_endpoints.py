"""Tests for the notification endpoints (device tokens, inbox, admin sends)."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

from app.models.enums import AppKey, DevicePlatform
from app.schemas.pagination import offset_payload

ENDPOINTS = "app.api.api_v1.endpoints.notifications"


def _registration() -> dict:
    return {
        "platform": DevicePlatform.android,
        "app_key": AppKey.ghar,
        "app_version": None,
        "locale": None,
        "last_seen": datetime(2026, 10, 14, 9, 30, tzinfo=UTC),
    }


def _delivery_row(delivery_id: str = "d1", read_at: str | None = None) -> dict:
    return {
        "id": delivery_id,
        "type": "booking_confirmed",
        "title": "Booked",
        "body": "Your booking is confirmed",
        "data": {"_meta": {"type_key": "booking_confirmed"}},
        "created_at": datetime(2026, 10, 14, 9, 0, tzinfo=UTC),
        "read_at": read_at,
    }


class TestDeviceRegistration:
    """POST /notifications/devices/register"""

    @pytest.mark.asyncio
    async def test_register_returns_201_with_resource(self, authenticated_client: AsyncClient):
        with patch(f"{ENDPOINTS}.register_device_token", new_callable=AsyncMock) as mock_register:
            mock_register.return_value = _registration()
            response = await authenticated_client.post(
                "/api/v1/notifications/devices/register",
                json={"token": "fcm_token_1", "platform": "android", "app_key": "ghar"},
            )

        assert response.status_code == 201
        body = response.json()
        assert body["app_key"] == "ghar"
        assert body["platform"] == "android"
        assert body["last_seen"].endswith("Z")
        assert "ok" not in body
        kwargs = mock_register.call_args.kwargs
        assert kwargs["app_key"] == AppKey.ghar
        assert kwargs["user_id"] is not None

    @pytest.mark.asyncio
    async def test_register_rejects_user_id_in_body(self, authenticated_client: AsyncClient):
        with patch(f"{ENDPOINTS}.register_device_token", new_callable=AsyncMock) as mock_register:
            response = await authenticated_client.post(
                "/api/v1/notifications/devices/register",
                json={
                    "token": "t",
                    "platform": "android",
                    "app_key": "ghar",
                    "user_id": "someone-else",
                },
            )

        assert response.status_code == 422
        mock_register.assert_not_called()

    @pytest.mark.asyncio
    async def test_register_requires_app_key(self, authenticated_client: AsyncClient):
        response = await authenticated_client.post(
            "/api/v1/notifications/devices/register",
            json={"token": "t", "platform": "android"},
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_register_rejects_unknown_platform(self, authenticated_client: AsyncClient):
        response = await authenticated_client.post(
            "/api/v1/notifications/devices/register",
            json={"token": "t", "platform": "windows", "app_key": "ghar"},
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_anonymous_register_binds_no_user(self, client: AsyncClient):
        with patch(f"{ENDPOINTS}.register_device_token", new_callable=AsyncMock) as mock_register:
            mock_register.return_value = _registration()
            response = await client.post(
                "/api/v1/notifications/devices/register",
                json={"token": "t", "platform": "ios", "app_key": "flatmates"},
            )

        assert response.status_code == 201
        assert mock_register.call_args.kwargs["user_id"] is None
        assert mock_register.call_args.kwargs["app_key"] == AppKey.flatmates


class TestDeviceUnregistration:
    """DELETE /notifications/devices/unregister (token in the JSON body)"""

    @pytest.mark.asyncio
    async def test_unregister_is_scoped_to_caller_and_returns_204(
        self, authenticated_client: AsyncClient
    ):
        with patch(
            f"{ENDPOINTS}.unregister_device_token", new_callable=AsyncMock
        ) as mock_unregister:
            response = await authenticated_client.request(
                "DELETE",
                "/api/v1/notifications/devices/unregister",
                json={"token": "fcm_token_1"},
            )

        assert response.status_code == 204
        kwargs = mock_unregister.call_args.kwargs
        assert kwargs["token"] == "fcm_token_1"
        assert kwargs["user_id"]

    @pytest.mark.asyncio
    async def test_unregister_requires_authentication(self, client: AsyncClient):
        response = await client.request(
            "DELETE",
            "/api/v1/notifications/devices/unregister",
            json={"token": "fcm_token_1"},
        )
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_unregister_rejects_token_in_query_string(
        self, authenticated_client: AsyncClient
    ):
        response = await authenticated_client.request(
            "DELETE",
            "/api/v1/notifications/devices/unregister?token=fcm_token_1",
            json={},
        )
        assert response.status_code == 422


class TestMyNotifications:
    """GET /notifications/me: cursor page, unread count, read state per delivery."""

    @pytest.mark.asyncio
    async def test_returns_page_with_type_read_at_and_unread_count(
        self, authenticated_client: AsyncClient
    ):
        with patch(f"{ENDPOINTS}.list_deliveries_for_user", new_callable=AsyncMock) as mock_list:
            mock_list.return_value = (
                [_delivery_row("d1", read_at=None)],
                None,
                None,
                4,
            )
            response = await authenticated_client.get("/api/v1/notifications/me")

        assert response.status_code == 200
        body = response.json()
        assert body["unread_count"] == 4
        assert body["has_more"] is False
        assert body["total"] is None
        item = body["items"][0]
        assert item["id"] == "d1"
        assert item["type"] == "booking_confirmed"
        assert item["read_at"] is None
        assert item["created_at"].endswith("Z")

    @pytest.mark.asyncio
    async def test_unknown_query_key_is_rejected(self, authenticated_client: AsyncClient):
        response = await authenticated_client.get("/api/v1/notifications/me?bogus=1")
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_cursor_from_other_filter_is_rejected(self, authenticated_client: AsyncClient):
        """A cursor made for the full list cannot page the unread-only list."""
        with patch(f"{ENDPOINTS}.list_deliveries_for_user", new_callable=AsyncMock) as mock_list:
            mock_list.return_value = (
                [_delivery_row("d1"), _delivery_row("d2")],
                offset_payload(1),
                None,
                2,
            )
            first = await authenticated_client.get("/api/v1/notifications/me?limit=1")
        cursor = first.json()["next_cursor"]
        assert cursor

        response = await authenticated_client.get(
            f"/api/v1/notifications/me?limit=1&unread_only=true&cursor={cursor}"
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "INVALID_CURSOR"


class TestDeliveryRead:
    """POST /notifications/deliveries/{delivery_id}/opened"""

    @pytest.mark.asyncio
    async def test_marks_delivery_and_returns_read_at(self, authenticated_client: AsyncClient):
        with patch(f"{ENDPOINTS}.mark_delivery_opened", new_callable=AsyncMock) as mock_mark:
            mock_mark.return_value = {
                "ok": True,
                "delivery_id": "11111111-1111-1111-1111-111111111111",
                "read_at": "2026-10-14T09:30:00+00:00",
            }
            response = await authenticated_client.post(
                "/api/v1/notifications/deliveries/11111111-1111-1111-1111-111111111111/opened"
            )

        assert response.status_code == 200
        assert response.json() == {
            "delivery_id": "11111111-1111-1111-1111-111111111111",
            "read_at": "2026-10-14T09:30:00Z",
        }

    @pytest.mark.asyncio
    async def test_unknown_delivery_is_404_envelope(self, authenticated_client: AsyncClient):
        with patch(f"{ENDPOINTS}.mark_delivery_opened", new_callable=AsyncMock) as mock_mark:
            mock_mark.return_value = {"ok": False, "error": "not_found"}
            response = await authenticated_client.post("/api/v1/notifications/deliveries/x/opened")

        assert response.status_code == 404
        assert response.json()["error"]["code"] == "DELIVERY_NOT_FOUND"

    @pytest.mark.asyncio
    async def test_other_users_delivery_is_403(self, authenticated_client: AsyncClient):
        with patch(f"{ENDPOINTS}.mark_delivery_opened", new_callable=AsyncMock) as mock_mark:
            mock_mark.return_value = {"ok": False, "error": "forbidden"}
            response = await authenticated_client.post(
                "/api/v1/notifications/deliveries/11111111-1111-1111-1111-111111111111/opened"
            )
        assert response.status_code == 403


class TestAdminSends:
    """Admin sends. Every send is gated by the dispatcher."""

    @pytest.mark.asyncio
    async def test_typed_send_rejects_unregistered_type_key(
        self, admin_authenticated_client: AsyncClient
    ):
        with patch(
            f"{ENDPOINTS}.dispatch_notification_to_user", new_callable=AsyncMock
        ) as mock_dispatch:
            response = await admin_authenticated_client.post(
                "/api/v1/notifications/send/typed/user",
                json={"user_id": 1, "type_key": "not_a_type", "title": "T", "body": "B"},
            )

        assert response.status_code == 422
        mock_dispatch.assert_not_called()

    @pytest.mark.asyncio
    async def test_typed_send_returns_channel_outcomes(
        self, admin_authenticated_client: AsyncClient
    ):
        with patch(
            f"{ENDPOINTS}.dispatch_notification_to_user", new_callable=AsyncMock
        ) as mock_dispatch:
            mock_dispatch.return_value = {
                "type_key": "booking_confirmed",
                "title": "T",
                "body": "B",
                "sent_at": datetime(2026, 10, 14, 9, 30, tzinfo=UTC),
                "channels": {"push": {"ok": True, "sent": 1}},
            }
            response = await admin_authenticated_client.post(
                "/api/v1/notifications/send/typed/user",
                json={"user_id": 1, "type_key": "booking_confirmed", "title": "T", "body": "B"},
            )

        assert response.status_code == 200
        body = response.json()
        assert body["channels"]["push"] == {"ok": True, "sent": 1, "error": None}
        assert body["sent_at"].endswith("Z")

    @pytest.mark.asyncio
    async def test_typed_send_to_unknown_user_is_404_user_not_found(
        self, admin_authenticated_client: AsyncClient
    ):
        with patch(
            f"{ENDPOINTS}.dispatch_notification_to_user", new_callable=AsyncMock
        ) as mock_dispatch:
            mock_dispatch.return_value = {
                "type_key": "booking_confirmed",
                "title": "T",
                "body": "B",
                "sent_at": datetime(2026, 10, 14, 9, 30, tzinfo=UTC),
                "channels": {},
                "error": "user_not_found",
            }
            response = await admin_authenticated_client.post(
                "/api/v1/notifications/send/typed/user",
                json={
                    "user_id": 999999,
                    "type_key": "booking_confirmed",
                    "title": "T",
                    "body": "B",
                },
            )

        assert response.status_code == 404
        assert response.json()["error"]["code"] == "USER_NOT_FOUND"

    @pytest.mark.asyncio
    async def test_typed_send_reports_fcm_rate_limit_in_the_push_channel(
        self, admin_authenticated_client: AsyncClient
    ):
        """An FCM 429 does not change the HTTP status of a typed send. It is in channels.push."""
        with patch(
            f"{ENDPOINTS}.dispatch_notification_to_user", new_callable=AsyncMock
        ) as mock_dispatch:
            mock_dispatch.return_value = {
                "type_key": "booking_confirmed",
                "title": "T",
                "body": "B",
                "sent_at": datetime(2026, 10, 14, 9, 30, tzinfo=UTC),
                "channels": {"push": {"ok": False, "sent": 0, "error": "FCM_RATE_LIMITED"}},
            }
            response = await admin_authenticated_client.post(
                "/api/v1/notifications/send/typed/user",
                json={"user_id": 1, "type_key": "booking_confirmed", "title": "T", "body": "B"},
            )

        assert response.status_code == 200
        assert response.json()["channels"]["push"]["error"] == "FCM_RATE_LIMITED"

    @pytest.mark.asyncio
    async def test_topic_send_is_409_topic_channel_disabled(
        self, admin_authenticated_client: AsyncClient
    ):
        response = await admin_authenticated_client.post(
            "/api/v1/notifications/send/topic",
            json={"topic": "all", "title": "T", "body": "B"},
        )
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "TOPIC_CHANNEL_DISABLED"

    @pytest.mark.asyncio
    async def test_topic_send_requires_admin(self, authenticated_client: AsyncClient):
        response = await authenticated_client.post(
            "/api/v1/notifications/send/topic",
            json={"topic": "all", "title": "T", "body": "B"},
        )
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_raw_token_user_and_bulk_sends_are_removed(
        self, admin_authenticated_client: AsyncClient
    ):
        for path, body in (
            ("/api/v1/notifications/send/token", {"token": "t", "title": "T", "body": "B"}),
            ("/api/v1/notifications/send/user", {"user_id": "u", "title": "T", "body": "B"}),
            ("/api/v1/notifications/send/bulk", {"tokens": ["t"], "title": "T", "body": "B"}),
        ):
            response = await admin_authenticated_client.post(path, json=body)
            assert response.status_code == 404, path

    @pytest.mark.asyncio
    async def test_marketing_broadcast_rejects_non_marketing_type(
        self, admin_authenticated_client: AsyncClient
    ):
        response = await admin_authenticated_client.post(
            "/api/v1/notifications/marketing/broadcast",
            json={"type_key": "booking_confirmed", "title": "T", "body": "B"},
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_marketing_broadcast_covers_whole_audience_in_batches(
        self, admin_authenticated_client: AsyncClient
    ):
        audience = list(range(1, 451))
        with (
            patch(f"{ENDPOINTS}.count_users_for_segment", new_callable=AsyncMock, return_value=450),
            patch(
                f"{ENDPOINTS}.find_user_ids_for_segment",
                new_callable=AsyncMock,
                return_value=audience,
            ),
            patch(
                f"{ENDPOINTS}.dispatch_notification_to_users", new_callable=AsyncMock
            ) as mock_dispatch,
        ):
            mock_dispatch.side_effect = lambda db, *, user_db_ids, **kw: {
                "requested": len(user_db_ids),
                "succeeded": len(user_db_ids),
                "details": [],
            }
            response = await admin_authenticated_client.post(
                "/api/v1/notifications/marketing/broadcast",
                json={"type_key": "promotion_generic", "title": "T", "body": "B"},
            )

        assert response.status_code == 200
        assert response.json() == {"requested": 450, "processed": 450, "succeeded": 450}
        batch_sizes = [len(c.kwargs["user_db_ids"]) for c in mock_dispatch.call_args_list]
        assert batch_sizes == [200, 200, 50]
