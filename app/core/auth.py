from __future__ import annotations

import socket
from enum import StrEnum
from typing import TYPE_CHECKING, Any

import httpcore
import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_fixed,
)

from app.config import settings
from app.core.http import get_supabase_auth_http_client
from app.core.jwt_verification import JWKSUnavailable, verify_jwt_locally
from app.core.logging import get_logger

if TYPE_CHECKING:
    # ``Client`` / ``ClientOptions`` are used only as type annotations. With
    # ``from __future__ import annotations`` they are lazy strings, so the
    # heavy ``supabase`` package does not need to load at import time.
    from supabase import Client, ClientOptions

logger = get_logger(__name__)


def create_client(*args: Any, **kwargs: Any) -> Client:
    """Lazily resolve ``supabase.create_client``.

    The ``supabase`` package (~25MB) is only needed when a Supabase client is
    first built at runtime, so we keep it off the app import path. Exposing
    this thin wrapper at module scope preserves the ``app.core.auth.create_client``
    seam that tests patch.
    """
    from supabase import create_client as _supabase_create_client

    return _supabase_create_client(*args, **kwargs)


SUPABASE_AUTH_TIMEOUT = 10.0
SUPABASE_DATA_TIMEOUT = 120.0

_RETRYABLE_NETWORK_ERRORS: tuple[type[BaseException], ...] = (
    httpx.ConnectError,
    httpx.ConnectTimeout,
    httpx.ReadTimeout,
    httpx.WriteTimeout,
    httpx.PoolTimeout,
    httpx.NetworkError,
    httpcore.ConnectError,
    httpcore.ConnectTimeout,
    httpcore.ReadTimeout,
    httpcore.NetworkError,
    socket.gaierror,
    socket.timeout,
    ConnectionResetError,
    ConnectionAbortedError,
)


def _retry_on_transient_network() -> Any:
    """Tenacity decorator: 2 attempts, 0.3 s flat wait on transient network errors."""
    return retry(
        retry=retry_if_exception_type(_RETRYABLE_NETWORK_ERRORS),
        wait=wait_fixed(0.3),
        stop=stop_after_attempt(2),
        reraise=True,
    )


class AuthFailureReason(StrEnum):
    """Why an auth/admin Supabase call failed.

    The dependency layer maps these to HTTP status codes so clients can
    distinguish a bad token (401) from a transient provider outage (503).
    """

    INVALID_TOKEN = "invalid_token"
    PROVIDER_UNREACHABLE = "provider_unreachable"
    PROVIDER_ERROR = "provider_error"


# Sentinel key used to mark a tagged failure result. Kept unlikely to
# collide with real Supabase /auth/v1/user payload keys.
_FAILURE_SENTINEL = "__auth_failure__"


def _is_failure(result: Any) -> bool:
    return isinstance(result, dict) and result.get(_FAILURE_SENTINEL) is True


def _make_failure(reason: AuthFailureReason, error: str) -> dict[str, Any]:
    return {
        _FAILURE_SENTINEL: True,
        "reason": reason.value,
        "error": error,
    }


