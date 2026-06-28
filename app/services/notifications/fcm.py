"""FCM (Firebase Cloud Messaging) token management and message sending."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

import httpx

if TYPE_CHECKING:
    from google.oauth2 import service_account

from app.config import settings
from app.core.exceptions import BadRequestException
from app.core.logging import get_logger

logger = get_logger(__name__)

FCM_SCOPE = "https://www.googleapis.com/auth/firebase.messaging"

_fcm_credentials: service_account.Credentials | None = None
_fcm_token_expiry: float = 0.0
_fcm_client: httpx.AsyncClient | None = None
_fcm_available: bool | None = None  # None=unchecked, True=ok, False=creds missing


def _get_fcm_client() -> httpx.AsyncClient:
    """Return a reusable FCM HTTP client."""
    global _fcm_client
    if _fcm_client is None or _fcm_client.is_closed:
        _fcm_client = httpx.AsyncClient(timeout=15)
    return _fcm_client


async def close_fcm_client() -> None:
    """Close the reusable FCM HTTP client."""
    global _fcm_client
    if _fcm_client is not None and not _fcm_client.is_closed:
        await _fcm_client.aclose()
    _fcm_client = None


def _access_token() -> str | None:
    """Create or reuse an OAuth2 access token from the service account file.

    Caches credentials and refreshes only when the token is near expiry.
    Returns None (and sets _fcm_available=False) if credentials are missing,
    so callers can degrade gracefully instead of crashing.
    """
    global _fcm_credentials, _fcm_token_expiry, _fcm_available

    if _fcm_available is False:
        return None

    # Lazy import to avoid hard dependency at app import time
    from google.auth.transport.requests import Request
    from google.oauth2 import service_account

    if not settings.FIREBASE_PROJECT_ID:
        logger.error("FIREBASE_PROJECT_ID is not configured — push notifications disabled")
        _fcm_available = False
        return None
    creds_path = settings.GOOGLE_APPLICATION_CREDENTIALS
    if not creds_path or not os.path.exists(creds_path):
        logger.error(
            "GOOGLE_APPLICATION_CREDENTIALS path is invalid or missing — push notifications disabled"
        )
        _fcm_available = False
        return None

    import time as _time

    now = _time.time()

    try:
        if _fcm_credentials is None:
            _fcm_credentials = service_account.Credentials.from_service_account_file(
                creds_path,
                scopes=[FCM_SCOPE],
            )

        if now >= _fcm_token_expiry:
            _fcm_credentials.refresh(Request())
            _fcm_token_expiry = now + 3300
    except Exception as exc:
        logger.error("FCM credential initialization failed: %s", exc)
        _fcm_available = False
        return None

    _fcm_available = True
    return str(_fcm_credentials.token)


def build_message(
    *,
    token: str | None = None,
    topic: str | None = None,
    title: str | None = None,
    body: str | None = None,
    data: dict[str, str] | None = None,
    deep_link: str | None = None,
    image: str | None = None,
    priority_high: bool = True,
    content_available: bool = False,
    ttl_seconds: int | None = None,
) -> dict[str, Any]:
    """Build an FCM HTTP v1 message payload.

    Supports notification+data and data-only content (iOS background).
    """
    data = data or {}
    if deep_link:
        data["deep_link"] = deep_link

    msg: dict[str, Any] = {"message": {}}
    if token:
        msg["message"]["token"] = token
    elif topic:
        msg["message"]["topic"] = topic
    else:
        raise BadRequestException(detail="Either token or topic must be provided")

    if title or body or image:
        msg["message"]["notification"] = {
            k: v for k, v in [("title", title), ("body", body), ("image", image)] if v
        }

    if data:
        msg["message"]["data"] = {k: str(v) for k, v in data.items()}

    if priority_high or ttl_seconds is not None:
        android_cfg: dict[str, Any] = msg["message"].get("android") or {}
        if priority_high:
            android_cfg["priority"] = "HIGH"
            android_cfg["notification"] = {"channel_id": "high_importance_channel"}
        if ttl_seconds is not None:
            android_cfg["ttl"] = f"{int(ttl_seconds)}s"
        if android_cfg:
            msg["message"]["android"] = android_cfg

    # APNs headers for alert vs background
    apns_headers = {"apns-priority": "10", "apns-push-type": "alert"}
    aps_payload: dict[str, Any] = {"sound": "default"}
    if content_available:
        apns_headers = {"apns-priority": "5", "apns-push-type": "background"}
        aps_payload = {"content-available": 1}
    msg["message"]["apns"] = {
        "headers": apns_headers,
        "payload": {"aps": aps_payload},
    }

    return msg


async def send_message(message: dict[str, Any]) -> dict[str, Any]:
    """Send a single FCM HTTP v1 message."""
    token = _access_token()
    if token is None:
        raise RuntimeError("FCM credentials not configured — push notifications disabled")
    project_id = settings.FIREBASE_PROJECT_ID
    url = f"https://fcm.googleapis.com/v1/projects/{project_id}/messages:send"
    client = _get_fcm_client()
    resp = await client.post(url, headers={"Authorization": f"Bearer {token}"}, json=message)
    resp.raise_for_status()
    return dict(resp.json())
