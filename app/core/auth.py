from typing import Any

import httpx

from app.config import settings
from app.core.logging import get_logger
from supabase import Client, ClientOptions, create_client

logger = get_logger(__name__)

SUPABASE_AUTH_TIMEOUT = 10.0
SUPABASE_DATA_TIMEOUT = 120.0
SUPABASE_STORAGE_TIMEOUT = 20.0


class SupabaseClientManager:
    """Encapsulates Supabase client lifecycle — replaces module-level globals.

    Provides lazy initialization of all Supabase clients and a proper
    shutdown path for the async HTTP client used for auth API calls.
    """

    def __init__(self) -> None:
        self._auth_client: Client | None = None
        self._service_client: Client | None = None
        self._storage_client: Client | None = None
        self._auth_http_client: httpx.AsyncClient | None = None

    # -- Auth HTTP client (async, used for verify_supabase_token) ---------------

    def get_auth_http_client(self) -> httpx.AsyncClient:
        """Get or create the reusable async HTTP client for Supabase auth calls."""
        if self._auth_http_client is None or self._auth_http_client.is_closed:
            self._auth_http_client = httpx.AsyncClient(
                timeout=SUPABASE_AUTH_TIMEOUT, follow_redirects=True
            )
        return self._auth_http_client

    # -- Sync Supabase clients --------------------------------------------------

    def get_auth_client(self) -> Client:
        """Get Supabase client for authentication only."""
        if self._auth_client is None:
            key = settings.SUPABASE_CLIENT_KEY
            if not key:
                raise ValueError(
                    "Missing Supabase publishable key. Set SUPABASE_PUBLISHABLE_KEY."
                )
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

    def get_storage_client(self) -> Client:
        """Get Supabase client configured for server-side storage operations."""
        if self._storage_client is None:
            self._storage_client = create_client(
                settings.SUPABASE_URL,
                settings.SUPABASE_SECRET_KEY,
                options=self._build_client_options(SUPABASE_STORAGE_TIMEOUT),
            )
        return self._storage_client

    # -- Lifecycle --------------------------------------------------------------

    async def close(self) -> None:
        """Gracefully close all managed HTTP clients. Call on app shutdown."""
        if self._auth_http_client and not self._auth_http_client.is_closed:
            await self._auth_http_client.aclose()
            self._auth_http_client = None

        # Close sync Supabase clients' underlying httpx.Client connections.
        # Each sub-client (auth, postgrest, storage) stores its httpx.Client
        # as `.session` on the respective sub-object.
        for client_attr in ("_auth_client", "_service_client", "_storage_client"):
            client = getattr(self, client_attr, None)
            if client is None:
                continue
            # Try known sub-client session paths
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

    async def verify_token(self, token: str) -> dict[str, Any] | None:
        """Verify Supabase JWT by calling the Supabase Auth API."""
        url = f"{settings.SUPABASE_URL.rstrip('/')}/auth/v1/user"
        headers = {
            "Authorization": f"Bearer {token}",
            "apikey": settings.SUPABASE_CLIENT_KEY,
        }
        try:
            client = self.get_auth_http_client()
            response = await client.get(url, headers=headers)

            if response.status_code != 200:
                logger.warning(
                    "Supabase token verification failed: status=%s body=%s",
                    response.status_code,
                    response.text[:200],
                )
                return None

            user_data = response.json()
            user_id = user_data.get("id")
            if not isinstance(user_id, str) or not user_id.strip():
                logger.warning("Supabase /auth/v1/user response missing id")
                return None

            email = user_data.get("email") if isinstance(user_data.get("email"), str) else None
            phone = user_data.get("phone") if isinstance(user_data.get("phone"), str) else None
            user_metadata = user_data.get("user_metadata")
            if not isinstance(user_metadata, dict):
                user_metadata = {}

            email_verified = bool(
                user_data.get("email_confirmed_at")
                or user_data.get("phone_confirmed_at")
            )

            return {
                "id": user_id,
                "email": email,
                "user_metadata": user_metadata,
                "phone": phone,
                "email_verified": email_verified,
            }
        except Exception as exc:  # noqa: BLE001
            logger.error("Supabase API token verification failed: %s", exc, exc_info=True)
            return None

    async def admin_find_user_by_phone(self, phone: str) -> dict[str, Any] | None:
        """Lookup a user via Supabase GoTrue Admin by phone."""
        base = settings.SUPABASE_URL.rstrip('/') + '/auth/v1'
        url = f"{base}/admin/users"
        headers = {
            "apikey": settings.SUPABASE_SECRET_KEY,
            "Authorization": f"Bearer {settings.SUPABASE_SECRET_KEY}",
        }
        params: dict[str, str | int] = {"phone": phone, "per_page": 1}
        try:
            client = self.get_auth_http_client()
            resp = await client.get(url, headers=headers, params=params)
            if resp.status_code == 200:
                data = resp.json()
                users = None
                if isinstance(data, dict) and "users" in data:
                    users = data.get("users") or []
                elif isinstance(data, list):
                    users = data
                else:
                    users = []
                if users:
                    user = users[0]
                    if user.get("phone") == phone:
                        return {
                            "id": user.get("id"),
                            "email": user.get("email"),
                            "phone": user.get("phone"),
                            "user_metadata": user.get("user_metadata") or {},
                        }
                    return None
                return None
            if resp.status_code == 404:
                return None
            logger.warning(
                "Admin user lookup by phone failed: %s %s", resp.status_code, resp.text
            )
            return None
        except Exception as e:
            logger.error("Admin user lookup error: %s", e)
            return None

    # -- Internal ---------------------------------------------------------------

    @staticmethod
    def _build_supabase_http_client(timeout: float) -> httpx.Client:
        return httpx.Client(timeout=timeout, follow_redirects=True, http2=True)

    @classmethod
    def _build_client_options(cls, timeout: float) -> ClientOptions:
        return ClientOptions(httpx_client=cls._build_supabase_http_client(timeout))


# -- Module-level singleton & backward-compatible wrappers ----------------------

_manager = SupabaseClientManager()


def _get_supabase_auth_http_client() -> httpx.AsyncClient:
    """Backward-compatible wrapper."""
    return _manager.get_auth_http_client()


def get_supabase_auth_client() -> Client:
    """Backward-compatible wrapper."""
    return _manager.get_auth_client()


def get_supabase_service_client() -> Client:
    """Backward-compatible wrapper."""
    return _manager.get_service_client()


def get_supabase_storage_client() -> Client:
    """Backward-compatible wrapper."""
    return _manager.get_storage_client()


async def close_supabase_clients() -> None:
    """Close all managed Supabase connections. Call on app shutdown."""
    await _manager.close()


# Alias for any existing callers of the old name
close_supabase_auth_http_client = close_supabase_clients


# -- Auth functions ------------------------------------------------------------

async def verify_supabase_token(token: str) -> dict[str, Any] | None:
    """Verify Supabase JWT by calling the Supabase Auth API.

    Sends the user's access token to ``GET /auth/v1/user`` which performs
    server-side validation.  This approach works with all Supabase key
    formats (including the newer ``sb_publishable_*`` / ``sb_secret_*``
    keys that do not expose JWKS).
    """
    return await _manager.verify_token(token)


async def admin_find_user_by_phone(phone: str) -> dict[str, Any] | None:
    """Lookup a user via Supabase GoTrue Admin by phone.

    Requires service role key configured in settings.SUPABASE_SECRET_KEY.
    Returns a minimal user dict if found, else None.
    """
    return await _manager.admin_find_user_by_phone(phone)
