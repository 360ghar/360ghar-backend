"""
Tests for app.services.push_notification module.
"""

from unittest.mock import AsyncMock, patch

import pytest

from app.services.push_notification import (
    notify_listing_approved,
    notify_new_match,
    notify_new_message,
    notify_visit_confirmed,
    notify_visit_scheduled,
    send_push_notification,
)


class TestDispatchFallback:
    """Tests that notification dispatches gracefully fall back when dispatcher fails."""

    @pytest.mark.asyncio
    async def test_notify_new_message_fallback(self, mock_db_session):
        with patch(
            "app.services.notification_dispatcher.dispatch_notification_to_user",
            side_effect=ImportError("not available"),
        ):
            result = await notify_new_message(
                mock_db_session,
                recipient_db_id=1,
                sender_name="Alice",
                conversation_id=42,
            )
            assert result["fallback"] is True
            assert result["type_key"] == "flatmate_new_message"
            mock_db_session.begin_nested.assert_called_once()

    @pytest.mark.asyncio
    async def test_notify_new_match_fallback(self, mock_db_session):
        with patch(
            "app.services.notification_dispatcher.dispatch_notification_to_user",
            side_effect=Exception("connection error"),
        ):
            result = await notify_new_match(
                mock_db_session,
                recipient_db_id=1,
                peer_name="Bob",
                match_id=7,
            )
            assert result["fallback"] is True

    @pytest.mark.asyncio
    async def test_notify_listing_approved_fallback(self, mock_db_session):
        with patch(
            "app.services.notification_dispatcher.dispatch_notification_to_user",
            side_effect=Exception("FCM down"),
        ):
            result = await notify_listing_approved(
                mock_db_session,
                recipient_db_id=1,
                listing_title="My Room",
            )
            assert result["fallback"] is True

    @pytest.mark.asyncio
    async def test_notify_visit_scheduled_fallback(self, mock_db_session):
        with patch(
            "app.services.notification_dispatcher.dispatch_notification_to_user",
            side_effect=Exception("timeout"),
        ):
            result = await notify_visit_scheduled(
                mock_db_session,
                recipient_db_id=1,
                property_title="Flat 101",
                scheduled_date="2025-06-01",
            )
            assert result["fallback"] is True

    @pytest.mark.asyncio
    async def test_notify_visit_confirmed_fallback(self, mock_db_session):
        with patch(
            "app.services.notification_dispatcher.dispatch_notification_to_user",
            side_effect=Exception("service unavailable"),
        ):
            result = await notify_visit_confirmed(
                mock_db_session,
                recipient_db_id=1,
                property_title="Flat 101",
                scheduled_date="2025-06-01",
            )
            assert result["fallback"] is True


class TestSendPushNotification:
    """Tests for raw FCM send function."""

    @pytest.mark.asyncio
    async def test_send_push_notification_fallback(self, mock_db_session):
        with patch(
            "app.services.notifications.send_to_token",
            side_effect=Exception("no FCM"),
        ):
            result = await send_push_notification(
                mock_db_session,
                fcm_token="token123",
                title="Test",
                body="Body",
            )
            assert result["fallback"] is True

    @pytest.mark.asyncio
    async def test_send_push_notification_success(self, mock_db_session):
        with patch(
            "app.services.notifications.send_to_token",
            new_callable=AsyncMock,
            return_value={"ok": True, "message_id": "msg-123"},
        ):
            result = await send_push_notification(
                mock_db_session,
                fcm_token="valid-token",
                title="Hello",
                body="World",
                data={"route": "/test"},
            )
            assert result["ok"] is True


class TestNotifyDeepLinks:
    """Tests that notification helpers include correct deep-link routes."""

    @pytest.mark.asyncio
    async def test_new_message_route(self, mock_db_session):
        with patch(
            "app.services.notification_dispatcher.dispatch_notification_to_user",
            new_callable=AsyncMock,
            return_value={"ok": True},
        ) as mock_dispatch:
            await notify_new_message(
                mock_db_session,
                recipient_db_id=1,
                sender_name="Alice",
                conversation_id=42,
            )
            call_kwargs = mock_dispatch.call_args.kwargs
            # The route comes from the deep-link registry, the single source.
            assert call_kwargs.get("deep_link") == "/flatmates/chat/42"
            assert "data" not in call_kwargs or not call_kwargs["data"]
            mock_db_session.begin_nested.assert_called_once()

    @pytest.mark.asyncio
    async def test_new_match_has_no_route_until_a_conversation_id_is_passed(self, mock_db_session):
        with patch(
            "app.services.notification_dispatcher.dispatch_notification_to_user",
            new_callable=AsyncMock,
            return_value={"ok": True},
        ) as mock_dispatch:
            await notify_new_match(
                mock_db_session,
                recipient_db_id=1,
                peer_name="Bob",
                match_id=99,
            )
            call_kwargs = mock_dispatch.call_args.kwargs
            # The chat route takes a conversation id. match_id is not one, so no route is sent.
            assert call_kwargs.get("deep_link") is None

    @pytest.mark.asyncio
    async def test_listing_approved_has_no_route(self, mock_db_session):
        with patch(
            "app.services.notification_dispatcher.dispatch_notification_to_user",
            new_callable=AsyncMock,
            return_value={"ok": True},
        ) as mock_dispatch:
            await notify_listing_approved(
                mock_db_session,
                recipient_db_id=1,
                listing_title="Room A",
                boosted_for_hours=24,
            )
            call_kwargs = mock_dispatch.call_args.kwargs
            # The flatmates app has no /post route, so no deep link is sent.
            assert call_kwargs.get("deep_link") is None
            assert "boosted for 24 hours" in call_kwargs["body"]

    @pytest.mark.asyncio
    async def test_listing_approved_can_publish_realtime_immediately(self, mock_db_session):
        with (
            patch(
                "app.services.notification_dispatcher.dispatch_notification_to_user",
                new_callable=AsyncMock,
                return_value={"ok": True},
            ),
            patch(
                "app.services.flatmates.realtime.publish_flatmates_realtime_event",
                new_callable=AsyncMock,
            ) as mock_publish,
            patch("app.services.flatmates.realtime.queue_flatmates_realtime_event") as mock_queue,
        ):
            await notify_listing_approved(
                mock_db_session,
                recipient_db_id=1,
                listing_title="Room A",
                realtime_publish_immediately=True,
            )

            mock_queue.assert_not_called()
            mock_publish.assert_awaited_once()
            event_payload = mock_publish.await_args.args[0]
            assert event_payload.user_id == 1
            assert event_payload.event_type == "new_notification"
            assert event_payload.payload["type_key"] == "flatmate_listing_approved"

    @pytest.mark.asyncio
    async def test_visit_notifications_have_no_route(self, mock_db_session):
        with patch(
            "app.services.notification_dispatcher.dispatch_notification_to_user",
            new_callable=AsyncMock,
            return_value={"ok": True},
        ) as mock_dispatch:
            await notify_visit_scheduled(
                mock_db_session,
                recipient_db_id=1,
                property_title="Flat X",
                scheduled_date="2025-07-01",
            )
            call_kwargs = mock_dispatch.call_args.kwargs
            # The flatmates app has no /visits route, so no deep link is sent.
            assert call_kwargs.get("deep_link") is None