class SupabaseClientManager:
    """Manages Supabase clients as singletons with environment-based configuration.

    The async HTTP client used for GoTrue REST calls (verify_token,
    admin user ops) is owned by ``app.core.http`` and accessed via
    :func:`get_supabase_auth_http_client`.  Only the synchronous
    ``supabase.Client`` wrappers (auth, postgrest) are managed here.
    """

    def __init__(self) -> None:
        self._auth_client: Client | None = None
        self._service_client: Client | None = None

    # -- Sync Supabase clients --------------------------------------------------

    def get_auth_client(self) -> Client:
        """Get Supabase client for authentication only."""
        if self._auth_client is None:
            key = settings.SUPABASE_CLIENT_KEY
            if not key:
                raise ValueError("Missing Supabase publishable key. Set SUPABASE_PUBLISHABLE_KEY.")
            # ``create_client`` resolves to the module-level lazy wrapper above,
            # which imports the heavy ``supabase`` package only on first use and
            # stays patchable as ``app.core.auth.create_client``.
            self._auth_client = create_client(
                settings.SUPABASE_URL,
                key,
                options=self._build_client_options(SUPABASE_AUTH_TIMEOUT),
            )
        return self._auth_client

    def get_service_client(self) -> Client:
        """Get Supabase client using service role key for server-side DB ops."""
        if self._service_client is None:
            self._service_client = create_client(
                settings.SUPABASE_URL,
                settings.SUPABASE_SECRET_KEY,
                options=self._build_client_options(SUPABASE_DATA_TIMEOUT),
            )
        return self._service_client

    # -- Lifecycle --------------------------------------------------------------

    async def close(self) -> None:
        """Release manager-owned sync clients. Call on app shutdown.

        The shared async HTTP client is owned by ``app.core.http`` and
        is closed there.
        """
        for client_attr in ("_auth_client", "_service_client"):
            client = getattr(self, client_attr, None)
            if client is None:
                continue
            for sub_attr in ("auth", "postgrest", "storage"):
                sub = getattr(client, sub_attr, None)
                if sub is not None:
                    session = getattr(sub, "session", None)
                    if session is not None and hasattr(session, "close"):
                        try:
                            session.close()
                        except Exception:
                            pass
            setattr(self, client_attr, None)

    # -- Auth operations --------------------------------------------------------

    def _admin_headers(self, *, json: bool = False) -> dict[str, str]:
        """Return GoTrue Admin API headers (service role key)."""
        h: dict[str, str] = {
            "apikey": settings.SUPABASE_SECRET_KEY,
            "Authorization": f"Bearer {settings.SUPABASE_SECRET_KEY}",
        }
        if json:
            h["Content-Type"] = "application/json"
        return h

    def _admin_url(self, path: str) -> str:
        """Build a GoTrue Admin API URL."""
        return f"{settings.SUPABASE_URL.rstrip('/')}/auth/v1{path}"

    async def _admin_find_user_by_field(self, field: str, value: str) -> dict[str, Any] | None:
        """Lookup a user via Supabase GoTrue Admin by a single field.

        Returns the user dict on success, ``None`` on a "not found" /
        invalid response, or a :func:`_make_failure` tagged dict on a
        transient network / DNS error so callers can distinguish a
        genuine "no such user" from an unreachable provider.
        """
        url = self._admin_url("/admin/users")
        params: dict[str, str | int] = {field: value, "per_page": 1}
        try:
            response = await self._get_with_retry(url, params=params)
        except _RETRYABLE_NETWORK_ERRORS as exc:
            logger.warning("Admin user lookup by %s unreachable: %s", field, exc)
            return _make_failure(AuthFailureReason.PROVIDER_UNREACHABLE, str(exc))
        except Exception as exc:  # noqa: BLE001
            logger.error("Admin user lookup by %s error: %s", field, exc)
            return _make_failure(AuthFailureReason.PROVIDER_ERROR, str(exc))

        if response.status_code == 200:
            data = response.json()
            users: list[dict[str, Any]] = []
            if isinstance(data, dict) and "users" in data:
                users = data.get("users") or []
            elif isinstance(data, list):
                users = data
            for user in users:
                if user.get(field) == value:
                    return {
                        "id": user.get("id"),
                        "email": user.get("email"),
                        "phone": user.get("phone"),
                        "user_metadata": user.get("user_metadata") or {},
                        "app_metadata": user.get("app_metadata") or {},
                        "email_confirmed_at": user.get("email_confirmed_at"),
                        "phone_confirmed_at": user.get("phone_confirmed_at"),
                    }
            return None
        if response.status_code == 404:
            return None
        logger.warning(
            "Admin user lookup by %s failed: %s %s",
            field,
            response.status_code,
            response.text[:200],
        )
        return None

    @_retry_on_transient_network()
    async def _get_with_retry(
        self, url: str, *, params: dict[str, Any] | None = None
    ) -> httpx.Response:
        """GET against the shared Supabase auth client with transient-error retry."""
        client = get_supabase_auth_http_client()
        return await client.get(url, headers=self._admin_headers(), params=params)

    @_retry_on_transient_network()
    async def _post_with_retry(self, url: str, *, json: dict[str, Any]) -> httpx.Response:
        """POST against the shared Supabase auth client with transient-error retry."""
        client = get_supabase_auth_http_client()
        return await client.post(url, headers=self._admin_headers(json=True), json=json)

    @_retry_on_transient_network()
    async def _delete_with_retry(self, url: str) -> httpx.Response:
        """DELETE against the shared Supabase auth client with transient-error retry."""
        client = get_supabase_auth_http_client()
        return await client.delete(url, headers=self._admin_headers())

    async def verify_token(self, token: str) -> dict[str, Any] | None:
        """Verify Supabase JWT.

        Tries local JWKS-based verification first (signature + iss/aud/exp).
        Falls back to Supabase Auth ``GET /auth/v1/user`` introspection when
        the JWKS is unavailable. Returns the user dict on success, ``None``
        on an invalid/expired token, or a tagged failure dict on a transient
        provider error.
        """
        # ── Fast path: local JWT verification ───────────────────────────────
        try:
            claims = await verify_jwt_locally(token)
        except JWKSUnavailable as exc:
            logger.debug("JWKS unavailable (%s); falling back to introspection", exc)
            claims = None  # fall through to introspection
        except Exception as exc:  # noqa: BLE001 — never crash auth on JWT util
            logger.warning("Local JWT verification error: %s", exc)
            claims = None

        if claims is not None:
            return self._claims_to_user_dict(token, claims)

        # ── Fallback: Supabase Auth introspection ───────────────────────────
        return await self._verify_via_introspection(token)

    def _claims_to_user_dict(self, token: str, claims: dict[str, Any]) -> dict[str, Any] | None:
        """Convert decoded JWT claims to the canonical user dict shape.

        The claims from a Supabase access token contain ``sub`` (user id),
        ``email``, ``phone``, and ``user_metadata``/``app_metadata`` in some
        token versions.  Per-channel verification is derived from the
        ``*_confirmed_at`` fields when present, otherwise from the ``aal``
        and provider metadata.
        """
        user_id = claims.get("sub")
        if not isinstance(user_id, str) or not user_id.strip():
            logger.warning("JWT claims missing 'sub'")
            return None

        email = claims.get("email") if isinstance(claims.get("email"), str) else None
        phone = claims.get("phone") if isinstance(claims.get("phone"), str) else None
        user_metadata = claims.get("user_metadata")
        if not isinstance(user_metadata, dict):
            user_metadata = {}
        app_metadata = claims.get("app_metadata")
        if not isinstance(app_metadata, dict):
            app_metadata = {}

        email_confirmed_at = claims.get("email_confirmed_at")
        phone_confirmed_at = claims.get("phone_confirmed_at")

        email_verified = bool(email_confirmed_at or phone_confirmed_at)
        phone_verified = bool(phone_confirmed_at)

        return {
            "id": user_id,
            "email": email,
            "user_metadata": user_metadata,
            "app_metadata": app_metadata,
            "phone": phone,
            "email_verified": email_verified,
            "phone_verified": phone_verified,
            "email_confirmed_at": email_confirmed_at,
            "phone_confirmed_at": phone_confirmed_at,
        }

    async def _verify_via_introspection(self, token: str) -> dict[str, Any] | None:
        """Verify a token by calling Supabase Auth ``GET /auth/v1/user``.

        Used as a fallback when local JWKS verification is not available.
        """
        url = f"{settings.SUPABASE_URL.rstrip('/')}/auth/v1/user"
        headers = {
            "Authorization": f"Bearer {token}",
            "apikey": settings.SUPABASE_CLIENT_KEY,
        }
        try:
            response = await self._verify_get(url, headers=headers)
        except _RETRYABLE_NETWORK_ERRORS as exc:
            logger.warning("Supabase auth host unreachable for token verify: %s", exc)
            return _make_failure(AuthFailureReason.PROVIDER_UNREACHABLE, str(exc))
        except Exception as exc:  # noqa: BLE001
            logger.error("Supabase API token verification failed: %s", exc, exc_info=True)
            return _make_failure(AuthFailureReason.PROVIDER_ERROR, str(exc))

        if response.status_code != 200:
            if response.status_code in (401, 403):
                logger.info(
                    "Supabase token verification failed (expected for expired tokens): status=%s body=%s",
                    response.status_code,
                    response.text[:200],
                )
            else:
                logger.warning(
                    "Supabase token verification failed: status=%s body=%s",
                    response.status_code,
                    response.text[:200],
                )
            return None

        try:
            user_data = response.json()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Supabase /auth/v1/user returned non-JSON: %s", exc)
            return None

        user_id = user_data.get("id")
        if not isinstance(user_id, str) or not user_id.strip():
            logger.warning("Supabase /auth/v1/user response missing id")
            return None

        email = user_data.get("email") if isinstance(user_data.get("email"), str) else None
        phone = user_data.get("phone") if isinstance(user_data.get("phone"), str) else None
        user_metadata = user_data.get("user_metadata")
        if not isinstance(user_metadata, dict):
            user_metadata = {}
        app_metadata = user_data.get("app_metadata")
        if not isinstance(app_metadata, dict):
            app_metadata = {}

        email_confirmed_at = user_data.get("email_confirmed_at")
        phone_confirmed_at = user_data.get("phone_confirmed_at")

        # `email_verified` is kept for backward compatibility: it is True when
        # EITHER channel is confirmed (matches the prior behaviour). Callers
        # that need per-channel verification should read the new explicit
        # keys (`*_confirmed_at`, `phone_verified`).
        email_verified = bool(email_confirmed_at or phone_confirmed_at)
        phone_verified = bool(phone_confirmed_at)

        return {
            "id": user_id,
            "email": email,
            "user_metadata": user_metadata,
            "app_metadata": app_metadata,
            "phone": phone,
            "email_verified": email_verified,
            "phone_verified": phone_verified,
            "email_confirmed_at": email_confirmed_at,
            "phone_confirmed_at": phone_confirmed_at,
        }

    @_retry_on_transient_network()
    async def _verify_get(self, url: str, *, headers: dict[str, str]) -> httpx.Response:
        """GET with bearer-style auth headers; transient network errors retried."""
        client = get_supabase_auth_http_client()
        return await client.get(url, headers=headers)

    async def admin_find_user_by_phone(self, phone: str) -> dict[str, Any] | None:
        """Lookup a user via Supabase GoTrue Admin by phone.

        Returns the user dict on success, ``None`` on not-found / bad
        response, or a tagged failure dict when the Supabase host is
        unreachable.
        """
        return await self._admin_find_user_by_field("phone", phone)

    async def admin_get_user_by_email(self, email: str) -> dict[str, Any] | None:
        """Lookup a Supabase Auth user by email via GoTrue Admin API."""
        return await self._admin_find_user_by_field("email", email)

    async def admin_create_user(
        self,
        email: str,
        password: str,
        email_confirm: bool = True,
        user_metadata: dict | None = None,
    ) -> dict[str, Any] | None:
        """Create a new Supabase Auth user via GoTrue Admin API.

        Returns created user dict with ``id`` and ``email`` on success,
        ``None`` on a non-retryable failure (e.g. email already exists),
        or a tagged failure dict on a transient network / DNS error.
        """
        url = self._admin_url("/admin/users")
        payload: dict[str, Any] = {
            "email": email,
            "password": password,
            "email_confirm": email_confirm,
        }
        if user_metadata:
            payload["user_metadata"] = user_metadata
        try:
            resp = await self._post_with_retry(url, json=payload)
        except _RETRYABLE_NETWORK_ERRORS as exc:
            logger.warning("Admin create user unreachable for %s: %s", email, exc)
            return _make_failure(AuthFailureReason.PROVIDER_UNREACHABLE, str(exc))
        except Exception as exc:  # noqa: BLE001
            logger.error("Admin create user error for %s: %s", email, exc)
            return _make_failure(AuthFailureReason.PROVIDER_ERROR, str(exc))

        if resp.status_code in (200, 201):
            data = resp.json()
            created: dict[str, Any] = {"id": data.get("id"), "email": data.get("email")}
            logger.info("Created Supabase Auth user: %s", created.get("email"))
            return created
        logger.warning(
            "Admin create user failed for %s: %s %s",
            email,
            resp.status_code,
            resp.text[:300],
        )
        return None

    async def admin_link_identity(
        self, user_id: str, provider: str, id_token: str
    ) -> bool | dict[str, Any]:
        """Link an OAuth identity to an existing Supabase user via GoTrue Admin API.

        Returns ``True`` on success, ``False`` on a non-retryable
        failure, or a tagged failure dict on a transient network / DNS
        error.
        """
        url = self._admin_url(f"/admin/users/{user_id}/identities")
        payload = {"provider": provider, "id_token": id_token}
        try:
            resp = await self._post_with_retry(url, json=payload)
        except _RETRYABLE_NETWORK_ERRORS as exc:
            logger.warning("Admin link identity unreachable: %s", exc)
            return _make_failure(AuthFailureReason.PROVIDER_UNREACHABLE, str(exc))
        except Exception as exc:  # noqa: BLE001
            logger.error("Admin link identity error: %s", exc)
            return _make_failure(AuthFailureReason.PROVIDER_ERROR, str(exc))

        if resp.status_code in (200, 201):
            logger.info("Successfully linked %s identity to user %s", provider, user_id)
            return True
        logger.warning("Failed to link identity: %s %s", resp.status_code, resp.text[:200])
        return False

    async def admin_delete_user(self, user_id: str) -> bool | dict[str, Any]:
        """Hard-delete a Supabase Auth user via the GoTrue Admin API.

        Hard-deleting the user immediately invalidates ALL of that user's
        sessions and refresh tokens (session revocation) and removes the
        identity from Supabase Auth. A ``404`` (user already absent) is
        treated as success for idempotency. Returns ``True`` on success,
        ``False`` on a non-retryable failure, or a tagged failure dict
        (:func:`_make_failure`) on a transient network / DNS error.
        """
        url = self._admin_url(f"/admin/users/{user_id}")
        try:
            resp = await self._delete_with_retry(url)
        except _RETRYABLE_NETWORK_ERRORS as exc:
            logger.warning("Admin delete user unreachable for %s: %s", user_id, exc)
            return _make_failure(AuthFailureReason.PROVIDER_UNREACHABLE, str(exc))
        except Exception as exc:  # noqa: BLE001
            logger.error("Admin delete user error for %s: %s", user_id, exc, exc_info=True)
            return _make_failure(AuthFailureReason.PROVIDER_ERROR, str(exc))

        if resp.status_code in (200, 204, 404):
            logger.info("Supabase auth user %s deleted (or already absent)", user_id)
            return True
        logger.warning(
            "Admin delete user failed for %s: %s %s",
            user_id,
            resp.status_code,
            resp.text[:200],
        )
        return False

    # -- Internal ---------------------------------------------------------------

    @staticmethod
    def _build_supabase_http_client(timeout: float) -> httpx.Client:
        return httpx.Client(timeout=timeout, follow_redirects=True, http2=True)

    @classmethod
    def _build_client_options(cls, timeout: float) -> ClientOptions:
        from supabase import ClientOptions

        return ClientOptions(httpx_client=cls._build_supabase_http_client(timeout))


