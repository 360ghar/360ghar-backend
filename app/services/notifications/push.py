"""Supabase push notification dispatch and device token management."""

from __future__ import annotations

import asyncio
from typing import Any

import httpx

from app.core.exceptions import (
    BadRequestException,
    BaseAPIException,
    ExternalServiceError,
    ServiceUnavailableException,
)
from app.core.logging import get_logger
from app.core.utils import is_valid_uuid, utc_now_iso
from app.models.enums import AppKey, DevicePlatform
from app.services.notification_config import NotificationChannel

from . import fcm
from .crud import _record_notification
from .helpers import (
    _augment_data_with_meta,
    _get_type_config,
    _run_sync,
    _supa,
)

logger = get_logger(__name__)
PUSH_FANOUT_CONCURRENCY = 10
_DEAD_TOKEN_MARKERS = ("UNREGISTERED", "NotRegistered")


def fcm_error_to_api_error(exc: httpx.HTTPStatusError) -> BaseAPIException:
    """Map an FCM HTTP error to an API error.

    A 4xx that describes the message (bad token, bad payload) is a 400. 429 is a
    retryable quota or rate limit, so it is a 503 with Retry-After. Auth
    failures and 5xx from FCM are upstream faults, so they are a 502.
    """
    status = exc.response.status_code
    if status == 429:
        return ServiceUnavailableException(
            detail="Push service is busy. Retry later",
            error_code="FCM_RATE_LIMITED",
            headers={"Retry-After": "60"},
        )
    if 400 <= status < 500 and status not in (401, 403):
        return BadRequestException(
            detail="FCM rejected the push message", error_code="FCM_REJECTED"
        )
    return ExternalServiceError(detail="Push service is unavailable", error_code="FCM_UNAVAILABLE")


def _channel_error_code(exc: Exception) -> str:
    """Return the API error code for one failed FCM send. Non-HTTP errors are FCM_UNAVAILABLE."""
    if isinstance(exc, httpx.HTTPStatusError):
        return fcm_error_to_api_error(exc).error_code or "FCM_UNAVAILABLE"
    return "FCM_UNAVAILABLE"


async def register_device_token(
    *,
    token: str,
    platform: DevicePlatform,
    app_key: AppKey,
    user_id: str | None = None,
    app_version: str | None = None,
    locale: str | None = None,
) -> dict[str, Any]:
    """Register a device token for one app.

    A signed-in caller binds the token to its own user. An anonymous caller
    never changes a token that already belongs to a user: the call returns the
    same shape and changes nothing, so the owner keeps the device.
    """
    now_iso = utc_now_iso()
    # user_id is a UUID FK to auth.users. Non-UUID seed placeholders must not
    # bind (APIError invalid uuid); the token is still registered, unbound.
    bind_user_id = user_id if is_valid_uuid(user_id) else None
    row = {
        "token": token,
        "user_id": bind_user_id,
        "platform": platform.value,
        "app_key": app_key.value,
        "app_version": app_version,
        "locale": locale,
        "is_active": True,
        "last_seen": now_iso,
    }

    def _sync_register() -> None:
        supa = _supa()
        if bind_user_id is None:
            existing = (
                supa.table("device_tokens")
                .select("user_id")
                .eq("token", token)
                .limit(1)
                .execute()
                .data
                or []
            )
            if existing and existing[0].get("user_id"):
                return
        # Atomic upsert on the unique token. Concurrent registrations of the
        # same token do not raise 23505.
        supa.table("device_tokens").upsert(row, on_conflict="token").execute()

    await _run_sync(_sync_register)
    logger.info(
        "Registered device token",
        extra={
            "token_hash": hash(token),
            "app_key": app_key.value,
            "bound": bind_user_id is not None,
        },
    )
    return {
        "platform": platform,
        "app_key": app_key,
        "app_version": app_version,
        "locale": locale,
        "last_seen": now_iso,
    }


