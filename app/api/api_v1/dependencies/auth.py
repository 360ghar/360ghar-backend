from __future__ import annotations

from typing import Any

import sentry_sdk
from fastapi import Depends, Header, HTTPException, Query, Request, status
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthFailureReason, _is_failure, verify_supabase_token
from app.core.database import get_bg_session_factory, get_db
from app.core.db_resilience import (
    extract_db_error_code,
    is_statement_timeout,
    is_transient_db_error,
)
from app.core.logging import get_logger
from app.models.enums import UserRole
from app.models.users import User
from app.services.auth_user_cache import (
    AuthUserSnapshot,
    cache_auth_user,
    get_cached_auth_user,
    snapshot_from_user,
)
from app.services.user import get_or_create_user_from_supabase

logger = get_logger(__name__)

_RETRY_AFTER_SECONDS = "5"


def _safe_sentry_field(value: Any) -> str | None:
    """Serialize a user field for Sentry; drop mocks / non-scalars."""
    if value is None:
        return None
    type_name = type(value).__name__
    if type_name in {"MagicMock", "AsyncMock", "Mock", "NonCallableMagicMock"}:
        return None
    text = str(value)
    if "MagicMock" in text or "AsyncMock" in text:
        return None
    return text


def _set_sentry_user(user: Any) -> None:
    sentry_sdk.set_user({
        "id": _safe_sentry_field(getattr(user, "id", None)),
        "email": _safe_sentry_field(getattr(user, "email", None)),
        "username": _safe_sentry_field(getattr(user, "phone", None)),
    })


def _eager_load_user_columns(user: User) -> None:
    """Load all column attrs so they remain usable after session invalidate.

    ``execute_with_transient_retry`` can invalidate the request session and
    detach ORM instances. Loaded scalar columns stay readable; unloaded ones
    raise ``DetachedInstanceError`` on access.
    """
    try:
        state = sa_inspect(user)
    except Exception:  # noqa: BLE001
        return
    for attr in state.mapper.column_attrs:
        try:
            getattr(user, attr.key)
        except Exception:  # noqa: BLE001
            continue


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


def _auth_db_unavailable_response(exc: Exception) -> HTTPException:
    """Build a 503 response for transient local auth-sync database failures."""
    error_code = extract_db_error_code(exc) or (
        "STATEMENT_TIMEOUT" if is_statement_timeout(exc) else "AUTH_DB_UNAVAILABLE"
    )
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail={
            "code": "AUTH_DB_UNAVAILABLE",
            "message": "Authentication data is temporarily unavailable, please retry",
            "details": {"error_code": error_code},
        },
        headers={"Retry-After": _RETRY_AFTER_SECONDS},
    )


async def _rollback_optional_auth(db: AsyncSession) -> None:
    """Clear a failed optional-auth transaction before public endpoint work continues."""
    try:
        await db.rollback()
    except Exception as rollback_exc:  # noqa: BLE001
        logger.warning("Optional auth rollback failed: %s", rollback_exc)
    # Do not re-open a transaction with SET LOCAL here — connection-level
    # statement_timeout (libpq options) still applies, and starting a new
    # idle transaction would pin a Supavisor backend until the request ends.


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
        # Touch all column attrs before commit so a later session invalidate
        # (transient retry) does not force a refresh that raises DetachedInstanceError.
        _eager_load_user_columns(db_user)
        # Auth sync uses a transaction-scoped advisory lock. It is independent
        # from endpoint business writes, so release it before endpoint logic runs.
        # Commit ends the txn so Supavisor can free the backend until the next
        # query; connection-level statement_timeout still applies.
        await db.commit()
        request.state.user_id = getattr(db_user, "id", None)
        # Store raw Supabase user data so endpoints that need identity
        # metadata (e.g. GET /users/me/identities) can access it without
        # a second round-trip.
        request.state.supabase_user_data = supabase_user_data
        _set_sentry_user(db_user)
        logger.debug("User authenticated successfully", extra={"user_id": getattr(db_user, "id", None)})
        return db_user
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        if is_transient_db_error(exc) or is_statement_timeout(exc):
            logger.warning(
                "Authentication DB sync temporarily unavailable: %s",
                exc,
                exc_info=True,
                extra={
                    "reason": "authentication_db_unavailable",
                    "error_type": type(exc).__name__,
                },
            )
            raise _auth_db_unavailable_response(exc) from exc
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


async def get_current_cached_active_user(
    request: Request,
    authorization: str | None = Header(None),
    db: AsyncSession = Depends(get_db),
) -> AuthUserSnapshot:
    """Resolve active user through a short-lived local auth snapshot cache."""
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
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={
                    "code": "TOKEN_INVALID",
                    "message": "Invalid or expired token",
                },
            )

        supabase_user_id = str(supabase_user_data.get("id") or "")
        if supabase_user_id:
            cached_user = await get_cached_auth_user(supabase_user_id)
            if cached_user is not None:
                if not cached_user.is_active:
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail={
                            "code": "USER_INACTIVE",
                            "message": "Inactive user",
                        },
                    )
                request.state.user_id = cached_user.id
                request.state.supabase_user_data = supabase_user_data
                _set_sentry_user(cached_user)
                return cached_user

        db_user = await get_or_create_user_from_supabase(db, supabase_user_data)
        _eager_load_user_columns(db_user)
        await db.commit()
        snapshot = snapshot_from_user(db_user)
        await cache_auth_user(snapshot)

        if not snapshot.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "code": "USER_INACTIVE",
                    "message": "Inactive user",
                },
            )
        request.state.user_id = snapshot.id
        request.state.supabase_user_data = supabase_user_data
        _set_sentry_user(snapshot)
        return snapshot
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        if is_transient_db_error(exc) or is_statement_timeout(exc):
            logger.warning(
                "Cached authentication DB sync temporarily unavailable: %s",
                exc,
                exc_info=True,
                extra={
                    "reason": "authentication_db_unavailable",
                    "error_type": type(exc).__name__,
                },
            )
            raise _auth_db_unavailable_response(exc) from exc
        logger.error(
            "Cached authentication error: %s",
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
                _eager_load_user_columns(db_user)
                db.expunge(db_user)
                await db.commit()
            except Exception:
                await db.rollback()
                raise
        request.state.user_id = getattr(db_user, "id", None)
        _set_sentry_user(db_user)
        logger.debug("SSE user authenticated successfully", extra={"user_id": getattr(db_user, "id", None)})
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        if is_transient_db_error(exc) or is_statement_timeout(exc):
            logger.warning(
                "SSE authentication DB sync temporarily unavailable: %s",
                exc,
                exc_info=True,
                extra={
                    "reason": "authentication_db_unavailable",
                    "error_type": type(exc).__name__,
                },
            )
            raise _auth_db_unavailable_response(exc) from exc
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
        _eager_load_user_columns(db_user)
        await db.commit()
        request.state.user_id = getattr(db_user, "id", None)
        _set_sentry_user(db_user)
        return db_user
    except Exception:
        logger.warning("Optional auth resolution failed", exc_info=True)
        await _rollback_optional_auth(db)
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
