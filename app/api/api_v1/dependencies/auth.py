from __future__ import annotations

import sentry_sdk
from fastapi import Depends, Header, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthFailureReason, _is_failure, verify_supabase_token
from app.core.database import get_bg_session_factory, get_db
from app.core.logging import get_logger
from app.models.enums import UserRole
from app.models.users import User
from app.services.user import get_or_create_user_from_supabase

logger = get_logger(__name__)

_RETRY_AFTER_SECONDS = "5"


def _provider_unavailable_response() -> HTTPException:
    """Build a 503 response for an unreachable Supabase host.

    The token may be valid; the server just can't reach Supabase right
    now.  Returning 503 (instead of 401) lets the client distinguish
    a transient outage from a bad token.
    """
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail={
            "code": "AUTH_PROVIDER_UNREACHABLE",
            "message": "Authentication provider is temporarily unreachable, please retry",
        },
        headers={"Retry-After": _RETRY_AFTER_SECONDS},
    )


def _parse_bearer_token(authorization: str | None) -> str:
    if not authorization:
        logger.debug("Authorization header missing")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": "AUTH_HEADER_MISSING",
                "message": "Authorization header missing",
            },
        )

    try:
        scheme, token = authorization.split()
    except ValueError as exc:
        logger.warning(
            "Invalid authorization header format",
            extra={"reason": "invalid_header_format"},
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": "INVALID_AUTH_HEADER",
                "message": "Invalid authorization header format",
            },
        ) from exc

    if scheme.lower() != "bearer":
        logger.warning(
            "Invalid authentication scheme",
            extra={"reason": "invalid_scheme", "scheme": scheme},
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": "INVALID_AUTH_SCHEME",
                "message": "Invalid authentication scheme. Use Bearer.",
            },
        )

    return token


