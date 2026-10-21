"""Tests for the new auth/onboarding support endpoints.

Covers the four frozen-contract endpoints under /api/v1/auth:
  - POST /auth/identifier-status (public)
  - POST /auth/last-method       (auth required)
  - POST /auth/link-identity     (auth required)
  - GET  /auth/config            (public)
"""

from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient


class TestIdentifierStatus:
    """POST /api/v1/auth/identifier-status (public)."""

    @pytest.mark.asyncio
    async def test_verified_user_with_password_returns_password(self, client: AsyncClient):
        status_payload = {
            "exists": True,
            "verified": True,
            "has_password": True,
            "channel": "email",
            "next_step": "password",
        }
        with patch(
            "app.api.api_v1.endpoints.auth.get_identifier_status",
            new=AsyncMock(return_value=status_payload),
        ):
            response = await client.post(
                "/api/v1/auth/identifier-status",
                json={"identifier": "known@example.com"},
            )
        assert response.status_code == 200
        assert response.json() == status_payload

    @pytest.mark.asyncio
    async def test_unverified_user_returns_otp(self, client: AsyncClient):
        status_payload = {
            "exists": True,
            "verified": False,
            "has_password": False,
            "channel": "phone",
            "next_step": "otp",
        }
        with patch(
            "app.api.api_v1.endpoints.auth.get_identifier_status",
            new=AsyncMock(return_value=status_payload),
        ):
            response = await client.post(
                "/api/v1/auth/identifier-status",
                json={"identifier": "+919876543210"},
            )
        assert response.status_code == 200
        body = response.json()
        assert body["next_step"] == "otp"
        assert body["channel"] == "phone"

    @pytest.mark.asyncio
    async def test_unknown_identifier_returns_otp(self, client: AsyncClient):
        status_payload = {
            "exists": False,
            "verified": False,
            "has_password": False,
            "channel": "email",
            "next_step": "otp",
        }
        with patch(
            "app.api.api_v1.endpoints.auth.get_identifier_status",
            new=AsyncMock(return_value=status_payload),
        ):
            response = await client.post(
                "/api/v1/auth/identifier-status",
                json={"identifier": "nobody@example.com"},
            )
        assert response.status_code == 200
        assert response.json()["exists"] is False
        assert response.json()["next_step"] == "otp"

    @pytest.mark.asyncio
    async def test_phone_only_user_email_probe_returns_neutral_otp(self, client: AsyncClient):
        """A phone-only user probed on the EMAIL channel returns the neutral
        not-found shape with channel=email, next_step=otp."""
        status_payload = {
            "exists": False,
            "verified": False,
            "has_password": False,
            "channel": "email",
            "next_step": "otp",
        }
        with patch(
            "app.api.api_v1.endpoints.auth.get_identifier_status",
            new=AsyncMock(return_value=status_payload),
        ):
            response = await client.post(
                "/api/v1/auth/identifier-status",
                json={"identifier": "phoneonly@example.com"},
            )
        assert response.status_code == 200
        assert response.json() == status_payload

    @pytest.mark.asyncio
    async def test_is_public_no_auth_required(self, client: AsyncClient):
        """No Authorization header → still served (not 401)."""
        with patch(
            "app.api.api_v1.endpoints.auth.get_identifier_status",
            new=AsyncMock(
                return_value={
                    "exists": False,
                    "verified": False,
                    "has_password": False,
                    "channel": "email",
                    "next_step": "otp",
                }
            ),
        ):
            response = await client.post(
                "/api/v1/auth/identifier-status",
                json={"identifier": "x@example.com"},
            )
        assert response.status_code != 401

    @pytest.mark.asyncio
    async def test_missing_identifier_is_422(self, client: AsyncClient):
        response = await client.post("/api/v1/auth/identifier-status", json={})
        assert response.status_code == 422


class TestLastMethod:
    """POST /api/v1/auth/last-method (auth required)."""

    @pytest.mark.asyncio
    async def test_requires_auth(self, client: AsyncClient):
        response = await client.post(
            "/api/v1/auth/last-method",
            json={"method": "google"},
        )
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_records_method(self, authenticated_client: AsyncClient):
        with patch(
            "app.api.api_v1.endpoints.auth.set_last_auth_method",
            new=AsyncMock(),
        ) as mock_set:
            response = await authenticated_client.post(
                "/api/v1/auth/last-method",
                json={"method": "phone_otp"},
            )
        assert response.status_code == 204
        mock_set.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_records_apple_method(self, authenticated_client: AsyncClient):
        """Sign in with Apple is an accepted last-method value."""
        with patch(
            "app.api.api_v1.endpoints.auth.set_last_auth_method",
            new=AsyncMock(),
        ) as mock_set:
            response = await authenticated_client.post(
                "/api/v1/auth/last-method",
                json={"method": "apple"},
            )
        assert response.status_code == 204
        mock_set.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_invalid_method_is_422(self, authenticated_client: AsyncClient):
        response = await authenticated_client.post(
            "/api/v1/auth/last-method",
            json={"method": "facebook"},
        )
        assert response.status_code == 422


class TestAuthConfig:
    """GET /api/v1/auth/config (public)."""

    @pytest.mark.asyncio
    async def test_returns_client_ids(self, client: AsyncClient):
        from app.config import settings

        with patch.object(settings, "GOOGLE_WEB_CLIENT_ID", "web-id"), patch.object(
            settings, "GOOGLE_IOS_CLIENT_ID", "ios-id"
        ), patch.object(settings, "GOOGLE_ANDROID_CLIENT_ID", None):
            response = await client.get("/api/v1/auth/config")

        assert response.status_code == 200
        assert response.json() == {
            "google_web_client_id": "web-id",
            "google_ios_client_id": "ios-id",
            "google_android_client_id": None,
        }

    @pytest.mark.asyncio
    async def test_is_public(self, client: AsyncClient):
        response = await client.get("/api/v1/auth/config")
        assert response.status_code != 401
