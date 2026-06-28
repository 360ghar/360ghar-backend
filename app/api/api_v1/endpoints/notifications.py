from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.api_v1.dependencies.auth import (
    get_current_active_user,
    get_current_admin,
    get_current_user_optional,
)
from app.core.database import get_db
from app.schemas.pagination import CursorPage, CursorParams, build_cursor_page
from app.schemas.user import User as UserSchema
from app.services.notification_config import NOTIFICATION_TYPES, NotificationCategory
from app.services.notification_dispatcher import (
    count_users_for_segment,
    dispatch_notification_to_user,
    dispatch_notification_to_users,
    find_user_ids_for_segment,
)
from app.services.notifications import (
    list_notifications_for_user,
    mark_delivery_opened,
    register_device_token,
    unregister_device_token,
)
from app.services.notifications import (
    send_bulk as svc_send_bulk,
)
from app.services.notifications import (
    send_to_token as svc_send_to_token,
)
from app.services.notifications import (
    send_to_topic as svc_send_to_topic,
)
from app.services.notifications import (
    send_to_user as svc_send_to_user,
)

router = APIRouter()
MAX_MARKETING_RECIPIENTS = 5000


class DeviceRegister(BaseModel):
    token: str
    platform: Literal["android", "ios", "web"]
    app_version: str | None = None
    locale: str | None = None
    # user_id optional (ignored for untrusted callers); prefer auth header user
    user_id: str | None = None


@router.post("/devices/register", summary="Register notification device")
async def devices_register(
    payload: DeviceRegister,
    current_user: UserSchema | None = Depends(get_current_user_optional),
):
    # Require authentication before binding a device token to a user.
    # Anonymous callers may register a token, but it will remain unassociated
    # with any user_id to avoid impersonation.
    """Register notification device."""
    if current_user and getattr(current_user, "supabase_user_id", None):
        user_id = current_user.supabase_user_id
    else:
        if payload.user_id is not None:
            # Prevent unauthenticated clients from registering a token against an
            # arbitrary user id.
            raise HTTPException(
                status_code=401,
                detail={
                    "code": "AUTH_REQUIRED_FOR_USER_BIND",
                    "message": "Authentication is required to associate a device with a user",
                },
            )
        user_id = None
    return await register_device_token(
        token=payload.token,
        platform=payload.platform,
        user_id=user_id,
        app_version=payload.app_version,
        locale=payload.locale,
    )


@router.delete("/devices/unregister", summary="Unregister notification device")
async def devices_unregister(
    token: str = Query(..., min_length=1),
    _: UserSchema | None = Depends(get_current_user_optional),
):
    """Unregister notification device."""
    return await unregister_device_token(token=token)


class SendToToken(BaseModel):
    token: str
    title: str
    body: str
    data: dict[str, str] | None = None
    deep_link: str | None = None
    image: str | None = None


@router.post("/send/token", summary="Send notification to token")
async def send_token(req: SendToToken, _: UserSchema = Depends(get_current_admin)):
    """Send notification to token."""
    return await svc_send_to_token(
        token=req.token,
        title=req.title,
        body=req.body,
        data=req.data,
        deep_link=req.deep_link,
        image=req.image,
        type_key="admin_broadcast",
    )


class SendToUser(BaseModel):
    user_id: str
    title: str
    body: str
    data: dict[str, str] | None = None
    deep_link: str | None = None


@router.post("/send/user", summary="Send notification to user")
async def send_user(req: SendToUser, _: UserSchema = Depends(get_current_admin)):
    """Send notification to user."""
    return await svc_send_to_user(
        user_id=req.user_id,
        title=req.title,
        body=req.body,
        data=req.data,
        deep_link=req.deep_link,
        type_key="admin_broadcast",
    )


class SendToTopic(BaseModel):
    topic: str
    title: str
    body: str
    data: dict[str, str] | None = None
    deep_link: str | None = None


@router.post("/send/topic", summary="Send notification to topic")
async def send_topic(req: SendToTopic, _: UserSchema = Depends(get_current_admin)):
    """Send notification to topic."""
    return await svc_send_to_topic(
        topic=req.topic,
        title=req.title,
        body=req.body,
        data=req.data,
        deep_link=req.deep_link,
        type_key="admin_broadcast",
    )


class SendBulk(BaseModel):
    tokens: list[str] = Field(..., min_length=1, max_length=500)
    title: str
    body: str
    data: dict[str, str] | None = None
    deep_link: str | None = None


@router.post("/send/bulk", summary="Send bulk notifications")
async def send_bulk(req: SendBulk, _: UserSchema = Depends(get_current_admin)):
    """Send bulk notifications."""
    return await svc_send_bulk(
        tokens=req.tokens,
        title=req.title,
        body=req.body,
        data=req.data,
        deep_link=req.deep_link,
        type_key="admin_broadcast",
    )


