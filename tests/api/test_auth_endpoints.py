"""Tests that legacy auth endpoints are removed from the API surface."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("path", "payload"),
    [
        ("/api/v1/auth/login/", {"phone": "+919876543210", "password": "password123"}),
        (
            "/api/v1/auth/register/",
            {
                "phone": "+919876543210",
                "password": "password123",
                "full_name": "Test User",
            },
        ),
        ("/api/v1/auth/otp/request", {"phone": "+919876543210"}),
        ("/api/v1/auth/otp/verify", {"phone": "+919876543210", "token": "123456", "type": "sms"}),
        ("/api/v1/auth/refresh", {"refresh_token": "rt"}),
        ("/api/v1/auth/logout", {}),
        ("/api/v1/auth/forgot-password", {"phone": "+919876543210"}),
        ("/api/v1/auth/verify", {"phone": "+919876543210", "token": "123456", "type": "sms"}),
    ],
)
async def test_legacy_auth_endpoint_returns_not_found(client: AsyncClient, path: str, payload: dict):
    response = await client.post(path, json=payload)
    assert response.status_code == 404
