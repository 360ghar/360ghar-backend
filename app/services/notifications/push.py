"""Supabase push notification dispatch and device token management."""

from __future__ import annotations

import asyncio
from typing import Any, Literal

import httpx

from app.core.logging import get_logger
from app.core.utils import utc_now_iso
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


async def register_device_token(
    *,
    token: str,
    platform: Literal["android", "ios", "web"],
    user_id: str | None = None,
    app_version: str | None = None,
    locale: str | None = None,
) -> dict[str, Any]:
    """Upsert a device token in Supabase device_tokens."""
    now_iso = utc_now_iso()

    # Atomic upsert: resolves the (token) unique constraint inside Postgres
    # via INSERT ... ON CONFLICT (token) DO UPDATE. The previous SELECT-then-
    # INSERT/UPDATE pattern raced under concurrent registrations of the same
    # FCM token (cold-start / refresh / retry), surfacing as 23505 500s.
    def _sync_register():
        supa = _supa()
        supa.table("device_tokens").upsert(
            {
                "token": token,
                "user_id": user_id,
                "platform": platform,
                "app_version": app_version,
                "locale": locale,
                "is_active": True,
                "last_seen": now_iso,
            },
            on_conflict="token",
        ).execute()

    await _run_sync(_sync_register)
    logger.info("Registered device token", extra={"token_hash": hash(token), "user_id": user_id})
    return {"ok": True}


async def unregister_device_token(*, token: str) -> dict[str, Any]:
    """Deactivate a device token in Supabase device_tokens."""
    now_iso = utc_now_iso()

    def _sync_unregister():
        supa = _supa()
        supa.table("device_tokens").update(
            {
                "is_active": False,
                "last_seen": now_iso,
            }
        ).eq("token", token).execute()

    await _run_sync(_sync_unregister)
    logger.info("Deactivated device token", extra={"token_hash": hash(token)})
    return {"ok": True}


async def send_to_token(
    *,
    token: str,
    title: str,
    body: str,
    data: dict[str, str] | None = None,
    deep_link: str | None = None,
    image: str | None = None,
    type_key: str | None = None,
) -> dict[str, Any]:
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
            deep_link=deep_link,
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
                    "notification_id": notif["id"],
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
        logger.error("FCM send failed", extra={"status": e.response.status_code, "error": err_text}, exc_info=True)

        def _sync_record_failure():
            supa = _supa()
            supa.table("notification_deliveries").insert(
                {
                    "notification_id": notif["id"],
                    "status": "failed",
                    "error_code": err_text,
                }
            ).execute()
            if "UNREGISTERED" in err_text or "NotRegistered" in err_text:
                supa.table("device_tokens").update({"is_active": False}).eq("token", token).execute()

        await _run_sync(_sync_record_failure)
        raise