@router.post("/deliveries/{delivery_id}/opened", summary="Mark delivery as opened")
async def delivery_opened(
    delivery_id: str,
    current_user: UserSchema = Depends(get_current_active_user),
):
    """Mark a delivery as opened for the current authenticated user."""
    res = await mark_delivery_opened(
        delivery_id,
        user_supabase_id=getattr(current_user, "supabase_user_id", None),
    )
    if not res.get("ok"):
        if res.get("error") == "not_found":
            raise HTTPException(status_code=404, detail="Delivery not found")
        if res.get("error") == "forbidden":
            raise HTTPException(status_code=403, detail="Not allowed to update this notification")
        raise HTTPException(status_code=401, detail="Authentication required")
    return res


class TypedUserNotification(BaseModel):
    user_id: int
    type_key: str
    title: str
    body: str
    data: dict[str, str] | None = None
    deep_link: str | None = None


@router.post("/send/typed/user", summary="Send typed notification to user")
async def send_typed_user(
    req: TypedUserNotification,
    _: UserSchema = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Send a typed, multi-channel notification to a single user by DB id."""
    return await dispatch_notification_to_user(
        db,
        user_db_id=req.user_id,
        type_key=req.type_key,
        title=req.title,
        body=req.body,
        data=req.data,
        deep_link=req.deep_link,
    )


class NotificationLogEntry(BaseModel):
    id: str
    title: str
    body: str
    data: dict[str, Any] | None = None
    audience_type: str | None = None
    target_user_id: str | None = None
    topic: str | None = None
    created_at: str | None = None


@router.get("/users/{user_id}", response_model=CursorPage[NotificationLogEntry], summary="List user notifications")
async def list_user_notifications(
    user_id: int,
    _: UserSchema = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
    page: CursorParams = Depends(),
):
    """Return notifications sent to the specified user (by DB id)."""
    from app.models.users import User as UserModel

    user = await db.get(UserModel, user_id)
    if not user or not getattr(user, "supabase_user_id", None):
        raise HTTPException(status_code=404, detail="User not found or not linked to Supabase")
    records, next_payload, total = await list_notifications_for_user(
        user.supabase_user_id,
        cursor_payload=page.decoded(),
        limit=page.limit,
        with_total=page.include_total,
    )
    # Supabase may return ints/other types for id; normalise to strings for the API
    normalised: list[NotificationLogEntry] = []
    for rec in records:
        rec = dict(rec)
        rec["id"] = str(rec.get("id"))
        normalised.append(NotificationLogEntry(**rec))
    return build_cursor_page(normalised, limit=page.limit, next_payload=next_payload, total=total)


class MarketingNotification(BaseModel):
    type_key: str
    title: str
    body: str
    data: dict[str, str] | None = None
    deep_link: str | None = None


class SegmentFilter(BaseModel):
    role: Literal["user", "agent", "admin"] | None = None
    agent_id: int | None = None
    is_active: bool | None = True


class MarketingSegmentRequest(MarketingNotification):
    filter: SegmentFilter


def _ensure_marketing_type(type_key: str) -> None:
    cfg = NOTIFICATION_TYPES.get(type_key)
    if not cfg or cfg.category is not NotificationCategory.MARKETING:
        raise HTTPException(
            status_code=400,
            detail="type_key must be a configured marketing notification type",
        )


@router.post("/marketing/broadcast", summary="Send marketing broadcast")
async def send_marketing_broadcast(
    req: MarketingNotification,
    _: UserSchema = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Send a marketing notification to all active users (broadcast)."""
    _ensure_marketing_type(req.type_key)
    from app.models.users import User as UserModel

    total_result = await db.execute(
        select(func.count(UserModel.id)).where(UserModel.is_active.is_(True))
    )
    total_users = int(total_result.scalar_one() or 0)
    stmt = (
        select(UserModel.id)
        .where(UserModel.is_active.is_(True))
        .order_by(UserModel.id)
        .limit(MAX_MARKETING_RECIPIENTS)
    )
    res = await db.execute(stmt)
    user_ids = [row[0] for row in res.all()]
    summary = await dispatch_notification_to_users(
        db,
        user_db_ids=user_ids,
        type_key=req.type_key,
        title=req.title,
        body=req.body,
        data=req.data,
        deep_link=req.deep_link,
    )
    return {
        "requested": total_users,
        "processed": len(user_ids),
        "summary": summary,
    }


@router.post("/marketing/segment", summary="Send marketing segment")
async def send_marketing_segment(
    req: MarketingSegmentRequest,
    _: UserSchema = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Send a marketing notification to a segment of users based on simple filters."""
    _ensure_marketing_type(req.type_key)
    requested = await count_users_for_segment(
        db,
        role=req.filter.role,
        agent_id=req.filter.agent_id,
        is_active=req.filter.is_active,
    )
    user_ids = await find_user_ids_for_segment(
        db,
        role=req.filter.role,
        agent_id=req.filter.agent_id,
        is_active=req.filter.is_active,
        limit=MAX_MARKETING_RECIPIENTS,
    )
    if not user_ids:
        return {"requested": 0, "processed": 0, "summary": {"requested": 0, "succeeded": 0, "details": []}}
    summary = await dispatch_notification_to_users(
        db,
        user_db_ids=user_ids,
        type_key=req.type_key,
        title=req.title,
        body=req.body,
        data=req.data,
        deep_link=req.deep_link,
    )
    return {
        "requested": requested,
        "processed": len(user_ids),
        "summary": summary,
    }
