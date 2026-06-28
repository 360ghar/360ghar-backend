"""CRUD operations for notifications (create, list, mark opened)."""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from app.core.logging import get_logger
from app.core.utils import utc_now_iso
from app.schemas.pagination import offset_payload, read_offset

from .helpers import _run_sync, _supa

logger = get_logger(__name__)


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


async def list_notifications_for_user(
    target_user_id: str,
    *,
    cursor_payload: dict | None = None,
    limit: int = 50,
    with_total: bool = False,
) -> tuple[list[dict[str, Any]], dict | None, int | None]:
    """Return notifications for a given Supabase user id (offset-fallback pagination)."""
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
    """Mark a notification delivery as opened, verifying user ownership when possible."""
    if not user_supabase_id:
        return {"ok": False, "error": "unauthenticated"}
    try:
        UUID(delivery_id)
    except (ValueError, AttributeError):
        return {"ok": False, "error": "not_found"}

    def _sync_mark_opened():
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
            {"status": "opened", "opened_at": utc_now_iso()}
        ).eq("id", delivery_id).execute()
        return {"ok": True}

    return dict(await _run_sync(_sync_mark_opened))
