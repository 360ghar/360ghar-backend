"""
Tests for notification service module.
"""

from unittest.mock import patch

import pytest

from app.core.exceptions import BadRequestException
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

    def test_build_message_with_topic(self):
        """Test building message with topic."""
        from app.services.notifications import build_message

        msg = build_message(
            topic="test_topic",
            title="Test Title",
            body="Test Body",
        )

        assert msg["message"]["topic"] == "test_topic"

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

    def test_build_message_with_deep_link(self):
        """Test building message with deep link."""
        from app.services.notifications import build_message

        msg = build_message(
            token="test_token",
            title="Test Title",
            body="Test Body",
            deep_link="myapp://properties/123",
        )

        assert "data" in msg["message"]
        assert msg["message"]["data"]["deep_link"] == "myapp://properties/123"

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

    def test_build_message_requires_token_or_topic(self):
        """Test that token or topic is required."""
        from app.services.notifications import build_message

        with pytest.raises(BadRequestException) as exc_info:
            build_message(title="Test", body="Test")

        assert exc_info.value.status_code == 400
        assert "token or topic" in str(exc_info.value).lower()

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
        """Test registering new device token."""
        from app.services.notifications import register_device_token

        with patch(
            "app.services.notifications.helpers.get_supabase_service_client",
            return_value=mock_supabase_client,
        ):
            result = await register_device_token(
                token="new_device_token",
                platform="android",
                user_id="user_123",
            )

            assert result["ok"] is True

    @pytest.mark.asyncio
    async def test_register_existing_device_upserts(self, mock_supabase_client):
        """Re-registering an existing token must upsert, not raise 23505."""
        from app.services.notifications import register_device_token

        with patch(
            "app.services.notifications.helpers.get_supabase_service_client",
            return_value=mock_supabase_client,
        ):
            result = await register_device_token(
                token="existing_device_token",
                platform="ios",
                user_id="user_456",
            )

            assert result["ok"] is True

    @pytest.mark.asyncio
    async def test_register_calls_upsert_with_on_conflict(self, mock_supabase_client):
        """Regression guard: upsert must be invoked with on_conflict='token'."""
        from app.services.notifications import register_device_token

        with patch(
            "app.services.notifications.helpers.get_supabase_service_client",
            return_value=mock_supabase_client,
        ):
            await register_device_token(
                token="race_token",
                platform="android",
                user_id="user_789",
            )

            upsert_mock = mock_supabase_client.table.return_value.upsert
            upsert_mock.assert_called_once()
            kwargs = upsert_mock.call_args.kwargs
            assert kwargs.get("on_conflict") == "token"


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


class TestSendToTopic:
    """Tests for send_to_topic function."""

    @pytest.mark.asyncio
    async def test_send_to_topic_success(self, mock_supabase_client, mock_fcm_send):
        """Test sending notification to topic."""
        from app.services.notifications import send_to_topic

        mock_supabase_client.table.return_value.insert.return_value.execute.return_value.data = [
            {"id": "notif_123"}
        ]

        with patch(
            "app.services.notifications.helpers.get_supabase_service_client",
            return_value=mock_supabase_client,
        ):
            with patch("app.services.notifications.fcm._access_token", return_value="test_token"):
                result = await send_to_topic(
                    topic="all_users",
                    title="Announcement",
                    body="Important message",
                )

                assert result["ok"] is True


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
