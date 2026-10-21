"""CRUD operations for notifications: record, list deliveries, mark a delivery read.

The inbox is a list of deliveries. A delivery is one notification sent to one
device, so its id is the read-state key. ``notifications.id`` is never a read key.
"""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from app.core.logging import get_logger
from app.core.utils import is_valid_uuid, utc_now_iso
from app.schemas.pagination import offset_payload, read_offset
from app.services.notification_config import NotificationChannel

from .helpers import _augment_data_with_meta, _run_sync, _supa

logger = get_logger(__name__)

_DELIVERY_SELECT = (
    "id,status,opened_at,created_at,"
    "notifications!inner(id,title,body,data,audience_type,target_user_id,topic,created_at)"
)


async def _record_notification(
    *,
    title: str,
    body: str,
    audience_type: Literal["user", "topic", "all", "segment", "tokens"],
    data: dict[str, Any] | None = None,
    target_user_id: str | None = None,
    topic: str | None = None,
) -> dict[str, Any]:
    def _sync_record():
        supa = _supa()
        res = (
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
        )
        if res.data:
            return res.data[0]
        return {
            "id": None,
            "title": title,
            "body": body,
            "data": data,
            "audience_type": audience_type,
            "target_user_id": target_user_id,
            "topic": topic,
        }

    return dict(await _run_sync(_sync_record))


async def record_in_app_notification(
    *,
    user_id: str,
    type_key: str,
    title: str,
    body: str,
    data: dict[str, str] | None = None,
    deep_link: str | None = None,
    notification_id: str | None = None,
) -> str | None:
    """Write one inbox row for a dispatch: an ``in_app`` delivery.

    ``notification_id`` is the notifications row of the same dispatch, written by
    the push send. When it is None, this function writes that row. A dispatch
    therefore has one notifications row, not one per channel.

    No device is needed, so a user with no push token still gets the row.
    Returns the delivery id, or None when the row was not written. Never raises.
    """
    if not is_valid_uuid(user_id):
        return None
    try:
        notif_id = notification_id
        if notif_id is None:
            payload_data = _augment_data_with_meta(
                data, type_key=type_key, channel=NotificationChannel.IN_APP
            )
            if deep_link:
                payload_data["route"] = deep_link
            notif = await _record_notification(
                title=title,
                body=body,
                data=payload_data,
                audience_type="user",
                target_user_id=user_id,
            )
            notif_id = notif.get("id")
        if not notif_id:
            return None

        def _sync_insert() -> str | None:
            res = (
                _supa()
                .table("notification_deliveries")
                .insert({"notification_id": notif_id, "status": "in_app", "sent_at": utc_now_iso()})
                .execute()
            )
            return str(res.data[0]["id"]) if res.data else None

        delivery_id: str | None = await _run_sync(_sync_insert)
        return delivery_id
    except Exception:
        logger.error("Failed to record in-app notification for user %s", user_id, exc_info=True)
        return None


def _flatten_delivery(row: dict[str, Any]) -> dict[str, Any]:
    """Turn a PostgREST delivery row with an embedded notification into one flat row."""
    notif = row.get("notifications") or {}
    data = notif.get("data") or {}
    meta = data.get("_meta") if isinstance(data, dict) else None
    type_key = meta.get("type_key") if isinstance(meta, dict) else None
    return {
        "id": str(row["id"]),
        "type": type_key,
        "title": notif.get("title") or "",
        "body": notif.get("body") or "",
        "data": data if isinstance(data, dict) else None,
        "created_at": row.get("created_at") or notif.get("created_at"),
        "read_at": row.get("opened_at"),
        "audience_type": notif.get("audience_type"),
        "topic": notif.get("topic"),
    }


async def list_deliveries_for_user(
    target_user_id: str,
    *,
    unread_only: bool = False,
    cursor_payload: dict[str, Any] | None = None,
    limit: int = 20,
    with_total: bool = False,
    in_app_only: bool = False,
) -> tuple[list[dict[str, Any]], dict[str, Any] | None, int | None, int]:
    """Return one page of a user's deliveries, newest first.

    Returns ``(rows, next_payload, total, unread_count)``. ``total`` is set only
    when ``with_total`` is true. ``unread_count`` is always the count of
    unopened deliveries for the user. ``in_app_only`` keeps the rows of the
    in-app inbox (one per dispatch) and drops per-device push rows. The inbox
    is selected by ``device_token_id IS NULL``, not by status, because opening a
    row changes its status. The read flag is ``opened_at``.
    """
    if not is_valid_uuid(target_user_id):
        return [], None, (0 if with_total else None), 0

    offset = read_offset(cursor_payload or {})

    def _sync_list() -> list[dict[str, Any]]:
        query = (
            _supa()
            .table("notification_deliveries")
            .select(_DELIVERY_SELECT)
            .eq("notifications.target_user_id", target_user_id)
            .order("created_at", desc=True)
        )
        if in_app_only:
            query = query.is_("device_token_id", "null")
        if unread_only:
            query = query.is_("opened_at", "null")
        res = query.range(offset, offset + limit).execute()
        return list(res.data or [])

    def _sync_count(unread: bool) -> int:
        query = (
            _supa()
            .table("notification_deliveries")
            .select("id,notifications!inner(id)", count="exact")
            .eq("notifications.target_user_id", target_user_id)
        )
        if in_app_only:
            query = query.is_("device_token_id", "null")
        if unread:
            query = query.is_("opened_at", "null")
        res = query.limit(1).execute()
        return int(res.count or 0)

    rows = await _run_sync(_sync_list)
    unread_count = await _run_sync(lambda: _sync_count(True))
    total = await _run_sync(lambda: _sync_count(unread_only)) if with_total else None

    next_pg: dict[str, Any] | None = None
    if len(rows) > limit:
        rows = rows[:limit]
        next_pg = offset_payload(offset + limit)

    return [_flatten_delivery(r) for r in rows], next_pg, total, unread_count


