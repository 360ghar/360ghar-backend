from __future__ import annotations

from typing import Dict, List, Optional, Literal, Any, Tuple
import os
import asyncio
from datetime import datetime

import httpx

from app.core.config import settings
from app.core.auth import get_supabase_service_client
from app.core.logging import get_logger
from app.services.notification_config import (
    NOTIFICATION_TYPES,
    NotificationChannel,
    NotificationPriority,
)

logger = get_logger(__name__)

FCM_SCOPE = "https://www.googleapis.com/auth/firebase.messaging"


def _access_token() -> str:
    """Create an OAuth2 access token from the service account file.

    Requires settings.GOOGLE_APPLICATION_CREDENTIALS and settings.FIREBASE_PROJECT_ID.
    """
    # Lazy import to avoid hard dependency at app import time
    from google.oauth2 import service_account  # type: ignore
    from google.auth.transport.requests import Request  # type: ignore
    if not settings.FIREBASE_PROJECT_ID:
        raise RuntimeError("FIREBASE_PROJECT_ID is not configured")
    creds_path = settings.GOOGLE_APPLICATION_CREDENTIALS
    if not creds_path or not os.path.exists(creds_path):
        raise RuntimeError("GOOGLE_APPLICATION_CREDENTIALS path is invalid or missing")
    creds = service_account.Credentials.from_service_account_file(
        creds_path,
        scopes=[FCM_SCOPE],
    )
    creds.refresh(Request())
    return creds.token


def _get_type_config(type_key: Optional[str]) -> Tuple[Optional[str], Optional[int], bool]:
    """Resolve priority label, TTL, and priority_high flag for a type key.

    Falls back to a safe default if the type is unknown.
    """
    if not type_key:
        return None, None, True
    cfg = NOTIFICATION_TYPES.get(type_key)
    if not cfg:
        return None, None, True
    ttl = cfg.default_ttl_seconds
    priority_high = cfg.priority in {NotificationPriority.HIGH, NotificationPriority.CRITICAL}
    return cfg.priority.value, ttl, priority_high


def _augment_data_with_meta(
    data: Optional[Dict[str, Any]],
    *,
    type_key: Optional[str],
    channel: NotificationChannel,
    priority: Optional[str] = None,
) -> Dict[str, Any]:
    """Attach metadata about the notification into the data payload.

    Metadata is nested under a reserved `_meta` key to avoid clashing with
    domain-specific data fields.
    """
    base: Dict[str, Any] = dict(data or {})
    meta = base.get("_meta") or {}
    meta.update(
        {
            "type_key": type_key,
            "channel": channel.value,
        }
    )
    if priority:
        meta["priority"] = priority
    base["_meta"] = meta
    return base


def build_message(
    *,
    token: Optional[str] = None,
    topic: Optional[str] = None,
    title: Optional[str] = None,
    body: Optional[str] = None,
    data: Optional[Dict[str, str]] = None,
    deep_link: Optional[str] = None,
    image: Optional[str] = None,
    priority_high: bool = True,
    content_available: bool = False,
    ttl_seconds: Optional[int] = None,
) -> Dict[str, Any]:
    """Build an FCM HTTP v1 message payload.

    Supports notification+data and data-only content (iOS background).
    """
    data = data or {}
    if deep_link:
        data["deep_link"] = deep_link

    msg: Dict[str, Any] = {"message": {}}
    if token:
        msg["message"]["token"] = token
    elif topic:
        msg["message"]["topic"] = topic
    else:
        raise ValueError("Either token or topic must be provided")

    if title or body or image:
        msg["message"]["notification"] = {
            k: v for k, v in [("title", title), ("body", body), ("image", image)] if v
        }

    if data:
        msg["message"]["data"] = {k: str(v) for k, v in data.items()}

    if priority_high or ttl_seconds is not None:
        android_cfg: Dict[str, Any] = msg["message"].get("android") or {}
        if priority_high:
            android_cfg["priority"] = "HIGH"
            android_cfg["notification"] = {"channel_id": "high_importance_channel"}
        if ttl_seconds is not None:
            android_cfg["ttl"] = f"{int(ttl_seconds)}s"
        if android_cfg:
            msg["message"]["android"] = android_cfg

    # APNs headers for alert vs background
    apns_headers = {"apns-priority": "10", "apns-push-type": "alert"}
    aps_payload: Dict[str, Any] = {"sound": "default"}
    if content_available:
        apns_headers = {"apns-priority": "5", "apns-push-type": "background"}
        aps_payload = {"content-available": 1}
    msg["message"]["apns"] = {
        "headers": apns_headers,
        "payload": {"aps": aps_payload},
    }

    return msg


async def send_message(message: Dict[str, Any]) -> Dict[str, Any]:
    """Send a single FCM HTTP v1 message."""
    token = _access_token()
    project_id = settings.FIREBASE_PROJECT_ID
    url = f"https://fcm.googleapis.com/v1/projects/{project_id}/messages:send"
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(url, headers={"Authorization": f"Bearer {token}"}, json=message)
        resp.raise_for_status()
        return resp.json()


