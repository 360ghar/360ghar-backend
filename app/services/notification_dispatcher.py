from __future__ import annotations

from typing import Any

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.core.utils import utc_now_iso
from app.models.users import User as UserModel
from app.services.email import send_email
from app.services.notification_config import (
    NOTIFICATION_TYPES,
    NotificationCategory,
    NotificationChannel,
)
from app.services.notifications import send_to_user
from app.services.sms import send_sms

logger = get_logger(__name__)

DEFAULT_SEGMENT_LIMIT = 5000


def _get_user_channels_from_settings(
    *,
    settings_json: dict[str, Any] | None,
    category: NotificationCategory,
    marketing_opt_in_key: str | None,
) -> set[NotificationChannel]:
    """Determine which channels are enabled for the user.

    This function is tolerant of different shapes coming from the
    360 Ghar app and the Stays app.
    """
    enabled: set[NotificationChannel] = set()
    cfg = settings_json or {}

    # Global channel toggles
    push_enabled = bool(
        cfg.get("push_notifications", cfg.get("push", True))
    )
    email_enabled = bool(
        cfg.get("email_notifications", cfg.get("email", True))
    )
    sms_enabled = bool(cfg.get("sms_notifications", False))

    # Marketing-specific toggles
    marketing_allowed = True
    if category == NotificationCategory.MARKETING:
        marketing_allowed = False
        # 360 Ghar style flags
        promo_flag = bool(
            cfg.get("promotional_emails", cfg.get("promotional_push", True))
        )
        # Stays app style categories map: { categories: { promotions: true, ... } }
        categories_cfg = cfg.get("categories") or {}
        if not isinstance(categories_cfg, dict):
            categories_cfg = {}
        promotions_cat = bool(categories_cfg.get("promotions", True))

        marketing_allowed = promo_flag or promotions_cat

        # Optional per-type opt-in key, e.g. "visit_reminders" or "digest"
        if marketing_opt_in_key:
            # Top-level boolean or nested in categories
            specific_flag = cfg.get(marketing_opt_in_key)
            if specific_flag is None and isinstance(categories_cfg, dict):
                specific_flag = categories_cfg.get(marketing_opt_in_key)
            if specific_flag is not None:
                marketing_allowed = marketing_allowed and bool(specific_flag)

    if push_enabled and (category != NotificationCategory.MARKETING or marketing_allowed):
        enabled.add(NotificationChannel.PUSH)
    if email_enabled and (category != NotificationCategory.MARKETING or marketing_allowed):
        enabled.add(NotificationChannel.EMAIL)
    if sms_enabled and (category != NotificationCategory.MARKETING or marketing_allowed):
        enabled.add(NotificationChannel.SMS)

    # In-app centre is always allowed; it is a safe channel.
    enabled.add(NotificationChannel.IN_APP)
    return enabled


