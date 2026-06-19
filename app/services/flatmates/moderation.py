"""Report and block logic."""

from __future__ import annotations

import re
from datetime import datetime, time, timezone
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import BadRequestException, PropertyNotFoundException
from app.models.enums import (
    PG_FLATMATE_TYPES,
    ConversationStatus,
    FlatmatesProfileStatus,
    PropertyPurpose,
    UserMatchStatus,
    UserReportStatus,
)
from app.models.properties import Property
from app.models.social import UserBlock, UserConversation, UserMatch, UserReport
from app.models.users import User
from app.schemas.flatmates import ReportCreate
from app.schemas.pagination import offset_payload, read_offset
from app.services.flatmates.helpers import _canonical_pair

MIN_REVIEW_PHOTO_COUNT = 2
SUSPICIOUS_RENT_CEILING = 1_000_000
REPORT_AUTO_PAUSE_THRESHOLD = 3
EXPIRED_MOVE_IN_PAUSE_REASON = "expired_move_in_date"

_SPAM_PATTERNS: tuple[tuple[str, str, str], ...] = (
    ("adult_content", "high", r"\b(escort|call\s*girl|xxx|porn|nude|sexual\s+service)\b"),
    ("illegal_substances", "high", r"\b(cocaine|mdma|ganja|hashish|illegal\s+drugs)\b"),
    ("commercial_spam", "warning", r"\b(casino|betting|crypto|loan\s+offer|earn\s+money)\b"),
    ("off_platform_spam", "warning", r"\b(click\s+here|telegram\s+only|whatsapp\s+only)\b"),
)


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _as_price(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _listing_preferences(listing: Any) -> dict[str, Any]:
    preferences = getattr(listing, "listing_preferences", None)
    return dict(preferences) if isinstance(preferences, dict) else {}


def _normalized_photo_urls(listing: Any, image_urls: list[str] | None = None) -> list[str]:
    ordered_urls: list[str] = []
    seen: set[str] = set()

    def add_url(raw_url: Any) -> None:
        url = _as_text(raw_url)
        if not url or url in seen:
            return
        seen.add(url)
        ordered_urls.append(url)

    if image_urls is not None:
        for image_url in image_urls:
            add_url(image_url)
    else:
        add_url(getattr(listing, "main_image_url", None))
        images = getattr(listing, "__dict__", {}).get("images") or []
        sorted_images = sorted(
            images,
            key=lambda image: (
                getattr(image, "display_order", 0) or 0,
                getattr(image, "id", 0) or 0,
            ),
        )
        for image in sorted_images:
            add_url(getattr(image, "image_url", None))

    return ordered_urls


def _content_text(listing: Any) -> str:
    preferences = _listing_preferences(listing)
    raw_values: list[Any] = [
        getattr(listing, "title", None),
        getattr(listing, "description", None),
        getattr(listing, "owner_name", None),
        getattr(listing, "locality", None),
        getattr(listing, "sub_locality", None),
        getattr(listing, "city", None),
        getattr(listing, "search_keywords", None),
    ]
    for collection_name in ("features", "tags"):
        collection = getattr(listing, collection_name, None)
        if isinstance(collection, dict):
            raw_values.extend(key for key, value in collection.items() if value)
        elif isinstance(collection, list):
            raw_values.extend(collection)
    raw_values.extend(preferences.values())
    return " ".join(_as_text(value) for value in raw_values if _as_text(value)).lower()


def _flag(code: str, severity: str, reason: str, *, field: str | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "code": code,
        "severity": severity,
        "reason": reason,
    }
    if field:
        payload["field"] = field
    return payload


def build_listing_prescreen_result(
    listing: Any,
    *,
    image_urls: list[str] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Classify a flatmate listing for the human moderation queue.

    This is intentionally deterministic for V1: the PRD asks for a backend-side
    keyword/completeness classifier without an external ML dependency.
    """
    photo_urls = _normalized_photo_urls(listing, image_urls=image_urls)
    preferences = _listing_preferences(listing)
    flags: list[dict[str, Any]] = []

    if len(photo_urls) < MIN_REVIEW_PHOTO_COUNT:
        flags.append(
            _flag(
                "missing_photos",
                "high",
                f"Listing has {len(photo_urls)} photo(s); at least {MIN_REVIEW_PHOTO_COUNT} are required for review.",
                field="image_urls",
            )
        )

    required_fields = (
        ("title", getattr(listing, "title", None), "Title is missing."),
        ("description", getattr(listing, "description", None), "Description is missing."),
        ("city", getattr(listing, "city", None), "City is missing."),
        ("locality", getattr(listing, "locality", None), "Locality is missing."),
        (
            "sub_locality",
            getattr(listing, "sub_locality", None),
            "Society/building name is missing.",
        ),
        ("bedrooms", getattr(listing, "bedrooms", None), "Bedroom count is missing."),
        ("bathrooms", getattr(listing, "bathrooms", None), "Bathroom count is missing."),
        (
            "gender_preference",
            preferences.get("gender_preference"),
            "Gender preference is missing.",
        ),
        ("sharing_type", preferences.get("sharing_type"), "Sharing type is missing."),
    )
    for field, value, reason in required_fields:
        if not _as_text(value):
            flags.append(_flag("missing_key_field", "warning", reason, field=field))

    rent = _as_price(getattr(listing, "monthly_rent", None))
    if rent is None:
        rent = _as_price(getattr(listing, "base_price", None))
    if rent is None or rent <= 0:
        flags.append(
            _flag(
                "suspicious_pricing",
                "high",
                "Monthly rent is missing or zero.",
                field="monthly_rent",
            )
        )
    elif rent >= SUSPICIOUS_RENT_CEILING:
        flags.append(
            _flag(
                "suspicious_pricing",
                "high",
                "Monthly rent is at or above Rs 10L.",
                field="monthly_rent",
            )
        )

    content = _content_text(listing)
    for code, severity, pattern in _SPAM_PATTERNS:
        match = re.search(pattern, content, flags=re.IGNORECASE)
        if match:
            flags.append(
                {
                    **_flag(
                        code,
                        severity,
                        "Content contains keywords that may indicate spam or inappropriate content.",
                        field="content",
                    ),
                    "matched_term": match.group(0),
                }
            )

    prescreened_at = (now or datetime.now(timezone.utc)).isoformat()
    result = "flagged" if flags else "clear"
    reason = "; ".join(flag["reason"] for flag in flags[:3])
    if len(flags) > 3:
        reason = f"{reason}; {len(flags) - 3} more flag(s)"

    return {
        "prescreen_result": result,
        "flags": flags,
        "flagged": bool(flags),
        "flag_reason": reason or None,
        "photo_count": len(photo_urls),
        "prescreened_at": prescreened_at,
    }


def apply_listing_prescreen_metadata(
    listing: Any,
    *,
    admin_user_id: int | None = None,
    image_urls: list[str] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    result = build_listing_prescreen_result(listing, image_urls=image_urls, now=now)
    preferences = _listing_preferences(listing)
    preferences["ai_prescreen_result"] = result["prescreen_result"]
    preferences["ai_prescreen_flags"] = result["flags"]
    preferences["ai_prescreen_reason"] = result["flag_reason"]
    preferences["ai_prescreen_photo_count"] = result["photo_count"]
    preferences["ai_prescreened_at"] = result["prescreened_at"]
    if admin_user_id is not None:
        preferences["ai_prescreened_by"] = admin_user_id
    listing.listing_preferences = preferences
    return result


async def prescreen_flatmate_listing(
    db: AsyncSession,
    listing_id: int,
    *,
    admin_user_id: int | None = None,
) -> dict[str, Any]:
    stmt = (
        select(Property)
        .options(selectinload(Property.images))
        .where(
            Property.id == listing_id,
            Property.property_type.in_(PG_FLATMATE_TYPES),
            Property.purpose == PropertyPurpose.rent,
        )
    )
    listing = (await db.execute(stmt)).scalar_one_or_none()
    if listing is None:
        raise PropertyNotFoundException(property_id=listing_id)

    result = apply_listing_prescreen_metadata(listing, admin_user_id=admin_user_id)
    await db.flush()
    return {
        "listing_id": listing.id,
        **result,
    }


async def list_blocks(
    db: AsyncSession,
    user_id: int,
    *,
    cursor_payload: dict | None = None,
    limit: int = 20,
    with_total: bool = False,
) -> tuple[list[dict[str, Any]], dict | None, int | None]:
    from app.services.flatmates.helpers import _build_peer_payload

    if cursor_payload is None:
        cursor_payload = {}
    offset = read_offset(cursor_payload)

    total: int | None = None
    if with_total:
        total = (
            await db.execute(
                select(func.count())
                .select_from(UserBlock)
                .where(UserBlock.blocker_user_id == user_id)
            )
        ).scalar_one()

    stmt = (
        select(UserBlock, User)
        .join(User, User.id == UserBlock.blocked_user_id)
        .where(UserBlock.blocker_user_id == user_id)
        .order_by(UserBlock.created_at.desc())
        .offset(offset)
        .limit(limit + 1)
    )
    rows = (await db.execute(stmt)).all()
    has_more = len(rows) > limit
    rows = rows[:limit]
    next_payload = offset_payload(offset + limit) if has_more else None

    items = [
        {
            "id": block.id,
            "blocked_user": _build_peer_payload(blocked_user),
            "created_at": block.created_at,
        }
        for block, blocked_user in rows
    ]
    return items, next_payload, total


async def delete_block(db: AsyncSession, user_id: int, blocked_user_id: int) -> dict[str, Any]:
    stmt = select(UserBlock).where(
        UserBlock.blocker_user_id == user_id,
        UserBlock.blocked_user_id == blocked_user_id,
    )
    block = (await db.execute(stmt)).scalar_one_or_none()
    if block is None:
        raise BadRequestException(detail="Blocked user not found")
    await db.delete(block)
    await db.flush()
    return {"ok": True, "blocked_user_id": blocked_user_id}


async def create_block(db: AsyncSession, user_id: int, blocked_user_id: int) -> UserBlock:
    if blocked_user_id == user_id:
        raise BadRequestException(detail="Cannot block yourself")
    if await db.get(User, blocked_user_id) is None:
        raise BadRequestException(detail="User not found")
    stmt = select(UserBlock).where(
        UserBlock.blocker_user_id == user_id,
        UserBlock.blocked_user_id == blocked_user_id,
    )
    existing = (await db.execute(stmt)).scalar_one_or_none()
    if existing:
        return existing

    block = UserBlock(blocker_user_id=user_id, blocked_user_id=blocked_user_id)
    db.add(block)

    user_one_id, user_two_id = _canonical_pair(user_id, blocked_user_id)
    conversation_stmt = select(UserConversation).where(
        UserConversation.user_one_id == user_one_id,
        UserConversation.user_two_id == user_two_id,
    )
    conversation = (await db.execute(conversation_stmt)).scalar_one_or_none()
    if conversation:
        conversation.status = ConversationStatus.blocked

    match_stmt = select(UserMatch).where(
        UserMatch.user_one_id == user_one_id,
        UserMatch.user_two_id == user_two_id,
    )
    match = (await db.execute(match_stmt)).scalar_one_or_none()
    if match:
        match.status = UserMatchStatus.blocked

    await db.flush()
    return block


async def _active_reporter_count(db: AsyncSession, reported_user_id: int) -> int:
    rows = (
        await db.execute(
            select(UserReport.reporter_user_id).where(
                UserReport.reported_user_id == reported_user_id,
                UserReport.status.in_(
                    [
                        UserReportStatus.open.value,
                        UserReportStatus.reviewed.value,
                    ]
                ),
            )
        )
    ).scalars()
    return len({int(reporter_id) for reporter_id in rows.all()})


def apply_report_auto_pause(
    reported_user: User,
    *,
    report_count: int,
    now: datetime | None = None,
) -> bool:
    if report_count < REPORT_AUTO_PAUSE_THRESHOLD:
        return False
    if reported_user.flatmates_profile_status == FlatmatesProfileStatus.paused:
        return False

    paused_at = (now or datetime.now(timezone.utc)).isoformat()
    preferences = (
        dict(reported_user.preferences) if isinstance(reported_user.preferences, dict) else {}
    )
    flatmates_preferences = preferences.get("flatmates")
    if not isinstance(flatmates_preferences, dict):
        flatmates_preferences = {}
    else:
        flatmates_preferences = dict(flatmates_preferences)
    flatmates_preferences.update(
        {
            "auto_paused_reason": "repeat_reports",
            "auto_paused_report_count": report_count,
            "auto_paused_at": paused_at,
        }
    )
    preferences["flatmates"] = flatmates_preferences
    reported_user.preferences = preferences
    reported_user.flatmates_profile_status = FlatmatesProfileStatus.paused
    return True


def _as_aware_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def apply_expired_move_in_pause(
    listing: Property,
    *,
    now: datetime | None = None,
) -> bool:
    if getattr(listing, "property_type", None) not in PG_FLATMATE_TYPES:
        return False
    if getattr(listing, "purpose", None) != PropertyPurpose.rent:
        return False

    move_in_at = _as_aware_datetime(getattr(listing, "available_from", None))
    if move_in_at is None:
        return False

    effective_now = now or datetime.now(timezone.utc)
    if effective_now.tzinfo is None:
        effective_now = effective_now.replace(tzinfo=timezone.utc)
    if move_in_at.date() >= effective_now.date():
        return False

    preferences = _listing_preferences(listing)
    current_status = preferences.get("moderation_status", "live")
    if current_status not in {None, "live"} and not getattr(listing, "is_available", False):
        return False
    if (
        preferences.get("auto_paused_reason") == EXPIRED_MOVE_IN_PAUSE_REASON
        and preferences.get("moderation_status") == "paused"
        and not getattr(listing, "is_available", False)
    ):
        return False

    preferences.update(
        {
            "moderation_status": "paused",
            "auto_paused_reason": EXPIRED_MOVE_IN_PAUSE_REASON,
            "auto_paused_at": effective_now.isoformat(),
            "expired_move_in_date": move_in_at.isoformat(),
            "room_poster_review_required": True,
        }
    )
    if current_status:
        preferences.setdefault("previous_moderation_status", current_status)

    listing.listing_preferences = preferences
    listing.is_available = False
    return True


async def pause_expired_flatmate_listings(
    db: AsyncSession,
    *,
    now: datetime | None = None,
) -> int:
    effective_now = now or datetime.now(timezone.utc)
    if effective_now.tzinfo is None:
        effective_now = effective_now.replace(tzinfo=timezone.utc)
    cutoff = datetime.combine(effective_now.date(), time.min, tzinfo=effective_now.tzinfo)

    batch_size = 500
    paused_count = 0
    while True:
        result = await db.execute(
            select(Property)
            .where(
                Property.property_type.in_(PG_FLATMATE_TYPES),
                Property.purpose == PropertyPurpose.rent,
                Property.available_from.is_not(None),
                Property.available_from < cutoff,
                or_(
                    Property.is_available.is_(True),
                    func.coalesce(
                        Property.listing_preferences["moderation_status"].as_string(),
                        "live",
                    )
                    == "live",
                ),
            )
            .order_by(Property.id)
            .limit(batch_size)
        )
        listings = list(result.scalars().all())
        if not listings:
            break

        batch_paused = 0
        for listing in listings:
            if apply_expired_move_in_pause(listing, now=effective_now):
                paused_count += 1
                batch_paused += 1

        if batch_paused:
            await db.flush()
        else:
            break
    return paused_count


async def create_report(db: AsyncSession, user_id: int, payload: ReportCreate) -> UserReport:
    if payload.reported_user_id == user_id:
        raise BadRequestException(detail="Cannot report yourself")
    reported_user = await db.get(User, payload.reported_user_id)
    if reported_user is None:
        raise BadRequestException(detail="Reported user not found")
    report = UserReport(
        reporter_user_id=user_id,
        reported_user_id=payload.reported_user_id,
        conversation_id=payload.conversation_id,
        property_id=payload.property_id,
        reason=payload.reason.value,
        notes=payload.notes,
    )
    db.add(report)
    await db.flush()

    report_count = await _active_reporter_count(db, payload.reported_user_id)
    if apply_report_auto_pause(reported_user, report_count=report_count):
        from app.services.push_notification import _dispatch

        await _dispatch(
            db,
            user_db_id=payload.reported_user_id,
            type_key="flatmate_account_warned",
            title="Profile Paused",
            body="Your Flatmates profile is paused pending safety review.",
            data={"route": "/profile"},
            deep_link="/profile",
        )

    await db.refresh(report)
    return report
