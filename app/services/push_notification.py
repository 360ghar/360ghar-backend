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
from app.models.enums import AppKey
from app.services.deeplinks import get_app

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _chat_route(identifier: int) -> str:
    """Flatmates chat route. The path comes from the deep-link registry, the single source."""
    app = get_app("flatmates")
    if app is None:  # pragma: no cover - the registry always defines flatmates
        raise RuntimeError("flatmates app missing from the deep-link registry")
    return app.https_path("chat", str(identifier))


async def _dispatch(
    db: AsyncSession,
    *,
    user_db_id: int,
    type_key: str,
    title: str,
    body: str,
    data: dict[str, str] | None = None,
    deep_link: str | None = None,
    realtime_publish_immediately: bool = False,
) -> dict[str, Any]:
    """Dispatch a notification through the existing notification pipeline.

    Falls back to a log-only stub when the dispatcher is unavailable.
    """
    from app.services.flatmates.realtime import (
        EVENT_NEW_NOTIFICATION,
        FlatmatesRealtimeEvent,
        publish_flatmates_realtime_event,
        queue_flatmates_realtime_event,
    )

    realtime_event = FlatmatesRealtimeEvent(
        user_id=user_db_id,
        event_type=EVENT_NEW_NOTIFICATION,
        payload={
            "type_key": type_key,
            "title": title,
            "body": body,
            "route": deep_link,
        },
    )

    if not realtime_publish_immediately:
        queue_flatmates_realtime_event(
            db,
            user_id=user_db_id,
            event_type=EVENT_NEW_NOTIFICATION,
            payload=realtime_event.payload,
        )

    try:
        from app.services.notification_dispatcher import dispatch_notification_to_user

        async with db.begin_nested():
            result = await dispatch_notification_to_user(
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
        result = {"ok": False, "fallback": True, "type_key": type_key}

    if realtime_publish_immediately:
        await publish_flatmates_realtime_event(realtime_event)

    return result


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
            app_key=AppKey.flatmates,
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

    Deep-link route: the flatmates chat path from the deep-link registry.
    """
    return await _dispatch(
        db,
        user_db_id=recipient_db_id,
        type_key="flatmate_new_message",
        title=sender_name,
        body="Sent you a message",
        deep_link=_chat_route(conversation_id),
    )


async def notify_new_match(
    db: AsyncSession,
    *,
    recipient_db_id: int,
    peer_name: str,
    match_id: int,
) -> dict[str, Any]:
    """Notify a user about a new flatmate match.

    No deep link yet. The chat route needs the conversation id, not match_id.
    The match detail opens the conversation.
    """
    return await _dispatch(
        db,
        user_db_id=recipient_db_id,
        type_key="flatmate_new_match",
        title="New Match!",
        body=f"You matched with {peer_name}",
        deep_link=None,
    )


async def notify_listing_approved(
    db: AsyncSession,
    *,
    recipient_db_id: int,
    listing_title: str,
    boosted_for_hours: int | None = None,
    realtime_publish_immediately: bool = False,
) -> dict[str, Any]:
    """Notify a listing owner that their flatmate listing was approved.

    No deep link. The flatmates app has no /post route.
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
        deep_link=None,
        realtime_publish_immediately=realtime_publish_immediately,
    )


async def notify_visit_scheduled(
    db: AsyncSession,
    *,
    recipient_db_id: int,
    property_title: str,
    scheduled_date: str,
) -> dict[str, Any]:
    """Notify a user that a visit/meet has been scheduled.

    No deep link. The flatmates app has no /visits route.
    """
    return await _dispatch(
        db,
        user_db_id=recipient_db_id,
        type_key="flatmate_visit_scheduled",
        title="Visit Scheduled",
        body=f"Visit for {property_title} on {scheduled_date}",
        deep_link=None,
    )


async def notify_visit_confirmed(
    db: AsyncSession,
    *,
    recipient_db_id: int,
    property_title: str,
    scheduled_date: str,
) -> dict[str, Any]:
    """Notify a user that a visit/meet has been confirmed.

    No deep link. The flatmates app has no /visits route.
    """
    return await _dispatch(
        db,
        user_db_id=recipient_db_id,
        type_key="flatmate_visit_confirmed",
        title="Visit Confirmed",
        body=f"Visit for {property_title} on {scheduled_date} is confirmed",
        deep_link=None,
    )
