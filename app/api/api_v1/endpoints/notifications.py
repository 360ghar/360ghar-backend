from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.api_v1.dependencies.auth import (
    get_current_active_user,
    get_current_admin,
    get_current_user_optional,
)
from app.config import settings
from app.core.database import get_db
from app.core.db_resilience import (
    apply_statement_timeout,
    raise_read_service_unavailable,
)
from app.core.exceptions import (
    ConflictException,
    ForbiddenException,
    NotFoundException,
    UnauthorizedException,
)
from app.models.enums import AppKey, DevicePlatform, UserRole
from app.schemas.base import UtcDateTime, WriteModel
from app.schemas.pagination import CursorPage, CursorParams, build_cursor_page
from app.schemas.user import User as UserSchema
from app.services.notification_config import MarketingTypeKey, NotificationTypeKey
from app.services.notification_dispatcher import (
    count_users_for_segment,
    dispatch_notification_to_user,
    dispatch_notification_to_users,
    find_user_ids_for_segment,
)
from app.services.notifications import (
    list_deliveries_for_user,
    mark_delivery_opened,
    register_device_token,
    unregister_device_token,
)

router = APIRouter()

# Recipients per dispatch batch for a marketing send. Each batch is awaited in turn.
MARKETING_BATCH_SIZE = 200


# ---------------------------------------------------------------------------
# Device tokens
# ---------------------------------------------------------------------------


class DeviceRegisterIn(WriteModel):
    """Register a push token. The owner comes from the bearer token, never from the body."""

    token: str = Field(min_length=1, max_length=4096)
    platform: DevicePlatform
    app_key: AppKey
    app_version: str | None = Field(default=None, max_length=64)
    locale: str | None = Field(default=None, max_length=32)


class DeviceRegistration(BaseModel):
    platform: DevicePlatform
    app_key: AppKey
    app_version: str | None = None
    locale: str | None = None
    last_seen: UtcDateTime


@router.post(
    "/devices/register",
    status_code=status.HTTP_201_CREATED,
    response_model=DeviceRegistration,
    summary="Register notification device",
)
async def devices_register(
    payload: DeviceRegisterIn,
    current_user: UserSchema | None = Depends(get_current_user_optional),
) -> DeviceRegistration:
    """Register a push token for the caller's app.

    A signed-in caller binds the token to its own user. An anonymous caller
    cannot change a token that belongs to a user.
    """
    user_id = getattr(current_user, "supabase_user_id", None) if current_user else None
    result = await register_device_token(
        token=payload.token,
        platform=payload.platform,
        app_key=payload.app_key,
        user_id=user_id,
        app_version=payload.app_version,
        locale=payload.locale,
    )
    return DeviceRegistration(**result)


class DeviceUnregisterIn(WriteModel):
    token: str = Field(min_length=1, max_length=4096)


@router.delete(
    "/devices/unregister",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Unregister notification device",
)
async def devices_unregister(
    payload: DeviceUnregisterIn,
    current_user: UserSchema = Depends(get_current_active_user),
) -> None:
    """Deactivate one of the caller's own device tokens. Other users' tokens are not changed."""
    user_id = getattr(current_user, "supabase_user_id", None)
    if not user_id:
        raise UnauthorizedException(detail="Authentication required")
    await unregister_device_token(token=payload.token, user_id=user_id)


# ---------------------------------------------------------------------------
# Inbox (read state is per delivery)
# ---------------------------------------------------------------------------


class NotificationItem(BaseModel):
    """One delivery of a notification. ``id`` is the delivery id, the read-state key."""

    id: str
    type: str | None = None
    title: str
    body: str
    data: dict[str, Any] | None = None
    created_at: UtcDateTime | None = None
    read_at: UtcDateTime | None = None


class NotificationPage(CursorPage[NotificationItem]):
    unread_count: int = Field(description="Deliveries the caller has not opened.")


