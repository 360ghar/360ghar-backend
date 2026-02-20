"""End-to-end checks for removed legacy auth endpoints."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_registration_endpoint_removed(client: AsyncClient):
    response = await client.post(
        "/api/v1/auth/register/",
        json={
            "phone": "+919876543210",
            "password": "SecurePass123!",
            "full_name": "New User",
            "email": "newuser@example.com",
        },
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_login_endpoint_removed(client: AsyncClient):
    response = await client.post(
        "/api/v1/auth/login/",
        json={"phone": "+919876543210", "password": "SecurePass123!"},
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_otp_endpoints_removed(client: AsyncClient):
    request_response = await client.post(
        "/api/v1/auth/otp/request",
        json={"phone": "+919876543210"},
    )
    verify_response = await client.post(
        "/api/v1/auth/otp/verify",
        json={"phone": "+919876543210", "token": "123456", "type": "sms"},
    )

    assert request_response.status_code == 404
    assert verify_response.status_code == 404
