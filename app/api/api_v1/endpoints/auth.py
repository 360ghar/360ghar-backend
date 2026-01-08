import re
import time
from typing import Literal, Optional

import anyio
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, EmailStr, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import (
    admin_find_user_by_phone,
    get_supabase_auth_client,
    get_supabase_service_client,
    verify_supabase_token,
)
from app.core.cache import get_cache_manager
from app.core.database import get_db
from app.core.logging import get_logger
from app.schemas.user import UserCreate, UserLogin
from app.services.user import get_or_create_user_from_supabase

router = APIRouter()
logger = get_logger(__name__)

# E.164 phone format regex (e.g., +919876543210)
E164_PHONE_PATTERN = re.compile(r"^\+[1-9]\d{6,14}$")

# OTP rate limit settings
OTP_RATE_LIMIT_CALLS = 5  # max OTP requests
OTP_RATE_LIMIT_PERIOD = 300  # per 5 minutes


def _validate_phone_format(phone: str) -> str:
    """Validate and normalize phone to E.164 format."""
    # Remove any whitespace
    phone = phone.strip().replace(" ", "").replace("-", "")
    if not E164_PHONE_PATTERN.match(phone):
        raise ValueError(
            "Phone must be in E.164 format (e.g., +919876543210)"
        )
    return phone


def _extract_bearer_token(authorization: str | None) -> str:
    """Extract bearer token from Authorization header."""
    if not authorization:
        raise HTTPException(
            status_code=401,
            detail={
                "code": "AUTH_HEADER_MISSING",
                "message": "Authorization header missing",
            },
        )

    try:
        scheme, token = authorization.split()
    except ValueError as exc:
        raise HTTPException(
            status_code=401,
            detail={
                "code": "INVALID_AUTH_HEADER",
                "message": "Invalid authorization header format",
            },
        ) from exc

    if scheme.lower() != "bearer":
        raise HTTPException(
            status_code=401,
            detail={
                "code": "INVALID_AUTH_SCHEME",
                "message": "Invalid authentication scheme. Use Bearer.",
            },
        )

    return token


async def _check_otp_rate_limit(phone: str, request: Request) -> None:
    """Check per-phone rate limit for OTP requests."""
    # Get client IP for additional rate limiting
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        client_ip = forwarded.split(",")[0].strip()
    else:
        client_ip = request.client.host if request.client else "unknown"

    # Rate limit by phone number
    phone_key = f"otp_rate_limit:phone:{phone}"
    # Rate limit by IP (to prevent enumeration attacks)
    ip_key = f"otp_rate_limit:ip:{client_ip}"

    now = int(time.time())
    window_start = now - OTP_RATE_LIMIT_PERIOD

    for key in [phone_key, ip_key]:
        cache = get_cache_manager()
        if cache.is_available():
            history = await cache.get(key) or []
            history = [ts for ts in history if ts > window_start]

            if len(history) >= OTP_RATE_LIMIT_CALLS:
                logger.warning(
                    f"OTP rate limit exceeded for {key}",
                    extra={"phone": phone, "ip": client_ip},
                )
                raise HTTPException(
                    status_code=429,
                    detail={
                        "code": "RATE_LIMITED",
                        "message": f"Too many OTP requests. Please try again in {OTP_RATE_LIMIT_PERIOD // 60} minutes.",
                    },
                    headers={"Retry-After": str(OTP_RATE_LIMIT_PERIOD)},
                )

            history.append(now)
            await cache.set(key, history, ttl=OTP_RATE_LIMIT_PERIOD)

