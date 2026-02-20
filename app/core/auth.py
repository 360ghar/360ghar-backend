from typing import Any, Dict, Optional

import httpx
from supabase import Client, create_client

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

# Supabase client for auth only
_supabase_client: Client = None
_supabase_service_client: Client = None


def get_supabase_auth_client() -> Client:
    """Get Supabase client for authentication only"""
    global _supabase_client
    if _supabase_client is None:
        key = settings.SUPABASE_CLIENT_KEY
        if not key:
            raise ValueError(
                "Missing Supabase publishable key. Set SUPABASE_PUBLISHABLE_KEY."
            )
        _supabase_client = create_client(settings.SUPABASE_URL, key)
    return _supabase_client

def get_supabase_service_client() -> Client:
    """Get Supabase client using service role key for server-side DB ops"""
    global _supabase_service_client
    if _supabase_service_client is None:
        _supabase_service_client = create_client(settings.SUPABASE_URL, settings.SUPABASE_SECRET_KEY)
    return _supabase_service_client


async def verify_supabase_token(token: str) -> Optional[Dict[str, Any]]:
    """Verify Supabase JWT by calling the Supabase Auth API.

    Sends the user's access token to ``GET /auth/v1/user`` which performs
    server-side validation.  This approach works with all Supabase key
    formats (including the newer ``sb_publishable_*`` / ``sb_secret_*``
    keys that do not expose JWKS).
    """
    url = f"{settings.SUPABASE_URL.rstrip('/')}/auth/v1/user"
    headers = {
        "Authorization": f"Bearer {token}",
        "apikey": settings.SUPABASE_CLIENT_KEY,
    }
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
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


async def admin_find_user_by_phone(phone: str) -> Optional[Dict[str, Any]]:
    """Lookup a user via Supabase GoTrue Admin by phone.

    Requires service role key configured in settings.SUPABASE_SECRET_KEY.
    Returns a minimal user dict if found, else None.
    """
    base = settings.SUPABASE_URL.rstrip('/') + '/auth/v1'
    url = f"{base}/admin/users"
    headers = {
        "apikey": settings.SUPABASE_SECRET_KEY,
        "Authorization": f"Bearer {settings.SUPABASE_SECRET_KEY}",
    }
    params = {"phone": phone, "per_page": 1}
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, headers=headers, params=params)
            if resp.status_code == 200:
                data = resp.json()
                # GoTrue returns { users: [...], aud, next_page?, last_page? } in some versions
                users = None
                if isinstance(data, dict) and "users" in data:
                    users = data.get("users") or []
                elif isinstance(data, list):
                    users = data
                else:
                    users = []
                if users:
                    user = users[0]
                    # Ensure match on phone to avoid false positives when server ignores filter
                    if user.get("phone") == phone:
                        return {
                            "id": user.get("id"),
                            "email": user.get("email"),
                            "phone": user.get("phone"),
                            "user_metadata": user.get("user_metadata") or {},
                        }
                    return None
                return None
            # 404 from admin implies not found; treat as None
            if resp.status_code == 404:
                return None
            logger.warning(
                "Admin user lookup by phone failed: %s %s", resp.status_code, resp.text
            )
            return None
    except Exception as e:
        logger.error(f"Admin user lookup error: {e}")
        return None
