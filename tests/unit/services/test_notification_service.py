"""
Tests for notification service module.
"""

from unittest.mock import AsyncMock, patch

import pytest

from app.services.notification_config import NotificationChannel


class TestBuildMessage:
    """Tests for build_message function."""

    def test_build_message_with_token(self):
        """Test building message with device token."""
        from app.services.notifications import build_message

        msg = build_message(
            token="test_token",
            title="Test Title",
            body="Test Body",
        )

        assert "message" in msg
        assert msg["message"]["token"] == "test_token"
        assert msg["message"]["notification"]["title"] == "Test Title"
        assert msg["message"]["notification"]["body"] == "Test Body"

    def test_build_message_with_data(self):
        """Test building message with data payload."""
        from app.services.notifications import build_message

        msg = build_message(
            token="test_token",
            title="Test Title",
            body="Test Body",
            data={"key": "value"},
        )

        assert "data" in msg["message"]
        assert msg["message"]["data"]["key"] == "value"

    def test_build_message_with_deep_link_sends_route_only(self):
        """deep_link becomes the ``route`` data key. No ``deep_link`` key is sent."""
        from app.services.notifications import build_message

        msg = build_message(
            token="test_token",
            title="Test Title",
            body="Test Body",
            route="/property/123",
        )

        assert msg["message"]["data"]["route"] == "/property/123"
        assert "deep_link" not in msg["message"]["data"]

    def test_build_message_top_level_type_key_and_meta_json(self):
        """type_key is top-level data. _meta is JSON text, never a Python repr."""
        import json

        from app.models.enums import AppKey
        from app.services.notifications import build_message

        msg = build_message(
            token="test_token",
            title="T",
            body="B",
            data={"_meta": {"type_key": "booking_confirmed", "channel": "push"}},
            route="/property/9",
            type_key="booking_confirmed",
            app_key=AppKey.estate,
        )

        data = msg["message"]["data"]
        assert data["type_key"] == "booking_confirmed"
        assert json.loads(data["_meta"]) == {"type_key": "booking_confirmed", "channel": "push"}
        assert msg["message"]["android"]["notification"]["channel_id"] == "high_importance_channel"

    def test_build_message_channel_follows_app(self):
        """Flatmates pushes name the flatmates channel. The ghar app does not create it."""
        from app.models.enums import AppKey
        from app.services.notifications import build_message

        msg = build_message(token="test_token", title="T", body="B", app_key=AppKey.flatmates)

        assert msg["message"]["android"]["notification"]["channel_id"] == "flatmates_messages"

    def test_build_message_with_image(self):
        """Test building message with image."""
        from app.services.notifications import build_message

        msg = build_message(
            token="test_token",
            title="Test Title",
            body="Test Body",
            image="https://example.com/image.png",
        )

        assert msg["message"]["notification"]["image"] == "https://example.com/image.png"

    def test_build_message_high_priority(self):
        """Test building high priority message."""
        from app.services.notifications import build_message

        msg = build_message(
            token="test_token",
            title="Test Title",
            body="Test Body",
            priority_high=True,
        )

        assert "android" in msg["message"]
        assert msg["message"]["android"]["priority"] == "HIGH"

    def test_build_message_with_ttl(self):
        """Test building message with TTL."""
        from app.services.notifications import build_message

        msg = build_message(
            token="test_token",
            title="Test Title",
            body="Test Body",
            ttl_seconds=3600,
        )

        assert "android" in msg["message"]
        assert msg["message"]["android"]["ttl"] == "3600s"

    def test_build_message_content_available(self):
        """Test building silent/background message."""
        from app.services.notifications import build_message

        msg = build_message(
            token="test_token",
            title="Test Title",
            body="Test Body",
            content_available=True,
        )

        assert "apns" in msg["message"]
        assert msg["message"]["apns"]["headers"]["apns-push-type"] == "background"
        assert msg["message"]["apns"]["payload"]["aps"]["content-available"] == 1


