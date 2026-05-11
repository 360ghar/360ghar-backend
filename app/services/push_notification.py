"""
Flatmates push notification dispatch service.

Provides convenience helpers for sending FCM push notifications for key
flatmates events (new message, new match, listing approved, visit
scheduled/confirmed).

Each notification includes a ``route`` data field for deep-link navigation
on the mobile client.

If the FCM infrastructure (notification_dispatcher) is unavailable at
runtime (e.g. missing FIREBASE_PROJECT_ID), notifications are logged
as a fallback so the app never crashes.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _dispatch(
    db: AsyncSession,
    *,
    user_db_id: int,
    type_key: str,
    title: str,
    body: str,
    data: dict[str, str] | None = None,
    deep_link: str | None = None,
) -> dict[str, Any]:
    """Dispatch a notification through the existing notification pipeline.

    Falls back to a log-only stub when the dispatcher is unavailable.
    """
    # --- SSE event to user (always fire, even if FCM is down) ---
    try:
        from app.core.sse import sse_bus

        await sse_bus.emit(
            user_db_id,
            {
                "type": "new_notification",
                "type_key": type_key,
                "title": title,
                "body": body,
                "route": (data or {}).get("route"),
            },
        )
    except Exception:  # noqa: BLE001
        pass  # best-effort

    try:
        from app.services.notification_dispatcher import dispatch_notification_to_user

        return await dispatch_notification_to_user(
            db,
            user_db_id=user_db_id,
            type_key=type_key,
            title=title,
            body=body,
            data=data,
            deep_link=deep_link,
        )
    except Exception:
        logger.warning(
            "Push notification dispatch failed (stub fallback)",
            extra={
                "user_db_id": user_db_id,
                "type_key": type_key,
                "title": title,
                "body": body,
            },
        )
        return {"ok": False, "fallback": True, "type_key": type_key}


# ---------------------------------------------------------------------------
# Public API -- generic send
# ---------------------------------------------------------------------------


async def send_push_notification(
    db: AsyncSession,
    *,
    fcm_token: str,
    title: str,
    body: str,
    data: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Send a raw FCM push notification to a specific device token.

    This is the lowest-level entry point; prefer the typed helpers below
    for domain events.
    """
    try:
        from app.services.notifications import send_to_token

        return await send_to_token(
            token=fcm_token,
            title=title,
            body=body,
            data=data,
        )
    except Exception:
        logger.warning(
            "FCM send_to_token failed (stub fallback)",
            extra={"title": title, "body": body},
        )
        return {"ok": False, "fallback": True}


# ---------------------------------------------------------------------------
# Public API -- flatmates domain helpers
# ---------------------------------------------------------------------------


async def notify_new_message(
    db: AsyncSession,
    *,
    recipient_db_id: int,
    sender_name: str,
    conversation_id: int,
) -> dict[str, Any]:
    """Notify a user that they received a new chat message.

    Deep-link route: ``/chats/{conversation_id}``
    """
    return await _dispatch(
        db,
        user_db_id=recipient_db_id,
        type_key="flatmate_new_message",
        title=sender_name,
        body="Sent you a message",
        data={"route": f"/chats/{conversation_id}"},
        deep_link=f"/chats/{conversation_id}",
    )


async def notify_new_match(
    db: AsyncSession,
    *,
    recipient_db_id: int,
    peer_name: str,
    match_id: int,
) -> dict[str, Any]:
    """Notify a user about a new flatmate match.

    Deep-link route: ``/chats/{match_id}`` (the conversation is opened
    from the match detail).
    """
    return await _dispatch(
        db,
        user_db_id=recipient_db_id,
        type_key="flatmate_new_match",
        title="New Match!",
        body=f"You matched with {peer_name}",
        data={"route": f"/chats/{match_id}"},
        deep_link=f"/chats/{match_id}",
    )


async def notify_listing_approved(
    db: AsyncSession,
    *,
    recipient_db_id: int,
    listing_title: str,
    boosted_for_hours: int | None = None,
) -> dict[str, Any]:
    """Notify a listing owner that their flatmate listing was approved.

    Deep-link route: ``/post``
    """
    body = f'Your listing "{listing_title}" is now live'
    if boosted_for_hours:
        body = f"{body} and boosted for {boosted_for_hours} hours"
    return await _dispatch(
        db,
        user_db_id=recipient_db_id,
        type_key="flatmate_listing_approved",
        title="Listing Approved",
        body=body,
        data={"route": "/post"},
        deep_link="/post",
    )


async def notify_visit_scheduled(
    db: AsyncSession,
    *,
    recipient_db_id: int,
    property_title: str,
    scheduled_date: str,
) -> dict[str, Any]:
    """Notify a user that a visit/meet has been scheduled.

    Deep-link route: ``/visits``
    """
    return await _dispatch(
        db,
        user_db_id=recipient_db_id,
        type_key="flatmate_visit_scheduled",
        title="Visit Scheduled",
        body=f"Visit for {property_title} on {scheduled_date}",
        data={"route": "/visits"},
        deep_link="/visits",
    )


async def notify_visit_confirmed(
    db: AsyncSession,
    *,
    recipient_db_id: int,
    property_title: str,
    scheduled_date: str,
) -> dict[str, Any]:
    """Notify a user that a visit/meet has been confirmed.

    Deep-link route: ``/visits``
    """
    return await _dispatch(
        db,
        user_db_id=recipient_db_id,
        type_key="flatmate_visit_confirmed",
        title="Visit Confirmed",
        body=f"Visit for {property_title} on {scheduled_date} is confirmed",
        data={"route": "/visits"},
        deep_link="/visits",
    )