# Supabase integration helpers
def _supa():
    return get_supabase_service_client()


async def register_device_token(
    *,
    token: str,
    platform: Literal["android", "ios", "web"],
    user_id: Optional[str] = None,
    app_version: Optional[str] = None,
    locale: Optional[str] = None,
) -> Dict[str, Any]:
    """Upsert a device token in Supabase device_tokens."""
    supa = _supa()
    now_iso = datetime.utcnow().isoformat()
    existing = supa.table("device_tokens").select("id").eq("token", token).execute()
    if existing.data:
        supa.table("device_tokens").update(
            {
                "user_id": user_id,
                "platform": platform,
                "app_version": app_version,
                "locale": locale,
                "is_active": True,
                "last_seen": now_iso,
            }
        ).eq("token", token).execute()
        logger.info("Updated existing device token", extra={"token_hash": hash(token), "user_id": user_id})
    else:
        supa.table("device_tokens").insert(
            {
                "token": token,
                "user_id": user_id,
                "platform": platform,
                "app_version": app_version,
                "locale": locale,
                "is_active": True,
                "last_seen": now_iso,
            }
        ).execute()
        logger.info("Inserted new device token", extra={"token_hash": hash(token), "user_id": user_id})
    return {"ok": True}


async def unregister_device_token(*, token: str) -> Dict[str, Any]:
    """Deactivate a device token in Supabase device_tokens."""
    supa = _supa()
    now_iso = datetime.utcnow().isoformat()
    supa.table("device_tokens").update(
        {
            "is_active": False,
            "last_seen": now_iso,
        }
    ).eq("token", token).execute()
    logger.info("Deactivated device token", extra={"token_hash": hash(token)})
    return {"ok": True}


async def _record_notification(
    *,
    title: str,
    body: str,
    audience_type: Literal["user", "topic", "all", "segment", "tokens"],
    data: Optional[Dict[str, Any]] = None,
    target_user_id: Optional[str] = None,
    topic: Optional[str] = None,
) -> Dict[str, Any]:
    supa = _supa()
    rec = (
        supa.table("notifications")
        .insert(
            {
                "title": title,
                "body": body,
                "data": data,
                "audience_type": audience_type,
                "target_user_id": target_user_id,
                "topic": topic,
            }
        )
        .execute()
        .data[0]
    )
    return rec


async def list_notifications_for_user(
    target_user_id: str,
    *,
    limit: int = 50,
    offset: int = 0,
) -> List[Dict[str, Any]]:
    """Return notifications for a given Supabase user id."""
    supa = _supa()
    # Supabase range is inclusive; compute end index accordingly.
    start = offset
    end = offset + max(limit, 1) - 1
    res = (
        supa.table("notifications")
        .select(
            "id,title,body,data,audience_type,target_user_id,topic,created_at"
        )
        .eq("target_user_id", target_user_id)
        .order("created_at", desc=True)
        .range(start, end)
        .execute()
    )
    return res.data or []


async def send_to_token(
    *,
    token: str,
    title: str,
    body: str,
    data: Optional[Dict[str, str]] = None,
    deep_link: Optional[str] = None,
    image: Optional[str] = None,
    type_key: Optional[str] = None,
) -> Dict[str, Any]:
    supa = _supa()
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
        msg = build_message(
            token=token,
            title=title,
            body=body,
            data=payload_data,
            deep_link=deep_link,
            image=image,
            priority_high=priority_high,
            ttl_seconds=ttl,
        )
        resp = await send_message(msg)
        dev = supa.table("device_tokens").select("id").eq("token", token).execute()
        supa.table("notification_deliveries").insert(
            {
                "notification_id": notif["id"],
                "device_token_id": (dev.data[0]["id"] if dev.data else None),
                "status": "sent",
                "fcm_message_id": resp.get("name"),
                "sent_at": datetime.utcnow().isoformat(),
            }
        ).execute()
        return {"ok": True, "fcm": resp}
    except httpx.HTTPStatusError as e:
        err_text = e.response.text
        logger.error("FCM send failed", extra={"status": e.response.status_code, "error": err_text})
        supa.table("notification_deliveries").insert(
            {
                "notification_id": notif["id"],
                "status": "failed",
                "error_code": err_text,
            }
        ).execute()
        # Deactivate on UNREGISTERED
        if "UNREGISTERED" in err_text or "NotRegistered" in err_text:
            supa.table("device_tokens").update({"is_active": False}).eq("token", token).execute()
        raise