async def get_current_user(
    request: Request,
    authorization: str | None = Header(None),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Resolve the current user from the Authorization bearer token."""
    token = _parse_bearer_token(authorization)

    try:
        supabase_user_data = await verify_supabase_token(token)
        if _is_failure(supabase_user_data):
            token_suffix = token[-8:] if len(token) > 8 else token
            reason = supabase_user_data.get("reason")
            if reason == AuthFailureReason.PROVIDER_UNREACHABLE.value:
                logger.warning(
                    "Auth provider unreachable (suffix=%s): %s",
                    token_suffix,
                    supabase_user_data.get("error"),
                    extra={
                        "reason": "auth_provider_unreachable",
                        "token_suffix": token_suffix,
                    },
                )
                raise _provider_unavailable_response()
            logger.warning(
                "Auth provider error (suffix=%s): %s",
                token_suffix,
                supabase_user_data.get("error"),
                extra={"reason": "auth_provider_error", "token_suffix": token_suffix},
            )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={
                    "code": "TOKEN_INVALID",
                    "message": "Invalid or expired token",
                },
            )
        if not supabase_user_data:
            token_suffix = token[-8:] if len(token) > 8 else token
            logger.info(
                "Invalid or expired token (suffix=%s)",
                token_suffix,
                extra={"reason": "token_invalid_or_expired", "token_suffix": token_suffix},
            )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={
                    "code": "TOKEN_INVALID",
                    "message": "Invalid or expired token",
                },
            )

        db_user = await get_or_create_user_from_supabase(db, supabase_user_data)
        request.state.user_id = getattr(db_user, "id", None)
        # Store raw Supabase user data so endpoints that need identity
        # metadata (e.g. GET /users/me/identities) can access it without
        # a second round-trip.
        request.state.supabase_user_data = supabase_user_data
        sentry_sdk.set_user({
            "id": str(getattr(db_user, "id", None)),
            "email": getattr(db_user, "email", None),
            "username": getattr(db_user, "phone", None),
        })
        logger.debug("User authenticated successfully", extra={"user_id": getattr(db_user, "id", None)})
        return db_user
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "Authentication error: %s",
            exc,
            exc_info=True,
            extra={"reason": "authentication_exception", "error_type": type(exc).__name__},
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": "AUTHENTICATION_FAILED",
                "message": "Authentication failed",
            },
        ) from exc


async def get_current_active_user(
    current_user: User = Depends(get_current_user),
) -> User:
    """Return the current user only if active."""
    if not getattr(current_user, "is_active", False):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "USER_INACTIVE",
                "message": "Inactive user",
            },
        )
    return current_user


async def get_current_user_sse(
    request: Request,
    authorization: str | None = Header(None),
    token: str | None = Query(None),
) -> User:
    """Resolve the current user from Bearer header or ``?token=`` query param.

    Browser ``EventSource`` cannot set custom headers, so SSE consumers pass
    the access token as a query parameter instead.  This dependency checks the
    query param first and falls back to the standard ``Authorization`` header.

    Uses a short-lived background-pool session instead of ``Depends(get_db)``
    so the main connection pool is not exhausted by long-running SSE streams.
    The session is closed immediately after authentication completes.
    """
    resolved_token: str | None = token

    if not resolved_token:
        resolved_token = _parse_bearer_token(authorization)

    try:
        supabase_user_data = await verify_supabase_token(resolved_token)
        if _is_failure(supabase_user_data):
            token_suffix = resolved_token[-8:] if len(resolved_token) > 8 else resolved_token
            reason = supabase_user_data.get("reason")
            if reason == AuthFailureReason.PROVIDER_UNREACHABLE.value:
                logger.warning(
                    "SSE auth provider unreachable (suffix=%s): %s",
                    token_suffix,
                    supabase_user_data.get("error"),
                    extra={
                        "reason": "auth_provider_unreachable",
                        "token_suffix": token_suffix,
                    },
                )
                raise _provider_unavailable_response()
            logger.warning(
                "SSE auth provider error (suffix=%s): %s",
                token_suffix,
                supabase_user_data.get("error"),
                extra={"reason": "auth_provider_error", "token_suffix": token_suffix},
            )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={
                    "code": "TOKEN_INVALID",
                    "message": "Invalid or expired token",
                },
            )
        if not supabase_user_data:
            token_suffix = resolved_token[-8:] if len(resolved_token) > 8 else resolved_token
            logger.info(
                "Invalid or expired token (suffix=%s)",
                token_suffix,
                extra={"reason": "token_invalid_or_expired", "token_suffix": token_suffix},
            )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={
                    "code": "TOKEN_INVALID",
                    "message": "Invalid or expired token",
                },
            )

        session_factory = get_bg_session_factory()
        async with session_factory() as db:
            try:
                db_user = await get_or_create_user_from_supabase(db, supabase_user_data)
                db.expunge(db_user)
                await db.commit()
            except Exception:
                await db.rollback()
                raise
        request.state.user_id = getattr(db_user, "id", None)
        sentry_sdk.set_user({
            "id": str(getattr(db_user, "id", None)),
            "email": getattr(db_user, "email", None),
            "username": getattr(db_user, "phone", None),
        })
        logger.debug("SSE user authenticated successfully", extra={"user_id": getattr(db_user, "id", None)})
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "SSE authentication error: %s",
            exc,
            exc_info=True,
            extra={"reason": "authentication_exception", "error_type": type(exc).__name__},
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": "AUTHENTICATION_FAILED",
                "message": "Authentication failed",
            },
        ) from exc

    if not getattr(db_user, "is_active", False):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "USER_INACTIVE",
                "message": "Inactive user",
            },
        )
    return db_user


async def get_current_user_optional(
    request: Request,
    authorization: str | None = Header(None),
    db: AsyncSession = Depends(get_db),
) -> User | None:
    """Return the authenticated user if present; otherwise None."""
    if not authorization:
        return None

    try:
        token = _parse_bearer_token(authorization)

        supabase_user_data = await verify_supabase_token(token)
        if _is_failure(supabase_user_data):
            token_suffix = token[-8:] if len(token) > 8 else token
            reason = supabase_user_data.get("reason")
            if reason == AuthFailureReason.PROVIDER_UNREACHABLE.value:
                logger.warning(
                    "Optional auth provider unreachable (suffix=%s): %s",
                    token_suffix,
                    supabase_user_data.get("error"),
                    extra={
                        "reason": "auth_provider_unreachable",
                        "token_suffix": token_suffix,
                    },
                )
                return None
            logger.warning(
                "Optional auth provider error (suffix=%s)",
                token_suffix,
                extra={"reason": "auth_provider_error", "token_suffix": token_suffix},
            )
            return None
        if not supabase_user_data:
            return None

        db_user = await get_or_create_user_from_supabase(db, supabase_user_data)
        request.state.user_id = getattr(db_user, "id", None)
        sentry_sdk.set_user({
            "id": str(getattr(db_user, "id", None)),
            "email": getattr(db_user, "email", None),
            "username": getattr(db_user, "phone", None),
        })
        return db_user
    except Exception:
        logger.warning("Optional auth resolution failed", exc_info=True)
        return None


async def get_current_agent(
    current_user: User = Depends(get_current_active_user),
) -> User:
    """Ensure the current user has agent role."""
    if getattr(current_user, "role", None) != UserRole.agent:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "AGENT_REQUIRED",
                "message": "Agent privileges required",
            },
        )
    return current_user


async def get_current_admin(
    current_user: User = Depends(get_current_active_user),
) -> User:
    """Ensure the current user has admin role."""
    if getattr(current_user, "role", None) != UserRole.admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "ADMIN_REQUIRED",
                "message": "Admin privileges required",
            },
        )
    return current_user