async def unregister_device_token(*, token: str, user_id: str) -> None:
    """Deactivate a device token that belongs to ``user_id``.

    A token of another user is not changed. The call is idempotent.
    """
    now_iso = utc_now_iso()

    def _sync_unregister() -> None:
        _supa().table("device_tokens").update({"is_active": False, "last_seen": now_iso}).eq(
            "token", token
        ).eq("user_id", user_id).execute()

    await _run_sync(_sync_unregister)
    logger.info("Deactivated device token", extra={"token_hash": hash(token)})


async def send_to_token(
    *,
    token: str,
    title: str,
    body: str,
    data: dict[str, str] | None = None,
    deep_link: str | None = None,
    image: str | None = None,
    type_key: str | None = None,
    app_key: AppKey = AppKey.ghar,
) -> dict[str, Any]:
    """Send one push to one token. FCM 4xx and 5xx errors raise an API error."""
    priority_label, ttl, priority_high = _get_type_config(type_key)
    payload_data = _augment_data_with_meta(
        data,
        type_key=type_key,
        channel=NotificationChannel.PUSH,
        priority=priority_label,
    )
    notif = await _record_notification(
        title=title,
        body=body,
        data=payload_data,
        audience_type="tokens",
    )
    try:
        msg = fcm.build_message(
            token=token,
            title=title,
            body=body,
            data=payload_data,
            route=deep_link,
            type_key=type_key,
            app_key=app_key,
            image=image,
            priority_high=priority_high,
            ttl_seconds=ttl,
        )
        resp = await fcm.send_message(msg)

        def _sync_record_delivery():
            supa = _supa()
            dev = supa.table("device_tokens").select("id").eq("token", token).execute()
            supa.table("notification_deliveries").insert(
                {
                    "notification_id": notif.get("id"),
                    "device_token_id": (dev.data[0]["id"] if dev.data else None),
                    "status": "sent",
                    "fcm_message_id": resp.get("name"),
                    "sent_at": utc_now_iso(),
                }
            ).execute()

        await _run_sync(_sync_record_delivery)
        return {"ok": True, "fcm": resp}
    except RuntimeError as e:
        logger.error("FCM send skipped — credentials not available: %s", e)
        return {"ok": False, "error": "FCM not configured"}
    except httpx.HTTPStatusError as e:
        err_text = e.response.text
        logger.error(
            "FCM send failed",
            extra={"status": e.response.status_code, "error": err_text},
            exc_info=True,
        )

        def _sync_record_failure():
            supa = _supa()
            supa.table("notification_deliveries").insert(
                {
                    "notification_id": notif.get("id"),
                    "status": "failed",
                    "error_code": err_text,
                }
            ).execute()
            if any(marker in err_text for marker in _DEAD_TOKEN_MARKERS):
                supa.table("device_tokens").update({"is_active": False}).eq(
                    "token", token
                ).execute()

        await _run_sync(_sync_record_failure)
        raise fcm_error_to_api_error(e) from e