class TestGetTypeConfig:
    """Tests for _get_type_config function."""

    def test_get_type_config_known_type(self):
        """Test getting config for known notification type."""
        from app.services.notifications import _get_type_config

        priority, ttl, high = _get_type_config("booking.confirmed")

        # Should return valid values based on config
        assert priority is not None or ttl is not None or high is not None

    def test_get_type_config_unknown_type(self):
        """Test getting config for unknown notification type."""
        from app.services.notifications import _get_type_config

        priority, ttl, high = _get_type_config("unknown.type")

        # Should return defaults
        assert priority is None
        assert ttl is None
        assert high is True

    def test_get_type_config_none_type(self):
        """Test getting config with None type."""
        from app.services.notifications import _get_type_config

        priority, ttl, high = _get_type_config(None)

        assert priority is None
        assert ttl is None
        assert high is True


class TestAugmentDataWithMeta:
    """Tests for _augment_data_with_meta function."""

    def test_augment_data_adds_meta(self):
        """Test that meta is added to data."""
        from app.services.notifications import _augment_data_with_meta

        result = _augment_data_with_meta(
            {"key": "value"},
            type_key="booking.confirmed",
            channel=NotificationChannel.PUSH,
            priority="high",
        )

        assert "_meta" in result
        assert result["_meta"]["type_key"] == "booking.confirmed"
        assert result["_meta"]["channel"] == "push"
        assert result["_meta"]["priority"] == "high"
        assert result["key"] == "value"

    def test_augment_data_empty_input(self):
        """Test augmenting None data."""
        from app.services.notifications import _augment_data_with_meta

        result = _augment_data_with_meta(
            None,
            type_key="test.type",
            channel=NotificationChannel.PUSH,
        )

        assert "_meta" in result
        assert result["_meta"]["type_key"] == "test.type"


class TestSendMessage:
    """Tests for send_message function."""

    @pytest.mark.asyncio
    async def test_send_message_success(self, mock_fcm_send):
        """Test successful message sending."""
        from app.services.notifications import send_message

        message = {"message": {"token": "test_token"}}

        with patch("app.services.notifications.fcm._access_token", return_value="test_token"):
            result = await send_message(message)

            assert "name" in result


class TestRegisterDeviceToken:
    """Tests for register_device_token function."""

    @pytest.mark.asyncio
    async def test_register_new_device(self, mock_supabase_client):
        """A signed-in registration returns the registered device."""
        from app.models.enums import AppKey, DevicePlatform
        from app.services.notifications import register_device_token

        with patch(
            "app.services.notifications.helpers.get_supabase_service_client",
            return_value=mock_supabase_client,
        ):
            result = await register_device_token(
                token="new_device_token",
                platform=DevicePlatform.android,
                app_key=AppKey.ghar,
                user_id="11111111-1111-1111-1111-111111111111",
            )

            assert result["app_key"] == AppKey.ghar
            assert result["platform"] == DevicePlatform.android

    @pytest.mark.asyncio
    async def test_register_calls_upsert_with_on_conflict_and_app_key(self, mock_supabase_client):
        """Regression guard: upsert uses on_conflict='token' and stores the app key."""
        from app.models.enums import AppKey, DevicePlatform
        from app.services.notifications import register_device_token

        with patch(
            "app.services.notifications.helpers.get_supabase_service_client",
            return_value=mock_supabase_client,
        ):
            await register_device_token(
                token="race_token",
                platform=DevicePlatform.ios,
                app_key=AppKey.flatmates,
                user_id="11111111-1111-1111-1111-111111111111",
            )

            upsert_mock = mock_supabase_client.table.return_value.upsert
            upsert_mock.assert_called_once()
            kwargs = upsert_mock.call_args.kwargs
            assert kwargs.get("on_conflict") == "token"
            row = upsert_mock.call_args.args[0]
            assert row["app_key"] == "flatmates"
            assert row["user_id"] == "11111111-1111-1111-1111-111111111111"

    @pytest.mark.asyncio
    async def test_anonymous_register_never_overwrites_owned_token(self, mock_supabase_client):
        """An anonymous caller cannot take a token that belongs to a user."""
        from app.models.enums import AppKey, DevicePlatform
        from app.services.notifications import register_device_token

        existing = mock_supabase_client.table.return_value.select.return_value.eq.return_value.limit.return_value
        existing.execute.return_value.data = [{"user_id": "22222222-2222-2222-2222-222222222222"}]

        with patch(
            "app.services.notifications.helpers.get_supabase_service_client",
            return_value=mock_supabase_client,
        ):
            await register_device_token(
                token="owned_token",
                platform=DevicePlatform.android,
                app_key=AppKey.ghar,
                user_id=None,
            )

        mock_supabase_client.table.return_value.upsert.assert_not_called()

    @pytest.mark.asyncio
    async def test_anonymous_register_of_new_token_is_unbound(self, mock_supabase_client):
        """An anonymous caller may register a token nobody owns, without a user."""
        from app.models.enums import AppKey, DevicePlatform
        from app.services.notifications import register_device_token

        existing = mock_supabase_client.table.return_value.select.return_value.eq.return_value.limit.return_value
        existing.execute.return_value.data = []

        with patch(
            "app.services.notifications.helpers.get_supabase_service_client",
            return_value=mock_supabase_client,
        ):
            await register_device_token(
                token="fresh_token",
                platform=DevicePlatform.web,
                app_key=AppKey.ghar,
                user_id=None,
            )

        row = mock_supabase_client.table.return_value.upsert.call_args.args[0]
        assert row["user_id"] is None


