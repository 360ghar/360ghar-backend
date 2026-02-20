"""
Tests for notification endpoints.
"""

from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient


class TestRegisterDeviceEndpoint:
    """Tests for POST /api/v1/notifications/devices/register endpoint."""

    @pytest.mark.asyncio
    async def test_register_device_token(self, authenticated_client: AsyncClient):
        """Test registering device token."""
        with patch(
            "app.api.api_v1.endpoints.notifications.register_device_token",
            new_callable=AsyncMock,
        ) as mock_register:
            mock_register.return_value = {"ok": True}

            response = await authenticated_client.post(
                "/api/v1/notifications/devices/register",
                json={
                    "token": "fcm_device_token_123",
                    "platform": "android",
                },
            )

            assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_register_device_token_ios(self, authenticated_client: AsyncClient):
        """Test registering iOS device token."""
        with patch(
            "app.api.api_v1.endpoints.notifications.register_device_token",
            new_callable=AsyncMock,
        ) as mock_register:
            mock_register.return_value = {"ok": True}

            response = await authenticated_client.post(
                "/api/v1/notifications/devices/register",
                json={
                    "token": "apns_device_token_456",
                    "platform": "ios",
                },
            )

            assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_register_device_unauthenticated(self, client: AsyncClient):
        """Test registering device token without auth (allowed but no user binding)."""
        with patch(
            "app.api.api_v1.endpoints.notifications.register_device_token",
            new_callable=AsyncMock,
        ) as mock_register:
            mock_register.return_value = {"ok": True}

            response = await client.post(
                "/api/v1/notifications/devices/register",
                json={
                    "token": "fcm_device_token_anonymous",
                    "platform": "android",
                },
            )

            # Anonymous registration is allowed
            assert response.status_code == 200


class TestUnregisterDeviceEndpoint:
    """Tests for DELETE /api/v1/notifications/devices/unregister endpoint."""

    @pytest.mark.asyncio
    async def test_unregister_device_token(self, authenticated_client: AsyncClient):
        with patch(
            "app.api.api_v1.endpoints.notifications.unregister_device_token",
            new_callable=AsyncMock,
        ) as mock_unregister:
            mock_unregister.return_value = {"ok": True}

            response = await authenticated_client.delete(
                "/api/v1/notifications/devices/unregister",
                params={"token": "fcm_device_token_123"},
            )

            assert response.status_code == 200
            mock_unregister.assert_awaited_once_with(token="fcm_device_token_123")

    @pytest.mark.asyncio
    async def test_unregister_requires_token(self, authenticated_client: AsyncClient):
        response = await authenticated_client.delete("/api/v1/notifications/devices/unregister")
        assert response.status_code == 422


class TestSendNotificationEndpoint:
    """Tests for admin notification sending."""

    @pytest.mark.asyncio
    async def test_send_to_topic(self, admin_authenticated_client: AsyncClient):
        """Test sending notification to topic."""
        with patch(
            "app.api.api_v1.endpoints.notifications.svc_send_to_topic",
            new_callable=AsyncMock,
        ) as mock_send:
            mock_send.return_value = {"ok": True}

            response = await admin_authenticated_client.post(
                "/api/v1/notifications/send/topic",
                json={
                    "topic": "all_users",
                    "title": "Announcement",
                    "body": "Important message",
                },
            )

            assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_send_to_user(self, admin_authenticated_client: AsyncClient):
        """Test sending notification to specific user."""
        with patch(
            "app.api.api_v1.endpoints.notifications.svc_send_to_user",
            new_callable=AsyncMock,
        ) as mock_send:
            mock_send.return_value = {"ok": True, "sent": 1}

            response = await admin_authenticated_client.post(
                "/api/v1/notifications/send/user",
                json={
                    "user_id": "550e8400-e29b-41d4-a716-446655440000",
                    "title": "Personal message",
                    "body": "Hello!",
                },
            )

            assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_send_to_topic_unauthorized(self, client: AsyncClient):
        """Test sending to topic without auth."""
        response = await client.post(
            "/api/v1/notifications/send/topic",
            json={
                "topic": "all_users",
                "title": "Test",
                "body": "Test",
            },
        )

        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_send_to_topic_forbidden_for_regular_user(
        self, authenticated_client: AsyncClient
    ):
        """Test regular user cannot send notifications."""
        response = await authenticated_client.post(
            "/api/v1/notifications/send/topic",
            json={
                "topic": "all_users",
                "title": "Test",
                "body": "Test",
            },
        )

        assert response.status_code == 403