async def send_to_user(
    *,
    user_id: str,
    title: str,
    body: str,
    data: Optional[Dict[str, str]] = None,
    deep_link: Optional[str] = None,
    type_key: Optional[str] = None,
) -> Dict[str, Any]:
    supa = _supa()
    tokens = (
        supa.table("device_tokens").select("token,id").eq("user_id", user_id).eq("is_active", True).execute().data
    )
    if not tokens:
        return {"ok": True, "sent": 0}
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
        audience_type="user",
        target_user_id=user_id,
    )

    async def _send_one(t: Dict[str, Any]):
        tk = t["token"]
        tk_id = t["id"]
        try:
            msg = build_message(
                token=tk,
                title=title,
                body=body,
                data=payload_data,
                deep_link=deep_link,
                priority_high=priority_high,
                ttl_seconds=ttl,
            )
            resp = await send_message(msg)
            supa.table("notification_deliveries").insert(
                {
                    "notification_id": notif["id"],
                    "device_token_id": tk_id,
                    "status": "sent",
                    "fcm_message_id": resp.get("name"),
                    "sent_at": datetime.utcnow().isoformat(),
                }
            ).execute()
        except Exception as e:  # broad to capture HTTP errors
            err = str(e)
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

    await asyncio.gather(*[_send_one(t) for t in tokens])
    return {"ok": True, "sent": len(tokens)}


async def send_to_topic(
    *,
    topic: str,
    title: str,
    body: str,
    data: Optional[Dict[str, str]] = None,
    deep_link: Optional[str] = None,
    type_key: Optional[str] = None,
) -> Dict[str, Any]:
    supa = _supa()
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
    msg = build_message(
        topic=topic,
        title=title,
        body=body,
        data=payload_data,
        deep_link=deep_link,
        priority_high=priority_high,
        ttl_seconds=ttl,
    )
    resp = await send_message(msg)
    supa.table("notification_deliveries").insert(
        {
            "notification_id": notif["id"],
            "status": "sent",
            "fcm_message_id": resp.get("name"),
            "sent_at": datetime.utcnow().isoformat(),
        }
    ).execute()
    return {"ok": True, "fcm": resp}


async def send_bulk(
    *,
    tokens: List[str],
    title: str,
    body: str,
    data: Optional[Dict[str, str]] = None,
    deep_link: Optional[str] = None,
    type_key: Optional[str] = None,
) -> Dict[str, Any]:
    supa = _supa()
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

    async def _send_one(tk: str):
        try:
            msg = build_message(
                token=tk,
                title=title,
                body=body,
                data=payload_data,
                deep_link=deep_link,
                priority_high=priority_high,
                ttl_seconds=ttl,
            )
            resp = await send_message(msg)
            dev = supa.table("device_tokens").select("id").eq("token", tk).execute()
            supa.table("notification_deliveries").insert(
                {
                    "notification_id": notif["id"],
                    "device_token_id": (dev.data[0]["id"] if dev.data else None),
                    "status": "sent",
                    "fcm_message_id": resp.get("name"),
                    "sent_at": datetime.utcnow().isoformat(),
                }
            ).execute()
        except Exception as e:
            err = str(e)
            if "UNREGISTERED" in err or "NotRegistered" in err:
                supa.table("device_tokens").update({"is_active": False}).eq("token", tk).execute()
            supa.table("notification_deliveries").insert(
                {
                    "notification_id": notif["id"],
                    "status": "failed",
                    "error_code": err,
                }
            ).execute()

    await asyncio.gather(*[_send_one(tk) for tk in tokens])
    return {"ok": True, "requested": len(tokens)}


async def mark_delivery_opened(
    delivery_id: str,
    *,
    user_supabase_id: Optional[str],
) -> Dict[str, Any]:
    """Mark a notification delivery as opened, verifying user ownership when possible."""
    if not user_supabase_id:
        return {"ok": False, "error": "unauthenticated"}

    supa = _supa()
    delivery_res = (
        supa.table("notification_deliveries")
        .select("notification_id,device_token_id")
        .eq("id", delivery_id)
        .limit(1)
        .execute()
    )
    if not delivery_res.data:
        return {"ok": False, "error": "not_found"}

    delivery = delivery_res.data[0]
    notification_id = delivery.get("notification_id")
    device_token_id = delivery.get("device_token_id")

    owner_ids = set()
    if notification_id:
        notif_res = (
            supa.table("notifications")
            .select("target_user_id")
            .eq("id", notification_id)
            .limit(1)
            .execute()
        )
        if notif_res.data:
            owner_ids.add(notif_res.data[0].get("target_user_id"))

    if device_token_id:
        token_res = (
            supa.table("device_tokens")
            .select("user_id")
            .eq("id", device_token_id)
            .limit(1)
            .execute()
        )
        if token_res.data:
            owner_ids.add(token_res.data[0].get("user_id"))

    # If we can determine ownership, enforce it
    if owner_ids and user_supabase_id not in owner_ids:
        return {"ok": False, "error": "forbidden"}

    supa.table("notification_deliveries").update(
        {"status": "opened", "opened_at": datetime.utcnow().isoformat()}
    ).eq("id", delivery_id).execute()
    return {"ok": True}