@router.get("/me", response_model=NotificationPage, summary="List my notifications")
async def list_my_notifications(
    page: CursorParams = Depends(),
    unread_only: bool = Query(False),
    current_user: UserSchema = Depends(get_current_active_user),
) -> NotificationPage:
    """Return the caller's in-app inbox, newest first. One row per notification, with or without a device."""
    filters = {"unread_only": unread_only}
    cursor_payload = page.decoded(filters)
    user_id = getattr(current_user, "supabase_user_id", None)
    if not user_id:
        return NotificationPage(
            items=[], limit=page.limit, unread_count=0, total=0 if page.include_total else None
        )
    try:
        rows, next_payload, total, unread_count = await list_deliveries_for_user(
            user_id,
            unread_only=unread_only,
            cursor_payload=cursor_payload,
            limit=page.limit,
            with_total=page.include_total,
            in_app_only=True,
        )
    except Exception as exc:
        raise_read_service_unavailable(
            exc,
            endpoint="notifications_me",
            detail="Notifications are temporarily unavailable. Please retry shortly.",
        )
        raise
    base = build_cursor_page(
        [NotificationItem(**row) for row in rows],
        limit=page.limit,
        next_payload=next_payload,
        total=total,
        filters=filters,
    )
    return NotificationPage(**base, unread_count=unread_count)


class DeliveryReadOut(BaseModel):
    delivery_id: str
    read_at: UtcDateTime


@router.post(
    "/deliveries/{delivery_id}/opened",
    response_model=DeliveryReadOut,
    summary="Mark delivery as opened",
)
async def delivery_opened(
    delivery_id: str,
    current_user: UserSchema = Depends(get_current_active_user),
) -> DeliveryReadOut:
    """Mark one of the caller's deliveries as read. A second call keeps the first read time."""
    res = await mark_delivery_opened(
        delivery_id,
        user_supabase_id=getattr(current_user, "supabase_user_id", None),
    )
    if not res.get("ok"):
        if res.get("error") == "not_found":
            raise NotFoundException(detail="Delivery not found", error_code="DELIVERY_NOT_FOUND")
        if res.get("error") == "forbidden":
            raise ForbiddenException(detail="Not allowed to update this notification")
        raise UnauthorizedException(detail="Authentication required")
    return DeliveryReadOut(delivery_id=res["delivery_id"], read_at=res["read_at"])


@router.get(
    "/users/{user_id}",
    response_model=CursorPage[NotificationItem],
    summary="List user notifications",
)
async def list_user_notifications(
    user_id: int,
    page: CursorParams = Depends(),
    _: UserSchema = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> CursorPage[NotificationItem]:
    """Admin: the deliveries of one user, by DB id."""
    from app.models.users import User as UserModel

    filters: dict[str, Any] = {}
    try:
        await apply_statement_timeout(db, settings.DB_READ_STATEMENT_TIMEOUT_MS)
        supabase_user_id = (
            await db.execute(select(UserModel.supabase_user_id).where(UserModel.id == user_id))
        ).scalar_one_or_none()
    except Exception as exc:
        raise_read_service_unavailable(
            exc,
            endpoint="notifications_user_list",
            detail="Notifications are temporarily unavailable. Please retry shortly.",
            extra={"target_user": user_id},
        )
        raise
    if not supabase_user_id:
        raise NotFoundException(
            detail="User not found or not linked to Supabase", error_code="USER_NOT_FOUND"
        )
    try:
        rows, next_payload, total, _unread = await list_deliveries_for_user(
            supabase_user_id,
            cursor_payload=page.decoded(filters),
            limit=page.limit,
            with_total=page.include_total,
        )
    except Exception as exc:
        raise_read_service_unavailable(
            exc,
            endpoint="notifications_user_list",
            detail="Notifications are temporarily unavailable. Please retry shortly.",
            extra={"target_user": user_id},
        )
        raise
    return CursorPage[NotificationItem](
        **build_cursor_page(
            [NotificationItem(**row) for row in rows],
            limit=page.limit,
            next_payload=next_payload,
            total=total,
            filters=filters,
        )
    )


# ---------------------------------------------------------------------------
# Admin sends. Every send goes through the consent gate of the dispatcher.
# ---------------------------------------------------------------------------


class ChannelOutcome(BaseModel):
    ok: bool
    sent: int | None = None
    error: str | None = None


class NotificationDispatchResult(BaseModel):
    type_key: str
    title: str
    body: str
    sent_at: UtcDateTime
    channels: dict[str, ChannelOutcome]
    error: str | None = None


class TypedUserNotification(WriteModel):
    user_id: int
    type_key: NotificationTypeKey
    title: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=1000)
    data: dict[str, str] | None = None
    deep_link: str | None = Field(default=None, max_length=512)