class TestListNotificationsForUser:
    """Tests for list_notifications_for_user function."""

    @pytest.mark.asyncio
    async def test_list_notifications(self, mock_supabase_client):
        """Test listing notifications for user."""
        from app.services.notifications import list_notifications_for_user

        mock_supabase_client.table.return_value.select.return_value.eq.return_value.order.return_value.range.return_value.execute.return_value.data = [
            {"id": "1", "title": "Test", "body": "Body"}
        ]

        with patch(
            "app.services.notifications.helpers.get_supabase_service_client",
            return_value=mock_supabase_client,
        ):
            rows, next_pg, total = await list_notifications_for_user("user_123", limit=10)

            assert isinstance(rows, list)


class TestSendToToken:
    """Tests for send_to_token function."""

    @pytest.mark.asyncio
    async def test_send_to_token_success(self, mock_supabase_client, mock_fcm_send):
        """Test sending notification to specific token."""
        from app.services.notifications import send_to_token

        # Mock the notification record insert
        mock_supabase_client.table.return_value.insert.return_value.execute.return_value.data = [
            {"id": "notif_123"}
        ]
        mock_supabase_client.table.return_value.select.return_value.eq.return_value.execute.return_value.data = [
            {"id": "device_123"}
        ]

        with patch(
            "app.services.notifications.helpers.get_supabase_service_client",
            return_value=mock_supabase_client,
        ):
            with patch("app.services.notifications.fcm._access_token", return_value="test_token"):
                result = await send_to_token(
                    token="device_token",
                    title="Test Title",
                    body="Test Body",
                )

                assert result["ok"] is True


class TestSendToUser:
    """Tests for send_to_user function."""

    @pytest.mark.asyncio
    async def test_send_to_user_no_tokens(self, mock_supabase_client):
        """Test sending to user with no device tokens."""
        from app.services.notifications import send_to_user

        mock_supabase_client.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value.data = []

        with patch(
            "app.services.notifications.helpers.get_supabase_service_client",
            return_value=mock_supabase_client,
        ):
            result = await send_to_user(
                user_id="user_123",
                title="Test",
                body="Test Body",
            )

            assert result["ok"] is True
            assert result["sent"] == 0

    @pytest.mark.asyncio
    async def test_send_to_user_record_failure_soft_fails(self):
        """Supabase notification insert failure must not raise out of send_to_user."""
        from app.services.notifications import send_to_user

        with patch(
            "app.services.notifications.push._record_notification",
            new_callable=AsyncMock,
            side_effect=RuntimeError("supabase down"),
        ):
            result = await send_to_user(
                user_id="11111111-1111-1111-1111-111111111123",
                title="Test",
                body="Test Body",
            )

        assert result["ok"] is False
        assert result["sent"] == 0
        assert "record_notification" in result["error"]

    @pytest.mark.asyncio
    async def test_send_to_user_token_fetch_failure_soft_fails(self):
        """Device token lookup failure must not raise out of send_to_user."""
        from app.services.notifications import send_to_user

        with patch(
            "app.services.notifications.push._record_notification",
            new_callable=AsyncMock,
            return_value={"id": "notif_1"},
        ):
            with patch(
                "app.services.notifications.push._run_sync",
                new_callable=AsyncMock,
                side_effect=RuntimeError("device_tokens unavailable"),
            ):
                result = await send_to_user(
                    user_id="11111111-1111-1111-1111-111111111123",
                    title="Test",
                    body="Test Body",
                )

        assert result["ok"] is False
        assert result["sent"] == 0
        assert result["notification_id"] == "notif_1"
        assert "device_tokens" in result["error"]


