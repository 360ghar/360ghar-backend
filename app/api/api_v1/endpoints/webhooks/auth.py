"""Supabase auth webhooks.

Currently supports ``POST /api/v1/webhooks/auth/password-changed`` which is
fired by Supabase GoTrue after a user changes their password.  The webhook
revokes all of the user's active sessions so that stolen/old JWTs stop working
immediately (the backend otherwise cannot invalidate Supabase-issued tokens).

Security:
    * HMAC-SHA256 signature verification of the raw body via the
      ``X-Supabase-Signature`` header (constant-time compare).
    * Per-IP rate limiting (30 calls / 60 s).
"""

from __future__ import annotations

import base64
import hashlib
import hmac

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field

from app.config import settings
from app.core.exceptions import RateLimitException
from app.core.logging import get_logger
from app.middleware.rate_limit import EndpointRateLimiter
from app.services.auth.session_revocation import revoke_all_user_sessions

logger = get_logger(__name__)

router = APIRouter(prefix="/webhooks/auth", tags=["webhooks"])

# Per-IP guard: webhook senders should rarely fire, but a misconfigured loop
# could hammer the endpoint. 30/min matches the documented Supabase retry budget.
_webhook_limiter = EndpointRateLimiter(calls=30, period=60)


class PasswordChangedPayload(BaseModel):
    """Body sent by the Supabase password-changed webhook."""

    user_id: str = Field(..., min_length=1, description="Supabase auth user UUID")


def _verify_signature(raw_body: bytes, signature: str | None) -> bool:
    """Constant-time HMAC-SHA256 verification of the raw request body.

    The expected digest encoding is controlled by
    ``SUPABASE_WEBHOOK_SIGNATURE_ENCODING`` ("hex" by default, or "base64").
    """
    secret = settings.SUPABASE_WEBHOOK_SECRET
    if not secret:
        # Webhook secret not configured — refuse to process.
        return False
    if not signature:
        return False
    digest = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256)
    encoding = settings.SUPABASE_WEBHOOK_SIGNATURE_ENCODING.lower()
    if encoding == "base64":
        expected = base64.b64encode(digest.digest()).decode("ascii")
    else:
        expected = digest.hexdigest()
    return hmac.compare_digest(expected, signature)


@router.post(
    "/password-changed",
    status_code=status.HTTP_200_OK,
    summary="Supabase webhook: invalidate sessions after a password change",
)
async def password_changed_webhook(
    request: Request,
    payload: PasswordChangedPayload,
) -> dict[str, str]:
    """Revoke all Supabase sessions for the user whose password just changed.

    Headers:
        X-Supabase-Signature: hex HMAC-SHA256 of the raw body using
            ``SUPABASE_WEBHOOK_SECRET``.
    """
    # Per-IP rate limit (manual call to preserve the FastAPI signature).
    client_id = _webhook_limiter.get_client_id(request)
    endpoint = f"{request.method}:{request.url.path}"
    if not await _webhook_limiter.check_rate_limit(client_id, endpoint):
        raise RateLimitException(detail="Too many requests; please slow down")

    # Signature verification must use the raw body (before FastAPI parsing).
    raw_body = await request.body()
    signature = request.headers.get("X-Supabase-Signature")
    if not _verify_signature(raw_body, signature):
        logger.warning(
            "password-changed webhook: rejected invalid/missing signature for user_id=%s",
            payload.user_id,
        )
        raise HTTPException(status_code=401, detail="Invalid or missing signature")

    logger.info(
        "password-changed webhook received, revoking sessions for user_id=%s",
        payload.user_id,
    )
    await revoke_all_user_sessions(payload.user_id)
    return {"status": "revoked", "user_id": payload.user_id}
