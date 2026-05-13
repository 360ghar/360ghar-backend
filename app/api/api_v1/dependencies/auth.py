from __future__ import annotations

import sentry_sdk
from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import verify_supabase_token
from app.core.database import get_db
from app.core.logging import get_logger
from app.models.enums import UserRole
from app.models.users import User
from app.services.user import get_or_create_user_from_supabase

logger = get_logger(__name__)


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
        if not supabase_user_data:
            token_suffix = token[-8:] if len(token) > 8 else token
            logger.warning(
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
