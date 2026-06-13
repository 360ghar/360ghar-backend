"""Auth/onboarding support endpoints.

The backend does NOT own login/refresh/logout (clients use the Supabase SDK
directly). These endpoints only MIRROR state and drive the client login
state-machine:

  - POST /auth/identifier-status  (public, rate-limited)
  - POST /auth/last-method        (auth required)
  - POST /auth/link-identity      (auth required)
  - GET  /auth/config             (public)
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.api_v1.dependencies.auth import get_current_active_user
from app.config import settings
from app.core.auth import AuthFailureReason, _is_failure, admin_link_identity
from app.core.database import get_db
from app.core.exceptions import BadRequestException, RateLimitException, ServiceUnavailableException
from app.core.logging import get_logger
from app.middleware.rate_limit import EndpointRateLimiter
from app.models.enums import AuthMethod
from app.models.users import User
from app.services.user import get_identifier_status, set_last_auth_method

logger = get_logger(__name__)

router = APIRouter()

# Per-IP guard for the public identifier-status probe. Reuses the project's
# EndpointRateLimiter (cache-backed, sliding window).
_identifier_status_limiter = EndpointRateLimiter(calls=30, period=60)


# ── Schemas ──────────────────────────────────────────────────────────────────


class IdentifierStatusRequest(BaseModel):
    identifier: str = Field(..., min_length=1, max_length=320)


class IdentifierStatusResponse(BaseModel):
    exists: bool
    verified: bool
    has_password: bool
    channel: str  # "email" | "phone"
    next_step: str  # "password" | "otp"


class LastMethodRequest(BaseModel):
    method: AuthMethod


class LinkIdentityRequest(BaseModel):
    provider: str = Field(..., min_length=1)
    id_token: str = Field(..., min_length=1)


class LinkIdentityResponse(BaseModel):
    linked: bool


class AuthConfigResponse(BaseModel):
    google_web_client_id: str | None = None
    google_ios_client_id: str | None = None
    google_android_client_id: str | None = None


# ── Endpoints ────────────────────────────────────────────────────────────────


@router.post(
    "/identifier-status",
    response_model=IdentifierStatusResponse,
    summary="Probe the auth status of an email/phone (drives client login flow)",
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
    client_id = _identifier_status_limiter.get_client_id(request)
    endpoint = f"{request.method}:{request.url.path}"
    if not await _identifier_status_limiter.check_rate_limit(client_id, endpoint):
        raise RateLimitException(detail="Too many requests; please slow down")

    identifier = body.identifier.strip()
    status_data = await get_identifier_status(db, identifier)
    return IdentifierStatusResponse(**status_data)


@router.post(
    "/last-method",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Record the last authentication method used by the current user",
)
async def last_method(
    body: LastMethodRequest,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """AUTH required. Persist ``method`` on the current user."""
    await set_last_auth_method(db, current_user, body.method)


@router.post(
    "/link-identity",
    response_model=LinkIdentityResponse,
    summary="Link an OAuth identity to the current Supabase user",
)
async def link_identity(
    body: LinkIdentityRequest,
    current_user: User = Depends(get_current_active_user),
) -> LinkIdentityResponse:
    """AUTH required. Wrap the GoTrue Admin identity-linking call."""
    linked = await admin_link_identity(
        current_user.supabase_user_id,
        body.provider,
        body.id_token,
    )
    if _is_failure(linked):
        if linked["reason"] == AuthFailureReason.PROVIDER_UNREACHABLE.value:
            # Transient provider outage → advise the client to retry.
            raise ServiceUnavailableException(
                detail="Identity provider is temporarily unreachable, please retry",
                headers={"Retry-After": "30"},
            )
        raise BadRequestException(detail="Failed to link identity")
    if not linked:
        raise BadRequestException(detail="Failed to link identity")
    return LinkIdentityResponse(linked=True)


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
