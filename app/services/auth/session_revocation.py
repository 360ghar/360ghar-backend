"""Supabase session revocation.

After a password change (or other security event), previously-issued Supabase
refresh tokens can be revoked via the GoTrue Admin API so that active sessions
stop working.  This module calls the Admin ``/auth/v1/admin/users/{id}/logout``
endpoint with ``scope=global`` to invalidate every refresh token for the user,
forcing every device to re-authenticate.

Note: Supabase access (JWT) tokens are short-lived and cannot be revoked before
their ``exp`` claim, so a stolen access token remains valid until it expires
(typically minutes). Revoking refresh tokens ensures no new access tokens can
be minted, which is the strongest session invalidation Supabase offers.
"""

from __future__ import annotations

import httpx

from app.config import settings
from app.core.exceptions import ServiceUnavailableException
from app.core.http import get_supabase_auth_http_client
from app.core.logging import get_logger

logger = get_logger(__name__)


async def revoke_all_user_sessions(supabase_user_id: str) -> None:
    """Invalidate every Supabase session for ``supabase_user_id``.

    Calls ``POST {SUPABASE_URL}/auth/v1/admin/users/{id}/logout`` with the
    service-role key and ``{"scope": "global"}``, which deletes all of the
    user's refresh tokens (revoking every active session across all devices).
    Raises :class:`ServiceUnavailableException` if Supabase is unreachable or
    returns an error response so callers surface a 503 to the webhook sender.
    """
    url = (
        f"{settings.SUPABASE_URL.rstrip('/')}/auth/v1/admin/users/"
        f"{supabase_user_id}/logout"
    )
    headers = {
        "Authorization": f"Bearer {settings.SUPABASE_SECRET_KEY}",
        "apikey": settings.SUPABASE_SECRET_KEY,
        "Content-Type": "application/json",
    }
    body = {"scope": "global"}

    try:
        client = get_supabase_auth_http_client()
        response = await client.post(url, headers=headers, json=body, timeout=15.0)
    except httpx.HTTPError as exc:
        logger.error(
            "Supabase session revocation request failed for user %s: %s",
            supabase_user_id,
            exc,
        )
        raise ServiceUnavailableException(detail="Failed to revoke user sessions") from None

    if response.status_code >= 400:
        logger.error(
            "Supabase session revocation failed for user %s: status=%s body=%s",
            supabase_user_id,
            response.status_code,
            response.text,
        )
        raise ServiceUnavailableException(detail="Failed to revoke user sessions")

    logger.info("Revoked all Supabase sessions for user %s", supabase_user_id)