@router.post("/login/")
async def login(user_login: UserLogin, db: AsyncSession = Depends(get_db)):
    """Login with Supabase Auth using phone + password"""
    try:
        supabase = get_supabase_auth_client()
        data = await anyio.to_thread.run_sync(
            lambda: supabase.auth.sign_in_with_password({
                "phone": user_login.phone,
                "password": user_login.password,
            })
        )

        # If the response lacks a usable session/token, try to classify the cause
        if not getattr(data, "session", None) or not getattr(data.session, "access_token", None):
            # Attempt admin lookup to distinguish not found vs wrong password
            supa_user = await admin_find_user_by_phone(user_login.phone)
            if not supa_user:
                logger.warning("Login failed: user not found (admin lookup)", extra={"phone": user_login.phone})
                raise HTTPException(
                    status_code=404,
                    detail={
                        "code": "USER_NOT_FOUND",
                        "message": "User with this phone does not exist",
                    },
                )
            logger.warning("Login failed: invalid credentials", extra={"phone": user_login.phone})
            raise HTTPException(
                status_code=401,
                detail={
                    "code": "INVALID_CREDENTIALS",
                    "message": "Invalid phone or password",
                },
            )

        # Verify token and ensure account is verified where applicable
        supabase_user_data = await verify_supabase_token(data.session.access_token)
        if not supabase_user_data:
            raise HTTPException(
                status_code=401,
                detail={
                    "code": "TOKEN_INVALID",
                    "message": "Invalid or expired token",
                },
            )

        if not supabase_user_data.get("email_verified", False):
            logger.warning("Login blocked: unverified account", extra={"phone": user_login.phone})
            raise HTTPException(
                status_code=403,
                detail={
                    "code": "UNVERIFIED_ACCOUNT",
                    "message": "Please verify your email or phone before logging in",
                },
            )

        db_user = await get_or_create_user_from_supabase(db, supabase_user_data)

        return {
            "access_token": data.session.access_token,
            "refresh_token": data.session.refresh_token,
            "expires_in": data.session.expires_in,
            "token_type": "bearer",
            "user": db_user,
        }
    except HTTPException:
        # Re-raise structured exceptions
        raise
    except Exception as e:
        # Heuristic classification for common Supabase auth errors
        msg = str(e).lower()

        if any(k in msg for k in ["confirm", "verified", "verification"]):
            logger.error(f"Authentication failed (unverified): {e}", extra={"phone": user_login.phone})
            raise HTTPException(
                status_code=403,
                detail={
                    "code": "UNVERIFIED_ACCOUNT",
                    "message": "Please verify your email or phone before logging in",
                },
            )
        if any(k in msg for k in ["too many", "rate", "rate limit", "throttle"]):
            logger.error(f"Authentication rate limited: {e}", extra={"phone": user_login.phone})
            raise HTTPException(
                status_code=429,
                detail={
                    "code": "RATE_LIMITED",
                    "message": "Too many attempts. Please try again later",
                },
            )

        # Try admin lookup as a fallback to classify not found vs invalid password
        try:
            supa_user = await admin_find_user_by_phone(user_login.phone)
        except Exception:
            supa_user = None

        if not supa_user:
            logger.error(f"Authentication failed: user not found ({e})", extra={"phone": user_login.phone})
            raise HTTPException(
                status_code=404,
                detail={
                    "code": "USER_NOT_FOUND",
                    "message": "User with this phone does not exist",
                },
            )

        logger.error(f"Authentication failed: invalid credentials ({e})", extra={"phone": user_login.phone})
        raise HTTPException(
            status_code=401,
            detail={
                "code": "INVALID_CREDENTIALS",
                "message": "Invalid phone or password",
            },
        )

@router.post("/register/")
async def register(user_data: UserCreate, db: AsyncSession = Depends(get_db)):
    """Register via Supabase Auth using phone as primary identifier"""
    try:
        supabase = get_supabase_auth_client()
        data = await anyio.to_thread.run_sync(
            lambda: supabase.auth.sign_up({
                "phone": user_data.phone,
                "password": user_data.password,
                "options": {
                    "data": {
                        "full_name": user_data.full_name,
                        "email": user_data.email
                    }
                }
            })
        )

        if data.user:
            supabase_user_data = {
                "id": data.user.id,
                "phone": data.user.phone,
                "email": data.user.email,
                "user_metadata": data.user.user_metadata or {}
            }

            db_user = await get_or_create_user_from_supabase(db, supabase_user_data)

            return {
                "message": "User registered successfully",
                "user": db_user,
                "access_token": data.session.access_token if data.session else None,
                "refresh_token": data.session.refresh_token if data.session else None,
                "expires_in": data.session.expires_in if data.session else None,
                "token_type": "bearer" if data.session else None,
            }
        else:
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "REGISTRATION_FAILED",
                    "message": "Registration failed",
                },
            )
    except HTTPException:
        # Re-raise structured exceptions
        raise
    except Exception as e:
        # Heuristic: classify common Supabase registration errors
        msg = str(e).lower()

        if "already" in msg or "exists" in msg or "duplicate" in msg:
            logger.warning(f"Registration failed: user exists ({e})", extra={"phone": user_data.phone})
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "USER_ALREADY_EXISTS",
                    "message": "A user with this phone number already exists",
                },
            )

        if "password" in msg and ("weak" in msg or "short" in msg or "length" in msg):
            logger.warning(f"Registration failed: weak password ({e})", extra={"phone": user_data.phone})
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "WEAK_PASSWORD",
                    "message": "Password does not meet security requirements",
                },
            )

        if any(k in msg for k in ["too many", "rate", "rate limit", "throttle"]):
            logger.error(f"Registration rate limited: {e}", extra={"phone": user_data.phone})
            raise HTTPException(
                status_code=429,
                detail={
                    "code": "RATE_LIMITED",
                    "message": "Too many attempts. Please try again later",
                },
            )

        # Generic fallback - do NOT expose internal error details
        logger.error(f"Registration failed: {e}", extra={"phone": user_data.phone})
        raise HTTPException(
            status_code=400,
            detail={
                "code": "REGISTRATION_FAILED",
                "message": "Registration failed. Please check your information and try again.",
            },
        )