async def send_to_user(
    *,
    user_id: str,
    title: str,
    body: str,
    data: dict[str, str] | None = None,
    deep_link: str | None = None,
    type_key: str | None = None,
) -> dict[str, Any]:
    """Send a push notification to all active device tokens for a user.

    Best-effort: Supabase record/token failures return
    ``{ok: False, error: ...}`` instead of raising, so callers (notification
    dispatcher) can continue email/SMS channels. Per-token FCM failures are
    recorded individually; the overall call still returns ``ok: True`` with
    ``sent`` equal to the number of tokens attempted when the fan-out ran.
    """
    priority_label, ttl, priority_high = _get_type_config(type_key)
    payload_data = _augment_data_with_meta(
        data,
        type_key=type_key,
        channel=NotificationChannel.PUSH,
        priority=priority_label,
    )
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
        return {"ok": False, "sent": 0, "error": f"record_notification: {e}"}

    def _sync_get_tokens():
        supa = _supa()
        return (
            supa.table("device_tokens")
            .select("token,id")
            .eq("user_id", user_id)
            .eq("is_active", True)
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
            "notification_id": notif.get("id"),
            "error": f"device_tokens: {e}",
        }

    if not tokens:
        return {"ok": True, "sent": 0, "notification_id": notif["id"]}

    semaphore = asyncio.Semaphore(PUSH_FANOUT_CONCURRENCY)

    async def _send_one(t: dict[str, Any]):
        async with semaphore:
            tk = t["token"]
            tk_id = t["id"]
            try:
                msg = fcm.build_message(
                    token=tk,
                    title=title,
                    body=body,
                    data=payload_data,
                    deep_link=deep_link,
                    priority_high=priority_high,
                    ttl_seconds=ttl,
                )
                resp = await fcm.send_message(msg)

                def _sync_record_sent():
                    supa = _supa()
                    supa.table("notification_deliveries").insert(
                        {
                            "notification_id": notif["id"],
                            "device_token_id": tk_id,
                            "status": "sent",
                            "fcm_message_id": resp.get("name"),
                            "sent_at": utc_now_iso(),
                        }
                    ).execute()

                await _run_sync(_sync_record_sent)
            except Exception as e:  # broad to capture HTTP errors
                err = str(e)
                logger.warning("FCM send failed for token in send_to_user: %s", err, exc_info=True)

                def _sync_record_failed():
                    supa = _supa()
                    if "UNREGISTERED" in err or "NotRegistered" in err:
                        supa.table("device_tokens").update({"is_active": False}).eq("token", tk).execute()
                    supa.table("notification_deliveries").insert(
                        {
                            "notification_id": notif["id"],
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

    await asyncio.gather(*[_send_one(t) for t in tokens])
    return {"ok": True, "sent": len(tokens), "notification_id": notif.get("id")}


async def send_to_topic(
    *,
    topic: str,
    title: str,
    body: str,
    data: dict[str, str] | None = None,
    deep_link: str | None = None,
    type_key: str | None = None,
) -> dict[str, Any]:
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
        audience_type="topic",
        topic=topic,
    )
    try:
        msg = fcm.build_message(
            topic=topic,
            title=title,
            body=body,
            data=payload_data,
            deep_link=deep_link,
            priority_high=priority_high,
            ttl_seconds=ttl,
        )
        resp = await fcm.send_message(msg)

        def _sync_record_delivery():
            supa = _supa()
            supa.table("notification_deliveries").insert(
                {
                    "notification_id": notif["id"],
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
        logger.error("FCM topic send failed", extra={"status": e.response.status_code, "error": err_text}, exc_info=True)

        def _sync_record_failure():
            supa = _supa()
            supa.table("notification_deliveries").insert(
                {
                    "notification_id": notif["id"],
                    "status": "failed",
                    "error_code": err_text,
                }
            ).execute()

        await _run_sync(_sync_record_failure)
        raise


async def send_bulk(
    *,
    tokens: list[str],
    title: str,
    body: str,
    data: dict[str, str] | None = None,
    deep_link: str | None = None,
    type_key: str | None = None,
) -> dict[str, Any]:
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

    semaphore = asyncio.Semaphore(PUSH_FANOUT_CONCURRENCY)

    async def _send_one(tk: str):
        async with semaphore:
            try:
                msg = fcm.build_message(
                    token=tk,
                    title=title,
                    body=body,
                    data=payload_data,
                    deep_link=deep_link,
                    priority_high=priority_high,
                    ttl_seconds=ttl,
                )
                resp = await fcm.send_message(msg)

                def _sync_record_sent():
                    supa = _supa()
                    dev = supa.table("device_tokens").select("id").eq("token", tk).execute()
                    supa.table("notification_deliveries").insert(
                        {
                            "notification_id": notif["id"],
                            "device_token_id": (dev.data[0]["id"] if dev.data else None),
                            "status": "sent",
                            "fcm_message_id": resp.get("name"),
                            "sent_at": utc_now_iso(),
                        }
                    ).execute()

                await _run_sync(_sync_record_sent)
            except Exception as e:
                err = str(e)
                logger.warning("FCM send failed for token in send_bulk: %s", err, exc_info=True)

                def _sync_record_failed():
                    supa = _supa()
                    if "UNREGISTERED" in err or "NotRegistered" in err:
                        supa.table("device_tokens").update({"is_active": False}).eq("token", tk).execute()
                    supa.table("notification_deliveries").insert(
                        {
                            "notification_id": notif["id"],
                            "status": "failed",
                            "error_code": err,
                        }
                    ).execute()

                await _run_sync(_sync_record_failed)

    await asyncio.gather(*[_send_one(tk) for tk in tokens])
    return {"ok": True, "requested": len(tokens)}
