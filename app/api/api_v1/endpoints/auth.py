"""Auth/onboarding support endpoints.

The backend does NOT own login/refresh/logout (clients use the Supabase SDK
directly). These endpoints only MIRROR state and drive the client login
state-machine:

  - POST /auth/identifier-status  (public, rate-limited)
  - POST /auth/last-method        (auth required)
  - POST /auth/delete-account     (auth required)
  - GET  /auth/config             (public)
"""

from __future__ import annotations

import hashlib
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.api_v1.dependencies.auth import get_current_active_user
from app.config import settings
from app.core.database import get_db
from app.core.exceptions import (
    BadRequestException,
    BaseAPIException,
    RateLimitException,
)
from app.core.logging import get_logger
from app.middleware.rate_limit import EndpointRateLimiter
from app.models.enums import AuthMethod
from app.models.users import User
from app.schemas.base import WriteModel
from app.services.user import delete_user_account, get_identifier_status, set_last_auth_method

logger = get_logger(__name__)

router = APIRouter()

# Per-IP and per-identifier guards for the public identifier-status probe.
_identifier_status_ip_limiter = EndpointRateLimiter(calls=10, period=60)
_identifier_status_identifier_limiter = EndpointRateLimiter(calls=5, period=3600)
_auth_mutation_limiter = EndpointRateLimiter(calls=30, period=60)


# ── Schemas ──────────────────────────────────────────────────────────────────


class IdentifierStatusRequest(BaseModel):
    identifier: str = Field(..., min_length=1, max_length=320)


class IdentifierStatusResponse(BaseModel):
    exists: bool
    verified: bool
    has_password: bool
    channel: Literal["email", "phone"]
    next_step: Literal["password", "otp"]


class LastMethodRequest(WriteModel):
    method: AuthMethod


class DeleteAccountRequest(WriteModel):
    confirm: bool = Field(
        ...,
        description="Must be true to permanently delete the authenticated account.",
    )


class AuthConfigResponse(BaseModel):
    google_web_client_id: str | None = None
    google_ios_client_id: str | None = None
    google_android_client_id: str | None = None


# ── Endpoints ────────────────────────────────────────────────────────────────


@router.post(
    "/identifier-status",
    response_model=IdentifierStatusResponse,
    summary="Probe the auth status of an email/phone (drives client login flow)",
    openapi_extra={
        "requestBody": {
            "content": {
                "application/json": {
                    "examples": {
                        "email": {"value": {"identifier": "user@example.com"}},
                        "phone": {"value": {"identifier": "+919876543210"}},
                    }
                }
            }
        }
    },
)
async def identifier_status(
    request: Request,
    body: IdentifierStatusRequest,
    db: AsyncSession = Depends(get_db),
) -> IdentifierStatusResponse:
    """PUBLIC. Return a NEUTRAL status for the given identifier.

    Rate-limited per-IP. Detects channel (``'@'`` → email, else phone), looks
    the identifier up directly in Supabase ``auth.users``, and computes
    ``next_step``: ``"password"`` iff the identifier exists, is verified, and
    has a password credential (``encrypted_password`` present); otherwise
    ``"otp"``.
    """
    endpoint = f"{request.method}:{request.url.path}"
    client_id = _identifier_status_ip_limiter.get_client_id(request)
    if not await _identifier_status_ip_limiter.check_rate_limit(client_id, endpoint):
        raise RateLimitException(detail="Too many requests; please slow down")

    identifier = body.identifier.strip()
    identifier_hash = hashlib.sha256(identifier.lower().encode()).hexdigest()
    identifier_client = f"identifier:{identifier_hash}"
    if not await _identifier_status_identifier_limiter.check_rate_limit(
        identifier_client, endpoint
    ):
        raise RateLimitException(
            detail="Too many attempts for this identifier; please try again later"
        )
    status_data = await get_identifier_status(db, identifier)
    return IdentifierStatusResponse(**status_data)


@router.post(
    "/last-method",
    status_code=204,
    summary="Record the last authentication method used by the current user",
)
async def last_method(
    request: Request,
    body: LastMethodRequest,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """AUTH required. Persist ``method`` on the current user. Returns 204 No Content."""
    endpoint = f"{request.method}:{request.url.path}"
    client_id = _auth_mutation_limiter.get_client_id(request)
    if not await _auth_mutation_limiter.check_rate_limit(client_id, endpoint):
        raise RateLimitException(detail="Too many requests; please slow down")
    await set_last_auth_method(db, current_user, body.method)
    return Response(status_code=204)


@router.get(
    "/config",
    response_model=AuthConfigResponse,
    summary="Public auth configuration (Google client IDs)",
)
async def auth_config() -> AuthConfigResponse:
    """PUBLIC. Return Google OAuth client IDs (any may be null)."""
    return AuthConfigResponse(
        google_web_client_id=settings.GOOGLE_WEB_CLIENT_ID,
        google_ios_client_id=settings.GOOGLE_IOS_CLIENT_ID,
        google_android_client_id=settings.GOOGLE_ANDROID_CLIENT_ID,
    )


@router.post(
    "/delete-account",
    status_code=204,
    summary="Permanently delete the current user's account",
)
async def delete_account(
    request: Request,
    body: DeleteAccountRequest,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """AUTH required. Permanently delete the caller's own account.

    Hard-deletes the Supabase Auth user (revoking all sessions) and
    anonymizes + soft-deletes the local record. App Store Guideline
    5.1.1(v) compliance: the account becomes permanently unusable.
    Returns 204 No Content. The canonical deletion route is ``DELETE /users/me``
    (also 204). Clients move to it, then this route is removed.
    """
    if not body.confirm:
        raise BadRequestException(detail="Account deletion requires confirm: true")
    endpoint = f"{request.method}:{request.url.path}"
    client_id = _auth_mutation_limiter.get_client_id(request)
    if not await _auth_mutation_limiter.check_rate_limit(client_id, endpoint):
        raise RateLimitException(detail="Too many requests; please slow down")
    try:
        await delete_user_account(db, current_user)
    except (BaseAPIException, HTTPException):
        raise
    except Exception as exc:
        logger.error(
            "Unexpected delete account failure for user %s: %s",
            current_user.id,
            exc,
            exc_info=True,
        )
        raise HTTPException(
            status_code=500,
            detail="Internal server error. Please try again later.",
        ) from None
    return Response(status_code=204)
