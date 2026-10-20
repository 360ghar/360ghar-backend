"""FCM (Firebase Cloud Messaging) token management and message sending."""

from __future__ import annotations

import asyncio
import inspect
import json
import os
from typing import TYPE_CHECKING, Any

import httpx

if TYPE_CHECKING:
    from google.oauth2 import service_account

from app.config import settings
from app.core.constants.limits import FCM_TOKEN_REFRESH_BUFFER_SECONDS
from app.core.logging import get_logger
from app.models.enums import AppKey

logger = get_logger(__name__)

FCM_SCOPE = "https://www.googleapis.com/auth/firebase.messaging"

_fcm_credentials: service_account.Credentials | None = None
_fcm_token_expiry: float = 0.0
_fcm_client: httpx.AsyncClient | None = None
_fcm_available: bool | None = None  # None=unchecked, True=ok, False=creds missing
_fcm_refresh_lock = asyncio.Lock()


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


async def _access_token() -> str | None:
    """Create or reuse an OAuth2 access token from the service account file.

    Caches credentials and refreshes only when the token is near expiry.
    Returns None (and sets _fcm_available=False) if credentials are missing,
    so callers can degrade gracefully instead of crashing.
    """
    global _fcm_credentials, _fcm_token_expiry, _fcm_available

    if _fcm_available is False:
        return None

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
    if _fcm_credentials is not None and now < _fcm_token_expiry:
        _fcm_available = True
        return str(_fcm_credentials.token)

    async with _fcm_refresh_lock:
        if _fcm_available is False:
            return None

        now = _time.time()
        if _fcm_credentials is not None and now < _fcm_token_expiry:
            _fcm_available = True
            return str(_fcm_credentials.token)

        try:
            # Lazy import to avoid hard dependency at app import time.
            from google.auth.transport.requests import Request
            from google.oauth2 import service_account

            if _fcm_credentials is None:
                _fcm_credentials = service_account.Credentials.from_service_account_file(
                    creds_path,
                    scopes=[FCM_SCOPE],
                )

            await asyncio.to_thread(_fcm_credentials.refresh, Request())
            credential_expiry = getattr(_fcm_credentials, "expiry", None)
            if credential_expiry is not None:
                _fcm_token_expiry = credential_expiry.timestamp() - FCM_TOKEN_REFRESH_BUFFER_SECONDS
            else:
                _fcm_token_expiry = _time.time() + 3600 - FCM_TOKEN_REFRESH_BUFFER_SECONDS
        except Exception as exc:
            logger.error("FCM credential initialization failed: %s", exc)
            # Keep availability retryable for transient Google auth/network failures.
            _fcm_available = None
            return None

    _fcm_available = True
    return str(_fcm_credentials.token)


# Android notification channel per app. The app must create the channel before
# a push that names it can display.
APP_CHANNEL_IDS: dict[str, str] = {
    AppKey.ghar.value: "high_importance_channel",
    AppKey.estate.value: "high_importance_channel",
    AppKey.flatmates.value: "flatmates_messages",
    AppKey.stays.value: "high_importance_channel",
}


def _data_value(value: Any) -> str:
    """FCM data values are strings. Structured values are JSON text, never a Python repr."""
    if isinstance(value, str):
        return value
    return json.dumps(value, separators=(",", ":"), default=str)


def build_message(
    *,
    token: str,
    title: str | None = None,
    body: str | None = None,
    data: dict[str, Any] | None = None,
    route: str | None = None,
    type_key: str | None = None,
    app_key: AppKey = AppKey.ghar,
    image: str | None = None,
    priority_high: bool = True,
    content_available: bool = False,
    ttl_seconds: int | None = None,
) -> dict[str, Any]:
    """Build an FCM HTTP v1 message for one device token.

    Data keys: ``route`` is the in-app route to open, ``type_key`` is the
    notification type at the top level, and any ``_meta`` block is JSON text.
    """
    payload: dict[str, str] = {k: _data_value(v) for k, v in (data or {}).items()}
    if route:
        payload["route"] = route
    if type_key:
        payload["type_key"] = type_key

    msg: dict[str, Any] = {"message": {"token": token}}

    if title or body or image:
        msg["message"]["notification"] = {
            k: v for k, v in [("title", title), ("body", body), ("image", image)] if v
        }

    if payload:
        msg["message"]["data"] = payload

    android_cfg: dict[str, Any] = {"notification": {"channel_id": APP_CHANNEL_IDS[app_key.value]}}
    if priority_high:
        android_cfg["priority"] = "HIGH"
    if ttl_seconds is not None:
        android_cfg["ttl"] = f"{int(ttl_seconds)}s"
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
    token_result = _access_token()
    token = await token_result if inspect.isawaitable(token_result) else token_result
    if token is None:
        raise RuntimeError("FCM credentials not configured — push notifications disabled")
    project_id = settings.FIREBASE_PROJECT_ID
    url = f"https://fcm.googleapis.com/v1/projects/{project_id}/messages:send"
    client = _get_fcm_client()
    resp = await client.post(url, headers={"Authorization": f"Bearer {token}"}, json=message)
    resp.raise_for_status()
    return dict(resp.json())