class OTPRequest(BaseModel):
    phone: str

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, v: str) -> str:
        return _validate_phone_format(v)


@router.post("/otp/request")
async def request_otp(payload: OTPRequest, request: Request):
    """Request an OTP for phone login (Supabase passwordless OTP)."""
    # Check rate limit before processing
    await _check_otp_rate_limit(payload.phone, request)

    try:
        supabase = get_supabase_auth_client()
        await anyio.to_thread.run_sync(
            lambda: supabase.auth.sign_in_with_otp({"phone": payload.phone})
        )
        return {"message": "OTP sent"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"OTP request failed: {e}", extra={"phone": payload.phone})
        raise HTTPException(
            status_code=400,
            detail={
                "code": "OTP_REQUEST_FAILED",
                "message": "Failed to send OTP",
            },
        )


class OTPVerify(BaseModel):
    phone: str
    token: str
    type: Literal["sms", "phone_change"] = "sms"

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, v: str) -> str:
        return _validate_phone_format(v)


@router.post("/otp/verify")
async def verify_otp(payload: OTPVerify, db: AsyncSession = Depends(get_db)):
    """Verify an OTP and return a bearer token + local user record."""
    try:
        supabase = get_supabase_auth_client()
        auth_resp = await anyio.to_thread.run_sync(
            lambda: supabase.auth.verify_otp(
                {
                    "phone": payload.phone,
                    "token": payload.token,
                    "type": payload.type,
                }
            )
        )

        session = getattr(auth_resp, "session", None)
        access_token = getattr(session, "access_token", None) if session else None
        if not access_token:
            raise HTTPException(
                status_code=401,
                detail={
                    "code": "OTP_INVALID",
                    "message": "Invalid or expired OTP",
                },
            )

        supabase_user_data = await verify_supabase_token(access_token)
        if not supabase_user_data:
            raise HTTPException(
                status_code=401,
                detail={
                    "code": "TOKEN_INVALID",
                    "message": "Invalid or expired token",
                },
            )

        db_user = await get_or_create_user_from_supabase(db, supabase_user_data)

        return {
            "access_token": access_token,
            "refresh_token": session.refresh_token if session else None,
            "expires_in": session.expires_in if session else None,
            "token_type": "bearer",
            "user": db_user,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"OTP verify failed: {e}", extra={"phone": payload.phone})
        raise HTTPException(
            status_code=400,
            detail={
                "code": "OTP_VERIFY_FAILED",
                "message": "OTP verification failed",
            },
        )


class RefreshTokenRequest(BaseModel):
    refresh_token: str