async def dispatch_notification_to_user(
    db: AsyncSession,
    *,
    user_db_id: int,
    type_key: str,
    title: str,
    body: str,
    data: dict[str, str] | None = None,
    deep_link: str | None = None,
) -> dict[str, Any]:
    """Dispatch a typed notification to a single user across channels.

    - Respects per-type configuration from NOTIFICATION_TYPES
    - Computes effective channels based on user.notification_settings JSON
    - Sends push (via FCM), email, and SMS where configured
    - Always records the notification for in-app consumption via push service
    """
    cfg = NOTIFICATION_TYPES.get(type_key)
    if not cfg:
        logger.warning("Unknown notification type_key; falling back", extra={"type_key": type_key})
        # Treat unknown types as admin broadcasts
        cfg = NOTIFICATION_TYPES["admin_broadcast"]

    result: dict[str, Any] = {
        "type_key": cfg.key,
        "title": title,
        "body": body,
        "sent_at": utc_now_iso(),
        "channels": {},
    }

    res = await db.execute(select(UserModel).where(UserModel.id == user_db_id))
    user: UserModel | None = res.scalar_one_or_none()
    if not user:
        logger.warning("dispatch_notification_to_user: user not found", extra={"user_db_id": user_db_id})
        result["error"] = "user_not_found"
        return result

    settings_json = user.notification_settings or {}
    effective_channels = _get_user_channels_from_settings(
        settings_json=settings_json,
        category=cfg.category,
        marketing_opt_in_key=cfg.marketing_opt_in_key,
    )

    # Only use channels allowed by both type config and user settings
    allowed_channels = cfg.allowed_channels & effective_channels

    # In-app: piggyback on push recording; every push notification is stored
    # via Supabase notifications table. For in-app-only types, we could add
    # a dedicated path in the future.

    # Push via FCM
    if NotificationChannel.PUSH in allowed_channels and user.supabase_user_id:
        try:
            push_resp = await send_to_user(
                user_id=user.supabase_user_id,
                title=title,
                body=body,
                data=data,
                deep_link=deep_link,
                type_key=cfg.key,
            )
            result["channels"]["push"] = {"ok": True, "response": push_resp}
        except Exception as e:
            logger.error(
                "Failed to send push notification",
                extra={"user_id": user.supabase_user_id, "type_key": cfg.key, "error": str(e)},
            )
            result["channels"]["push"] = {"ok": False, "error": str(e)}

    # Email
    if NotificationChannel.EMAIL in allowed_channels and user.email:
        try:
            ok = await send_email(
                to_email=user.email,
                subject=title,
                body=body,
            )
            result["channels"]["email"] = {"ok": ok}
        except Exception as e:
            logger.error(
                "Failed to send email notification",
                extra={"user_id": user.id, "email": user.email, "type_key": cfg.key, "error": str(e)},
            )
            result["channels"]["email"] = {"ok": False, "error": str(e)}

    # SMS
    if NotificationChannel.SMS in allowed_channels and user.phone:
        try:
            ok = await send_sms(
                phone_number=user.phone,
                message=body,
                metadata={"type_key": cfg.key},
            )
            result["channels"]["sms"] = {"ok": ok}
        except Exception as e:
            logger.error(
                "Failed to send SMS notification",
                extra={"user_id": user.id, "phone": user.phone, "type_key": cfg.key, "error": str(e)},
            )
            result["channels"]["sms"] = {"ok": False, "error": str(e)}

    return result


async def dispatch_notification_to_users(
    db: AsyncSession,
    *,
    user_db_ids: list[int],
    type_key: str,
    title: str,
    body: str,
    data: dict[str, str] | None = None,
    deep_link: str | None = None,
) -> dict[str, Any]:
    """Dispatch a notification to many users by DB id.

    This is a thin loop over dispatch_notification_to_user; for large
    audiences a background job system should be used instead.
    """
    results: list[dict[str, Any]] = []
    success = 0
    for uid in user_db_ids:
        try:
            res = await dispatch_notification_to_user(
                db,
                user_db_id=uid,
                type_key=type_key,
                title=title,
                body=body,
                data=data,
                deep_link=deep_link,
            )
            results.append({"user_id": uid, "result": res})
            if not res.get("error"):
                success += 1
        except Exception as e:  # pragma: no cover - defensive
            logger.error(
                "Bulk dispatch failed for user",
                extra={"user_db_id": uid, "type_key": type_key, "error": str(e)},
            )
            results.append({"user_id": uid, "error": str(e)})

    return {
        "requested": len(user_db_ids),
        "succeeded": success,
        "details": results,
    }


async def find_user_ids_for_segment(
    db: AsyncSession,
    *,
    role: str | None = None,
    agent_id: int | None = None,
    is_active: bool | None = True,
    limit: int | None = DEFAULT_SEGMENT_LIMIT,
) -> list[int]:
    """Resolve a simple audience segment to a list of user ids."""
    stmt, _ = _build_segment_statements(role=role, agent_id=agent_id, is_active=is_active)
    stmt = stmt.order_by(UserModel.id)
    if limit is not None:
        stmt = stmt.limit(limit)
    res = await db.execute(stmt)
    return [row[0] for row in res.all()]


async def count_users_for_segment(
    db: AsyncSession,
    *,
    role: str | None = None,
    agent_id: int | None = None,
    is_active: bool | None = True,
) -> int:
    """Count users in a simple audience segment without loading ids."""
    _, count_stmt = _build_segment_statements(role=role, agent_id=agent_id, is_active=is_active)
    return int((await db.execute(count_stmt)).scalar_one() or 0)


def _build_segment_statements(
    *,
    role: str | None,
    agent_id: int | None,
    is_active: bool | None,
) -> tuple[Select, Select]:
    stmt = select(UserModel.id)
    count_stmt = select(func.count(UserModel.id))
    conditions = []
    if role:
        conditions.append(UserModel.role == role)
    if agent_id is not None:
        conditions.append(UserModel.agent_id == agent_id)
    if is_active is not None:
        conditions.append(UserModel.is_active.is_(is_active))
    if conditions:
        stmt = stmt.where(*conditions)
        count_stmt = count_stmt.where(*conditions)
    return stmt, count_stmt
