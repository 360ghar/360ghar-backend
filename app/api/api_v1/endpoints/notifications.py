from typing import Optional, Dict, List, Literal, Any
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel, Field

from app.api.api_v1.dependencies.auth import get_current_user_optional
from app.core.database import get_db
from app.api.api_v1.dependencies.auth import get_current_admin, get_current_active_user
from app.schemas.user import User as UserSchema
from app.services.notifications import (
    register_device_token,
    unregister_device_token,
    send_to_token as svc_send_to_token,
    send_to_user as svc_send_to_user,
    send_to_topic as svc_send_to_topic,
    send_bulk as svc_send_bulk,
    mark_delivery_opened,
    list_notifications_for_user,
)
from app.services.notification_dispatcher import (
    dispatch_notification_to_user,
    dispatch_notification_to_users,
    find_user_ids_for_segment,
)
from app.services.notification_config import NOTIFICATION_TYPES, NotificationCategory

router = APIRouter()


class DeviceRegister(BaseModel):
    token: str
    platform: Literal["android", "ios", "web"]
    app_version: Optional[str] = None
    locale: Optional[str] = None
    # user_id optional (ignored for untrusted callers); prefer auth header user
    user_id: Optional[str] = None


@router.post("/devices/register")
async def devices_register(
    payload: DeviceRegister,
    current_user: Optional[UserSchema] = Depends(get_current_user_optional),
):
    # Require authentication before binding a device token to a user.
    # Anonymous callers may register a token, but it will remain unassociated
    # with any user_id to avoid impersonation.
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


@router.delete("/devices/unregister")
async def devices_unregister(
    token: str = Query(..., min_length=1),
    _: Optional[UserSchema] = Depends(get_current_user_optional),
):
    return await unregister_device_token(token=token)


class SendToToken(BaseModel):
    token: str
    title: str
    body: str
    data: Optional[Dict[str, str]] = None
    deep_link: Optional[str] = None
    image: Optional[str] = None


@router.post("/send/token")
async def send_token(req: SendToToken, _: UserSchema = Depends(get_current_admin)):
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
    data: Optional[Dict[str, str]] = None
    deep_link: Optional[str] = None


@router.post("/send/user")
async def send_user(req: SendToUser, _: UserSchema = Depends(get_current_admin)):
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
    data: Optional[Dict[str, str]] = None
    deep_link: Optional[str] = None


@router.post("/send/topic")
async def send_topic(req: SendToTopic, _: UserSchema = Depends(get_current_admin)):
    return await svc_send_to_topic(
        topic=req.topic,
        title=req.title,
        body=req.body,
        data=req.data,
        deep_link=req.deep_link,
        type_key="admin_broadcast",
    )


class SendBulk(BaseModel):
    tokens: List[str] = Field(..., min_length=1, max_length=500)
    title: str
    body: str
    data: Optional[Dict[str, str]] = None
    deep_link: Optional[str] = None


@router.post("/send/bulk")
async def send_bulk(req: SendBulk, _: UserSchema = Depends(get_current_admin)):
    return await svc_send_bulk(
        tokens=req.tokens,
        title=req.title,
        body=req.body,
        data=req.data,
        deep_link=req.deep_link,
        type_key="admin_broadcast",
    )


@router.post("/deliveries/{delivery_id}/opened")
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
    data: Optional[Dict[str, str]] = None
    deep_link: Optional[str] = None


@router.post("/send/typed/user")
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
    data: Optional[Dict[str, Any]] = None
    audience_type: Optional[str] = None
    target_user_id: Optional[str] = None
    topic: Optional[str] = None
    created_at: Optional[str] = None


@router.get("/users/{user_id}", response_model=List[NotificationLogEntry])
async def list_user_notifications(
    user_id: int,
    _: UserSchema = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """Return notifications sent to the specified user (by DB id)."""
    from app.models.users import User as UserModel

    user = await db.get(UserModel, user_id)
    if not user or not getattr(user, "supabase_user_id", None):
        raise HTTPException(status_code=404, detail="User not found or not linked to Supabase")
    records = await list_notifications_for_user(user.supabase_user_id, limit=limit, offset=offset)
    # Supabase may return ints/other types for id; normalise to strings for the API
    normalised: List[Dict[str, Any]] = []
    for rec in records:
        rec = dict(rec)
        rec["id"] = str(rec.get("id"))
        normalised.append(rec)
    return normalised


class MarketingNotification(BaseModel):
    type_key: str
    title: str
    body: str
    data: Optional[Dict[str, str]] = None
    deep_link: Optional[str] = None


class SegmentFilter(BaseModel):
    role: Optional[Literal["user", "agent", "admin"]] = None
    agent_id: Optional[int] = None
    is_active: Optional[bool] = True


class MarketingSegmentRequest(MarketingNotification):
    filter: SegmentFilter


def _ensure_marketing_type(type_key: str) -> None:
    cfg = NOTIFICATION_TYPES.get(type_key)
    if not cfg or cfg.category is not NotificationCategory.MARKETING:
        raise HTTPException(
            status_code=400,
            detail="type_key must be a configured marketing notification type",
        )


@router.post("/marketing/broadcast")
async def send_marketing_broadcast(
    req: MarketingNotification,
    _: UserSchema = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Send a marketing notification to all active users (broadcast)."""
    _ensure_marketing_type(req.type_key)
    from app.models.users import User as UserModel

    stmt = select(UserModel.id).where(UserModel.is_active.is_(True))
    res = await db.execute(stmt)
    user_ids = [row[0] for row in res.all()]
    # Safety limit to avoid accidental massive blasts from the dashboard
    MAX_RECIPIENTS = 5000
    limited_ids = user_ids[:MAX_RECIPIENTS]
    summary = await dispatch_notification_to_users(
        db,
        user_db_ids=limited_ids,
        type_key=req.type_key,
        title=req.title,
        body=req.body,
        data=req.data,
        deep_link=req.deep_link,
    )
    return {
        "requested": len(user_ids),
        "processed": len(limited_ids),
        "summary": summary,
    }


@router.post("/marketing/segment")
async def send_marketing_segment(
    req: MarketingSegmentRequest,
    _: UserSchema = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Send a marketing notification to a segment of users based on simple filters."""
    _ensure_marketing_type(req.type_key)
    user_ids = await find_user_ids_for_segment(
        db,
        role=req.filter.role,
        agent_id=req.filter.agent_id,
        is_active=req.filter.is_active,
    )
    MAX_RECIPIENTS = 5000
    limited_ids = user_ids[:MAX_RECIPIENTS]
    if not limited_ids:
        return {"requested": 0, "processed": 0, "summary": {"requested": 0, "succeeded": 0, "details": []}}
    summary = await dispatch_notification_to_users(
        db,
        user_db_ids=limited_ids,
        type_key=req.type_key,
        title=req.title,
        body=req.body,
        data=req.data,
        deep_link=req.deep_link,
    )
    return {
        "requested": len(user_ids),
        "processed": len(limited_ids),
        "summary": summary,
    }