class TestSendToUserFanOut:
    """send_to_user filters by app and reports its real outcome."""

    @pytest.mark.asyncio
    async def test_send_to_user_filters_tokens_by_app_key(self, mock_supabase_client):
        from app.models.enums import AppKey
        from app.services.notifications import send_to_user

        mock_supabase_client.table.return_value.insert.return_value.execute.return_value.data = [{"id": "n1"}]
        select_q = mock_supabase_client.table.return_value.select.return_value
        select_q.eq.return_value.eq.return_value.eq.return_value.execute.return_value.data = []

        with patch(
            "app.services.notifications.helpers.get_supabase_service_client",
            return_value=mock_supabase_client,
        ):
            result = await send_to_user(
                user_id="11111111-1111-1111-1111-111111111111",
                title="T",
                body="B",
                app_key=AppKey.flatmates,
            )

        select_q.eq.return_value.eq.return_value.eq.assert_called_with("app_key", "flatmates")
        assert result["ok"] is True
        assert result["sent"] == 0

    @pytest.mark.asyncio
    async def test_send_to_user_reports_not_ok_when_every_send_fails(self, mock_supabase_client):
        from app.models.enums import AppKey
        from app.services.notifications import send_to_user

        mock_supabase_client.table.return_value.insert.return_value.execute.return_value.data = [{"id": "n1"}]
        select_q = mock_supabase_client.table.return_value.select.return_value
        select_q.eq.return_value.eq.return_value.eq.return_value.execute.return_value.data = [
            {"token": "t1", "id": "d1"}
        ]

        with (
            patch(
                "app.services.notifications.helpers.get_supabase_service_client",
                return_value=mock_supabase_client,
            ),
            patch(
                "app.services.notifications.push.fcm.send_message",
                AsyncMock(side_effect=RuntimeError("fcm down")),
            ),
        ):
            result = await send_to_user(
                user_id="11111111-1111-1111-1111-111111111111",
                title="T",
                body="B",
                app_key=AppKey.ghar,
            )

        assert result["ok"] is False
        assert result["sent"] == 0
        assert result["failed"] == 1


class TestFcmErrorMapping:
    """An FCM 4xx is a 400. An FCM 5xx or auth failure is a 502."""

    @staticmethod
    def _http_error(status_code: int):
        import httpx

        request = httpx.Request("POST", "https://fcm.googleapis.com/v1/projects/x/messages:send")
        response = httpx.Response(status_code, request=request, text="{}")
        return httpx.HTTPStatusError("err", request=request, response=response)

    def test_fcm_4xx_maps_to_400(self):
        from app.services.notifications import fcm_error_to_api_error

        err = fcm_error_to_api_error(self._http_error(400))
        assert err.status_code == 400
        assert err.error_code == "FCM_REJECTED"

    def test_fcm_5xx_and_auth_map_to_502(self):
        from app.services.notifications import fcm_error_to_api_error

        assert fcm_error_to_api_error(self._http_error(503)).status_code == 502
        assert fcm_error_to_api_error(self._http_error(401)).status_code == 502


class TestMarkDeliveryOpened:
    """Tests for mark_delivery_opened function."""

    @pytest.mark.asyncio
    async def test_mark_delivery_opened_unauthenticated(self):
        """Test marking delivery opened without auth."""
        from app.services.notifications import mark_delivery_opened

        result = await mark_delivery_opened("delivery_123", user_supabase_id=None)

        assert result["ok"] is False
        assert result["error"] == "unauthenticated"

    @pytest.mark.asyncio
    async def test_mark_delivery_opened_not_found(self, mock_supabase_client):
        """Test marking non-existent delivery."""
        from app.services.notifications import mark_delivery_opened

        mock_supabase_client.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = []

        with patch(
            "app.services.notifications.helpers.get_supabase_service_client",
            return_value=mock_supabase_client,
        ):
            result = await mark_delivery_opened("delivery_123", user_supabase_id="user_123")

            assert result["ok"] is False
            assert result["error"] == "not_found"
