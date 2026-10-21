from __future__ import annotations

from typing import Any

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.db_resilience import apply_statement_timeout, execute_with_transient_retry
from app.core.logging import get_logger
from app.core.utils import utc_now
from app.models.users import User as UserModel
from app.services.email import send_email
from app.services.notification_config import (
    NOTIFICATION_TYPES,
    NotificationCategory,
    NotificationChannel,
    app_key_for_type,
)
from app.services.notifications import record_in_app_notification, send_to_user
from app.services.sms import send_sms

logger = get_logger(__name__)

DEFAULT_SEGMENT_LIMIT = 5000


# The only marketing consent key. Missing or non-true means opt-out.
MARKETING_CONSENT_KEY = "promotional_emails"


def _get_user_channels_from_settings(
    *,
    settings_json: dict[str, Any] | None,
    category: NotificationCategory,
) -> set[NotificationChannel]:
    """Return the channels the user allows for a notification category.

    Marketing needs ``promotional_emails`` to be true. Missing means opt-out.
    The read model (NotificationSettings) uses the same default.
    """
    enabled: set[NotificationChannel] = set()
    cfg = settings_json or {}

    push_enabled = cfg.get("push_notifications", True) is True
    email_enabled = cfg.get("email_notifications", True) is True
    sms_enabled = cfg.get("sms_notifications", False) is True

    marketing_allowed = True
    if category == NotificationCategory.MARKETING:
        marketing_allowed = cfg.get(MARKETING_CONSENT_KEY) is True

    if push_enabled and marketing_allowed:
        enabled.add(NotificationChannel.PUSH)
    if email_enabled and marketing_allowed:
        enabled.add(NotificationChannel.EMAIL)
    if sms_enabled and marketing_allowed:
        enabled.add(NotificationChannel.SMS)
    # The in-app inbox follows the same consent gate. Marketing without consent
    # writes no inbox row either.
    if marketing_allowed:
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

    - An unregistered ``type_key`` is an error. Nothing is sent.
    - Channels follow the type config and the user's notification settings.
    - Push goes only to devices of the app that owns the type.
    """
    cfg = NOTIFICATION_TYPES.get(type_key)
    if not cfg:
        logger.warning("Unknown notification type_key; nothing sent", extra={"type_key": type_key})
        return {
            "type_key": type_key,
            "title": title,
            "body": body,
            "sent_at": utc_now(),
            "channels": {},
            "error": "unknown_type_key",
        }

    result: dict[str, Any] = {
        "type_key": cfg.key,
        "title": title,
        "body": body,
        "sent_at": utc_now(),
        "channels": {},
    }

    res = await db.execute(select(UserModel).where(UserModel.id == user_db_id))
    user: UserModel | None = res.scalar_one_or_none()
    if not user:
        logger.warning(
            "dispatch_notification_to_user: user not found", extra={"user_db_id": user_db_id}
        )
        result["error"] = "user_not_found"
        return result

    settings_json = user.notification_settings or {}
    effective_channels = _get_user_channels_from_settings(
        settings_json=settings_json,
        category=cfg.category,
    )

    # Only use channels allowed by both type config and user settings
    allowed_channels = cfg.allowed_channels & effective_channels

    # One notifications row per dispatch. The push send writes it; the inbox reuses it.
    notification_id: str | None = None

    # Push via FCM (best-effort; soft-fails inside send_to_user)
    if NotificationChannel.PUSH in allowed_channels and user.supabase_user_id:
        try:
            push_resp = await send_to_user(
                user_id=user.supabase_user_id,
                title=title,
                body=body,
                data=data,
                deep_link=deep_link,
                type_key=cfg.key,
                app_key=app_key_for_type(cfg.key),
            )
            ok = bool(push_resp.get("ok"))
            notification_id = push_resp.get("notification_id")
            entry: dict[str, Any] = {"ok": ok, "sent": push_resp.get("sent", 0)}
            if not ok:
                entry["error"] = str(push_resp.get("error") or "push failed")
                logger.error(
                    "Failed to send push notification: %s (user_id=%s type_key=%s)",
                    entry["error"],
                    user.supabase_user_id,
                    cfg.key,
                )
            result["channels"]["push"] = entry
        except Exception as e:
            # Include the exception in the message body: structured `extra`
            # fields are often dropped in production logs.
            logger.error(
                "Failed to send push notification: %s (user_id=%s type_key=%s)",
                e,
                user.supabase_user_id,
                cfg.key,
                exc_info=True,
            )
            result["channels"]["push"] = {"ok": False, "sent": 0, "error": str(e)}

    # In-app inbox: one row per dispatch. It needs no device, so the inbox does not depend on push.
    if NotificationChannel.IN_APP in allowed_channels and user.supabase_user_id:
        await record_in_app_notification(
            user_id=user.supabase_user_id,
            type_key=cfg.key,
            title=title,
            body=body,
            data=data,
            deep_link=deep_link,
            notification_id=notification_id,
        )

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
                extra={
                    "user_id": user.id,
                    "email": user.email,
                    "type_key": cfg.key,
                    "error": str(e),
                },
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
                extra={
                    "user_id": user.id,
                    "phone": user.phone,
                    "type_key": cfg.key,
                    "error": str(e),
                },
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
    await apply_statement_timeout(db, settings.DB_READ_STATEMENT_TIMEOUT_MS)
    stmt, _ = _build_segment_statements(role=role, agent_id=agent_id, is_active=is_active)
    stmt = stmt.order_by(UserModel.id)
    if limit is not None:
        stmt = stmt.limit(limit)
    res = await execute_with_transient_retry(
        db,
        lambda: db.execute(stmt),
        operation_name="notification_segment_user_ids",
    )
    return [row[0] for row in res.all()]


async def count_users_for_segment(
    db: AsyncSession,
    *,
    role: str | None = None,
    agent_id: int | None = None,
    is_active: bool | None = True,
) -> int:
    """Count users in a simple audience segment without loading ids."""
    await apply_statement_timeout(db, settings.DB_READ_STATEMENT_TIMEOUT_MS)
    _, count_stmt = _build_segment_statements(role=role, agent_id=agent_id, is_active=is_active)
    result = await execute_with_transient_retry(
        db,
        lambda: db.execute(count_stmt),
        operation_name="notification_segment_count",
    )
    return int(result.scalar_one() or 0)


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