@router.post(
    "/send/typed/user",
    response_model=NotificationDispatchResult,
    summary="Send typed notification to user",
)
async def send_typed_user(
    req: TypedUserNotification,
    _: UserSchema = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> NotificationDispatchResult:
    """Send a typed, multi-channel notification to one user by DB id."""
    result = await dispatch_notification_to_user(
        db,
        user_db_id=req.user_id,
        type_key=req.type_key,
        title=req.title,
        body=req.body,
        data=req.data,
        deep_link=req.deep_link,
    )
    if result.get("error") == "user_not_found":
        raise NotFoundException(detail="User not found", error_code="USER_NOT_FOUND")
    return NotificationDispatchResult(**result)


class SendToTopic(WriteModel):
    topic: str = Field(min_length=1, max_length=900, pattern=r"^[A-Za-z0-9\-_.~%]+$")
    title: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=1000)
    data: dict[str, str] | None = None
    deep_link: str | None = Field(default=None, max_length=512)


@router.post(
    "/send/topic",
    response_model=NotificationDispatchResult,
    responses={
        409: {"description": "The topic channel is disabled. No client subscribes to topics."}
    },
    summary="Send notification to topic (disabled)",
)
async def send_topic(
    req: SendToTopic,
    _: UserSchema = Depends(get_current_admin),
) -> NotificationDispatchResult:
    """Always returns 409 TOPIC_CHANNEL_DISABLED.

    A topic message reaches every subscriber without a consent check, and no
    client subscribes to a topic. The route stays until the admin UI removes
    its topic tab.
    """
    raise ConflictException(
        detail="The topic channel is disabled. Send to typed users instead.",
        error_code="TOPIC_CHANNEL_DISABLED",
    )


class MarketingNotification(WriteModel):
    type_key: MarketingTypeKey
    title: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=1000)
    data: dict[str, str] | None = None
    deep_link: str | None = Field(default=None, max_length=512)


class SegmentFilter(WriteModel):
    role: UserRole | None = None
    agent_id: int | None = None
    is_active: bool | None = True


class MarketingSegmentRequest(MarketingNotification):
    filter: SegmentFilter


class MarketingSendResult(BaseModel):
    requested: int = Field(description="Active users in the audience.")
    processed: int = Field(description="Users the send was dispatched to.")
    succeeded: int = Field(
        description="Dispatches that reported no error. Consent may still block a channel."
    )


async def _dispatch_marketing(
    db: AsyncSession,
    *,
    user_ids: list[int],
    req: MarketingNotification,
) -> int:
    succeeded = 0
    for start in range(0, len(user_ids), MARKETING_BATCH_SIZE):
        summary = await dispatch_notification_to_users(
            db,
            user_db_ids=user_ids[start : start + MARKETING_BATCH_SIZE],
            type_key=req.type_key,
            title=req.title,
            body=req.body,
            data=req.data,
            deep_link=req.deep_link,
        )
        succeeded += int(summary["succeeded"])
    return succeeded


@router.post(
    "/marketing/broadcast", response_model=MarketingSendResult, summary="Send marketing broadcast"
)
async def send_marketing_broadcast(
    req: MarketingNotification,
    _: UserSchema = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> MarketingSendResult:
    """Send a marketing notification to every active user. Consent is checked per user."""
    try:
        requested = await count_users_for_segment(db, is_active=True)
        user_ids = await find_user_ids_for_segment(db, is_active=True, limit=None)
    except Exception as exc:
        raise_read_service_unavailable(
            exc,
            endpoint="notifications_marketing_broadcast",
            detail="Marketing broadcast is temporarily unavailable. Please retry shortly.",
        )
        raise
    succeeded = await _dispatch_marketing(db, user_ids=user_ids, req=req)
    return MarketingSendResult(requested=requested, processed=len(user_ids), succeeded=succeeded)


@router.post(
    "/marketing/segment", response_model=MarketingSendResult, summary="Send marketing segment"
)
async def send_marketing_segment(
    req: MarketingSegmentRequest,
    _: UserSchema = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> MarketingSendResult:
    """Send a marketing notification to a segment of users. Consent is checked per user."""
    role = req.filter.role.value if req.filter.role else None
    try:
        requested = await count_users_for_segment(
            db, role=role, agent_id=req.filter.agent_id, is_active=req.filter.is_active
        )
        user_ids = await find_user_ids_for_segment(
            db, role=role, agent_id=req.filter.agent_id, is_active=req.filter.is_active, limit=None
        )
    except Exception as exc:
        raise_read_service_unavailable(
            exc,
            endpoint="notifications_marketing_segment",
            detail="Marketing segment is temporarily unavailable. Please retry shortly.",
        )
        raise
    succeeded = await _dispatch_marketing(db, user_ids=user_ids, req=req)
    return MarketingSendResult(requested=requested, processed=len(user_ids), succeeded=succeeded)