# -- Module-level singleton & backward-compatible wrappers ----------------------

_manager = SupabaseClientManager()


def get_supabase_auth_client() -> Client:
    """Backward-compatible wrapper."""
    return _manager.get_auth_client()


def get_supabase_service_client() -> Client:
    """Backward-compatible wrapper."""
    return _manager.get_service_client()


async def close_supabase_clients() -> None:
    """Close manager-owned Supabase clients. Call on app shutdown.

    The shared async HTTP client used for GoTrue REST calls is owned
    by ``app.core.http`` and is closed via ``close_all_clients()``.
    """
    await _manager.close()


# Alias retained for any existing callers of the old name.
close_supabase_auth_http_client = close_supabase_clients


# -- Auth functions ------------------------------------------------------------


async def verify_supabase_token(token: str) -> dict[str, Any] | None:
    """Verify Supabase JWT by calling the Supabase Auth API.

    Sends the user's access token to ``GET /auth/v1/user`` which performs
    server-side validation.  This approach works with all Supabase key
    formats (including the newer ``sb_publishable_*`` / ``sb_secret_*``
    keys that do not expose JWKS).

    On success returns the user dict, on invalid token returns
    ``None``, and on a transient / DNS failure returns a tagged
    failure dict (see :func:`_make_failure`) that the dependency
    layer maps to HTTP 503.
    """
    return await _manager.verify_token(token)