@router.post("/refresh/")
async def refresh_token(payload: RefreshTokenRequest, db: AsyncSession = Depends(get_db)):
    """Refresh a Supabase session using a refresh token."""
    try:
        supabase = get_supabase_auth_client()
        auth_resp = await anyio.to_thread.run_sync(
            lambda: supabase.auth.refresh_session(payload.refresh_token)
        )

        session = getattr(auth_resp, "session", None)
        if not session or not getattr(session, "access_token", None):
            raise HTTPException(
                status_code=401,
                detail={
                    "code": "REFRESH_INVALID",
                    "message": "Invalid or expired refresh token",
                },
            )

        supabase_user_data = await verify_supabase_token(session.access_token)
        if not supabase_user_data:
            raise HTTPException(
                status_code=401,
                detail={
                    "code": "TOKEN_INVALID",
                    "message": "Invalid or expired token",
                },
            )

        db_user = await get_or_create_user_from_supabase(db, supabase_user_data)

        return {
            "access_token": session.access_token,
            "refresh_token": session.refresh_token,
            "expires_in": session.expires_in,
            "token_type": "bearer",
            "user": db_user,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Refresh token failed: {e}")
        raise HTTPException(
            status_code=400,
            detail={
                "code": "REFRESH_FAILED",
                "message": "Failed to refresh session",
            },
        )


class LogoutRequest(BaseModel):
    scope: Literal["global", "local", "others"] = "global"
    access_token: Optional[str] = None


@router.post("/logout/")
async def logout(
    payload: LogoutRequest | None = None,
    authorization: Optional[str] = Header(None),
):
    """Logout by revoking the refresh token(s) for the current session."""
    try:
        payload = payload or LogoutRequest()
        token = payload.access_token or _extract_bearer_token(authorization)
        supabase = get_supabase_service_client()
        await anyio.to_thread.run_sync(
            lambda: supabase.auth.admin.sign_out(token, payload.scope)
        )
        return {"message": "Logged out"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Logout failed: {e}")
        raise HTTPException(
            status_code=400,
            detail={
                "code": "LOGOUT_FAILED",
                "message": "Logout failed",
            },
        )


class ForgotPasswordRequest(BaseModel):
    email: Optional[EmailStr] = None
    phone: Optional[str] = None
    redirect_to: Optional[str] = None

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, v: Optional[str]) -> Optional[str]:
        if v:
            return _validate_phone_format(v)
        return v


@router.post("/forgot-password/")
async def forgot_password(payload: ForgotPasswordRequest, request: Request):
    """Trigger password recovery via email or OTP to phone."""
    if not payload.email and not payload.phone:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "MISSING_IDENTIFIER",
                "message": "Email or phone is required",
            },
        )

    try:
        supabase = get_supabase_auth_client()

        if payload.email:
            options = {"redirect_to": payload.redirect_to} if payload.redirect_to else None
            await anyio.to_thread.run_sync(
                lambda: supabase.auth.reset_password_for_email(payload.email, options)
            )
            return {"message": "Password reset email sent"}

        if payload.phone:
            await _check_otp_rate_limit(payload.phone, request)
            await anyio.to_thread.run_sync(
                lambda: supabase.auth.sign_in_with_otp({"phone": payload.phone})
            )
            return {"message": "OTP sent"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Password recovery failed: {e}")
        raise HTTPException(
            status_code=400,
            detail={
                "code": "PASSWORD_RESET_FAILED",
                "message": "Password recovery failed",
            },
        )


class VerifyRequest(BaseModel):
    token: str
    type: Literal["sms", "phone_change", "signup", "recovery", "email_change", "email"] = "sms"
    phone: Optional[str] = None
    email: Optional[EmailStr] = None

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, v: Optional[str]) -> Optional[str]:
        if v:
            return _validate_phone_format(v)
        return v


@router.post("/verify/")
async def verify_account(payload: VerifyRequest, db: AsyncSession = Depends(get_db)):
    """Verify OTP for email or phone and return a session."""
    if not payload.phone and not payload.email:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "MISSING_IDENTIFIER",
                "message": "Email or phone is required",
            },
        )

    try:
        supabase = get_supabase_auth_client()
        verify_payload: dict = {"token": payload.token, "type": payload.type}
        if payload.phone:
            verify_payload["phone"] = payload.phone
        if payload.email:
            verify_payload["email"] = payload.email

        auth_resp = await anyio.to_thread.run_sync(
            lambda: supabase.auth.verify_otp(verify_payload)
        )

        session = getattr(auth_resp, "session", None)
        access_token = getattr(session, "access_token", None) if session else None
        if not access_token:
            raise HTTPException(
                status_code=401,
                detail={
                    "code": "VERIFY_INVALID",
                    "message": "Invalid or expired verification token",
                },
            )

        supabase_user_data = await verify_supabase_token(access_token)
        if not supabase_user_data:
            raise HTTPException(
                status_code=401,
                detail={
                    "code": "TOKEN_INVALID",
                    "message": "Invalid or expired token",
                },
            )

        db_user = await get_or_create_user_from_supabase(db, supabase_user_data)

        return {
            "access_token": access_token,
            "refresh_token": session.refresh_token if session else None,
            "expires_in": session.expires_in if session else None,
            "token_type": "bearer",
            "user": db_user,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Verification failed: {e}")
        raise HTTPException(
            status_code=400,
            detail={
                "code": "VERIFY_FAILED",
                "message": "Verification failed",
            },
        )