async def send_to_user(
    *,
    user_id: str,
    title: str,
    body: str,
    data: dict[str, str] | None = None,
    deep_link: str | None = None,
    type_key: str | None = None,
    app_key: AppKey = AppKey.ghar,
) -> dict[str, Any]:
    """Send a push to every active token of ``user_id`` for ``app_key``.

    Best-effort: Supabase record and token failures return ``ok: False``
    instead of raising, so the dispatcher can still run email and SMS. ``ok``
    is true when at least one token got the message, or when the user has no
    active token for the app.
    """
    # device_tokens.user_id and notifications.target_user_id are UUID columns.
    # Legacy seed ids must not reach PostgREST (APIError invalid uuid).
    if not is_valid_uuid(user_id):
        return {
            "ok": True,
            "sent": 0,
            "failed": 0,
            "notification_id": None,
            "skipped": "invalid_user_id",
        }

    priority_label, ttl, priority_high = _get_type_config(type_key)
    payload_data = _augment_data_with_meta(
        data,
        type_key=type_key,
        channel=NotificationChannel.PUSH,
        priority=priority_label,
    )
    if deep_link:
        payload_data["route"] = deep_link
    try:
        notif = await _record_notification(
            title=title,
            body=body,
            data=payload_data,
            audience_type="user",
            target_user_id=user_id,
        )
    except Exception as e:
        logger.error(
            "Failed to record push notification for user %s: %s",
            user_id,
            e,
            exc_info=True,
        )
        return {"ok": False, "sent": 0, "failed": 0, "error": f"record_notification: {e}"}

    def _sync_get_tokens():
        supa = _supa()
        return (
            supa.table("device_tokens")
            .select("token,id")
            .eq("user_id", user_id)
            .eq("is_active", True)
            .eq("app_key", app_key.value)
            .execute()
            .data
        )

    try:
        tokens = await _run_sync(_sync_get_tokens)
    except Exception as e:
        logger.error(
            "Failed to fetch device tokens for user %s: %s",
            user_id,
            e,
            exc_info=True,
        )
        return {
            "ok": False,
            "sent": 0,
            "failed": 0,
            "notification_id": notif.get("id"),
            "error": f"device_tokens: {e}",
        }

    if not tokens:
        return {"ok": True, "sent": 0, "failed": 0, "notification_id": notif.get("id")}

    semaphore = asyncio.Semaphore(PUSH_FANOUT_CONCURRENCY)

    async def _send_one(t: dict[str, Any]) -> str | None:
        """Send to one token. Returns None when sent, else the channel error code."""
        async with semaphore:
            tk = t["token"]
            tk_id = t["id"]
            try:
                msg = fcm.build_message(
                    token=tk,
                    title=title,
                    body=body,
                    data=payload_data,
                    route=deep_link,
                    type_key=type_key,
                    app_key=app_key,
                    priority_high=priority_high,
                    ttl_seconds=ttl,
                )
                resp = await fcm.send_message(msg)

                def _sync_record_sent():
                    supa = _supa()
                    supa.table("notification_deliveries").insert(
                        {
                            "notification_id": notif.get("id"),
                            "device_token_id": tk_id,
                            "status": "sent",
                            "fcm_message_id": resp.get("name"),
                            "sent_at": utc_now_iso(),
                        }
                    ).execute()

                await _run_sync(_sync_record_sent)
                return None
            except Exception as e:  # broad to capture HTTP and credential errors
                err = str(e)
                # httpx's message omits the response body. FCM puts UNREGISTERED in the body.
                body_text = e.response.text if isinstance(e, httpx.HTTPStatusError) else ""
                is_dead_token = any(
                    marker in f"{err} {body_text}" for marker in _DEAD_TOKEN_MARKERS
                )
                error_code = _channel_error_code(e)
                logger.warning("FCM send failed for token in send_to_user: %s", err, exc_info=True)

                def _sync_record_failed():
                    supa = _supa()
                    if is_dead_token:
                        supa.table("device_tokens").update({"is_active": False}).eq(
                            "token", tk
                        ).execute()
                    supa.table("notification_deliveries").insert(
                        {
                            "notification_id": notif.get("id"),
                            "device_token_id": tk_id,
                            "status": "failed",
                            "error_code": err,
                        }
                    ).execute()

                try:
                    await _run_sync(_sync_record_failed)
                except Exception as record_err:
                    logger.warning(
                        "Failed to record FCM delivery failure: %s",
                        record_err,
                        exc_info=True,
                    )
                return error_code

    outcomes = await asyncio.gather(*[_send_one(t) for t in tokens])
    errors = [code for code in outcomes if code is not None]
    sent = len(outcomes) - len(errors)
    result: dict[str, Any] = {
        "ok": sent > 0,
        "sent": sent,
        "failed": len(errors),
        "notification_id": notif.get("id"),
    }
    if sent == 0:
        # The first failure's code, so the caller sees the FCM status (for example FCM_RATE_LIMITED).
        result["error"] = errors[0]
    return result