async def admin_find_user_by_phone(phone: str) -> dict[str, Any] | None:
    """Lookup a user via Supabase GoTrue Admin by phone.

    Requires service role key configured in settings.SUPABASE_SECRET_KEY.
    Returns a minimal user dict if found, ``None`` if not found / bad
    response, or a tagged failure dict if the provider is unreachable.
    """
    return await _manager.admin_find_user_by_phone(phone)


async def admin_get_user_by_email(email: str) -> dict[str, Any] | None:
    """Lookup a Supabase Auth user by email via GoTrue Admin API."""
    return await _manager.admin_get_user_by_email(email)


async def admin_link_identity(user_id: str, provider: str, id_token: str) -> bool | dict[str, Any]:
    """Link an OAuth identity to an existing Supabase Auth user.

    Returns ``True`` on success, ``False`` on a non-retryable failure,
    or a tagged failure dict on a transient network / DNS error.
    """
    return await _manager.admin_link_identity(user_id, provider, id_token)


async def admin_create_user(
    email: str,
    password: str,
    email_confirm: bool = True,
    user_metadata: dict | None = None,
) -> dict[str, Any] | None:
    """Create a new Supabase Auth user via GoTrue Admin API."""
    return await _manager.admin_create_user(
        email=email,
        password=password,
        email_confirm=email_confirm,
        user_metadata=user_metadata,
    )


async def admin_delete_user(user_id: str) -> bool | dict[str, Any]:
    """Hard-delete a Supabase Auth user via the GoTrue Admin API.

    Returns ``True`` on success (a 404 / already-absent is treated as
    success for idempotency), ``False`` on a non-retryable failure, or a
    tagged failure dict on a transient network / DNS error.
    """
    return await _manager.admin_delete_user(user_id)