# Legacy list of the ``notifications`` table rows for a user. Kept unchanged for the
# flatmates in-app list, which still reads this table. Its read flag lives in
# notifications.data, not on the delivery. Move that list to list_deliveries_for_user.
async def list_notifications_for_user(
    target_user_id: str,
    *,
    cursor_payload: dict | None = None,
    limit: int = 50,
    with_total: bool = False,
) -> tuple[list[dict[str, Any]], dict | None, int | None]:
    """Return notifications for a given Supabase user id (offset-fallback pagination)."""
    from app.core.utils import is_valid_uuid

    # target_user_id is UUID in Supabase. Non-UUID seed placeholders must not query.
    if not is_valid_uuid(target_user_id):
        return [], None, 0 if with_total else None

    if cursor_payload is None:
        cursor_payload = {}

    offset = read_offset(cursor_payload)
    fetch_limit = limit + 1

    def _sync_list():
        supa = _supa()
        start = offset
        end = offset + max(fetch_limit, 1) - 1
        res = (
            supa.table("notifications")
            .select("id,title,body,data,audience_type,target_user_id,topic,created_at")
            .eq("target_user_id", target_user_id)
            .order("created_at", desc=True)
            .range(start, end)
            .execute()
        )
        return res.data or []

    rows: list[dict[str, Any]] = list(await _run_sync(_sync_list))

    count_total: int | None = None
    if with_total:

        def _sync_count():
            supa = _supa()
            res = (
                supa.table("notifications")
                .select("id", count="exact")
                .eq("target_user_id", target_user_id)
                .execute()
            )
            return res.count or 0

        count_total = int(await _run_sync(_sync_count))

    next_pg: dict | None = None
    if len(rows) > limit:
        rows = rows[:limit]
        next_pg = offset_payload(offset + limit)

    return rows, next_pg, count_total


async def mark_delivery_opened(
    delivery_id: str,
    *,
    user_supabase_id: str | None,
) -> dict[str, Any]:
    """Mark one delivery as read for its owner.

    The owner is the target user of the notification, or the user of the device
    the delivery went to. Any other caller gets ``forbidden``. A second call
    keeps the first ``read_at``.
    """
    if not user_supabase_id:
        return {"ok": False, "error": "unauthenticated"}
    try:
        UUID(delivery_id)
    except (ValueError, AttributeError):
        return {"ok": False, "error": "not_found"}

    def _sync_mark_opened() -> dict[str, Any]:
        supa = _supa()
        delivery_res = (
            supa.table("notification_deliveries")
            .select("id,notification_id,device_token_id,opened_at")
            .eq("id", delivery_id)
            .limit(1)
            .execute()
        )
        if not delivery_res.data:
            return {"ok": False, "error": "not_found"}

        delivery = delivery_res.data[0]
        owner_ids: set[str | None] = set()
        if delivery.get("notification_id"):
            notif_res = (
                supa.table("notifications")
                .select("target_user_id")
                .eq("id", delivery["notification_id"])
                .limit(1)
                .execute()
            )
            if notif_res.data:
                owner_ids.add(notif_res.data[0].get("target_user_id"))
        if delivery.get("device_token_id"):
            token_res = (
                supa.table("device_tokens")
                .select("user_id")
                .eq("id", delivery["device_token_id"])
                .limit(1)
                .execute()
            )
            if token_res.data:
                owner_ids.add(token_res.data[0].get("user_id"))

        if user_supabase_id not in owner_ids:
            return {"ok": False, "error": "forbidden"}

        if delivery.get("opened_at"):
            return {"ok": True, "delivery_id": delivery_id, "read_at": delivery["opened_at"]}

        read_at = utc_now_iso()
        supa.table("notification_deliveries").update({"status": "opened", "opened_at": read_at}).eq(
            "id", delivery_id
        ).execute()
        return {"ok": True, "delivery_id": delivery_id, "read_at": read_at}

    return dict(await _run_sync(_sync_mark_opened))
