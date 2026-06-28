"""Tests for the Supabase password-changed webhook (Security #11).

Verifies:
  * A valid HMAC signature triggers session revocation (httpx mocked).
  * An invalid HMAC signature is rejected with 401.
  * A missing signature header is rejected with 401.

The test mounts ONLY the webhook router on a minimal FastAPI app (with the
shared exception handlers) so it does not depend on the full application
factory — keeping it robust to unrelated endpoint breakages.
"""

from __future__ import annotations

import hashlib
import hmac
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.api_v1.endpoints.webhooks.auth import router as webhook_router
from app.infrastructure.errors import register_exception_handlers

WEBHOOK_SECRET = "test-webhook-secret-1234567890"
WEBHOOK_PATH = "/api/v1/webhooks/auth/password-changed"


def _build_app() -> FastAPI:
    """Minimal app exposing only the webhook router under /api/v1."""
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(webhook_router, prefix="/api/v1")
    return app


def _sign(body: bytes, secret: str = WEBHOOK_SECRET) -> str:
    return hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


@pytest.fixture
def app_with_secret():
    """Patch the webhook secret + cache-free rate limiter for the test window."""
    from app.config import settings

    with patch.object(settings, "SUPABASE_WEBHOOK_SECRET", WEBHOOK_SECRET):
        yield _build_app()


@pytest.mark.asyncio
async def test_valid_signature_triggers_revocation(app_with_secret):
    body = b'{"user_id":"supabase-uuid-abc"}'
    signature = _sign(body)

    with patch(
        "app.api.api_v1.endpoints.webhooks.auth.revoke_all_user_sessions",
        new=AsyncMock(),
    ) as mock_revoke, patch(
        "app.api.api_v1.endpoints.webhooks.auth._webhook_limiter.check_rate_limit",
        new=AsyncMock(return_value=True),
    ):
        transport = ASGITransport(app=app_with_secret)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            response = await ac.post(
                WEBHOOK_PATH,
                content=body,
                headers={
                    "Content-Type": "application/json",
                    "X-Supabase-Signature": signature,
                },
            )

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "revoked"
    assert response.json()["user_id"] == "supabase-uuid-abc"
    mock_revoke.assert_awaited_once_with("supabase-uuid-abc")


@pytest.mark.asyncio
async def test_invalid_signature_returns_401(app_with_secret):
    body = b'{"user_id":"supabase-uuid-abc"}'

    with patch(
        "app.api.api_v1.endpoints.webhooks.auth.revoke_all_user_sessions",
        new=AsyncMock(),
    ) as mock_revoke, patch(
        "app.api.api_v1.endpoints.webhooks.auth._webhook_limiter.check_rate_limit",
        new=AsyncMock(return_value=True),
    ):
        transport = ASGITransport(app=app_with_secret)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            response = await ac.post(
                WEBHOOK_PATH,
                content=body,
                headers={
                    "Content-Type": "application/json",
                    "X-Supabase-Signature": "deadbeef" * 8,
                },
            )

    assert response.status_code == 401, response.text
    mock_revoke.assert_not_awaited()


@pytest.mark.asyncio
async def test_missing_signature_returns_401(app_with_secret):
    body = b'{"user_id":"supabase-uuid-abc"}'

    with patch(
        "app.api.api_v1.endpoints.webhooks.auth.revoke_all_user_sessions",
        new=AsyncMock(),
    ) as mock_revoke, patch(
        "app.api.api_v1.endpoints.webhooks.auth._webhook_limiter.check_rate_limit",
        new=AsyncMock(return_value=True),
    ):
        transport = ASGITransport(app=app_with_secret)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            response = await ac.post(
                WEBHOOK_PATH,
                content=body,
                headers={"Content-Type": "application/json"},
            )

    assert response.status_code == 401, response.text
    mock_revoke.assert_not_awaited()


@pytest.mark.asyncio
async def test_revocation_failure_returns_503(app_with_secret):
    """When Supabase is unreachable, the webhook surfaces 503."""
    from app.core.exceptions import ServiceUnavailableException

    body = b'{"user_id":"supabase-uuid-abc"}'
    signature = _sign(body)

    with patch(
        "app.api.api_v1.endpoints.webhooks.auth.revoke_all_user_sessions",
        new=AsyncMock(side_effect=ServiceUnavailableException(detail="boom")),
    ), patch(
        "app.api.api_v1.endpoints.webhooks.auth._webhook_limiter.check_rate_limit",
        new=AsyncMock(return_value=True),
    ):
        transport = ASGITransport(app=app_with_secret)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            response = await ac.post(
                WEBHOOK_PATH,
                content=body,
                headers={
                    "Content-Type": "application/json",
                    "X-Supabase-Signature": signature,
                },
            )

    assert response.status_code == 503, response.text
