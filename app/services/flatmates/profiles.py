"""Profile CRUD, listing, catalogs, bootstrap, and notification helpers."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import String, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import BadRequestException
from app.core.logging import get_logger
from app.models.enums import (
    FlatmatesProfileStatus,
    PropertyPurpose,
    PropertyType,
    SwipeTargetType,
)
from app.models.properties import Property, PropertyAmenity
from app.models.social import AppCatalog, UserConversation, UserMessage
from app.models.users import User, UserSwipe
from app.schemas.flatmates import FlatmatesProfileUpdate
from app.schemas.pagination import offset_payload, read_offset
from app.services.flatmates.helpers import (
    _build_peer_payload,
    _build_profile_payload,
    _serialize_flatmate_notification,
)
from app.services.notifications import _supa, list_notifications_for_user
from app.utils.validators import ValidationUtils

logger = get_logger(__name__)


def _move_in_profile_values(move_in: str | None) -> set[str]:
    if move_in is None:
        return set()
    value = move_in.strip().lower().replace("-", "_")
    if value in {"", "all", "any", "anytime", "flexible", "just_exploring"}:
        return set()
    if value in {"immediate", "immediately", "now"}:
        return {"immediate", "immediately", "now"}
    if value in {"this_month", "within_1_month", "within_a_month"}:
        return {"this_month", "within_1_month", "within_a_month"}
    if value == "next_month":
        return {"next_month"}
    if value in {"within_2_weeks", "two_weeks"}:
        return {"within_2_weeks", "two_weeks"}
    return set()


async def get_flatmates_profile(db: AsyncSession, user_id: int) -> dict[str, Any]:
    user = await db.get(User, user_id)
    if user is None:
        raise BadRequestException(detail="User not found")
    return _build_profile_payload(user)


async def get_profile_by_id(
    db: AsyncSession,
    user_id: int,
    *,
    current_user_id: int | None = None,
) -> dict[str, Any]:
    """Return a flatmates peer payload for an arbitrary user (used by GET /profiles/{user_id})."""
    user = await db.get(User, user_id)
    if user is None:
        raise BadRequestException(detail="User not found")
    current_user = await db.get(User, current_user_id) if current_user_id else None

    # Load the peer's most recent active flatmate/PG listing so the peer payload
    # carries the same listing context (photos, rent, amenities, room config)
    # as the swipe deck. Mirrors the batched query in list_discoverable_profiles.
    property_stmt = (
        select(Property)
        .options(
            selectinload(Property.images),
            selectinload(Property.property_amenities).selectinload(PropertyAmenity.amenity),
        )
        .where(
            Property.owner_id == user_id,
            Property.property_type.in_([PropertyType.flatmate, PropertyType.pg]),
            Property.purpose == PropertyPurpose.rent,
            Property.is_available.is_(True),
        )
        .order_by(Property.created_at.desc())
        .limit(1)
    )
    property_obj = (await db.execute(property_stmt)).scalar_one_or_none()

    return _build_peer_payload(
        user,
        current_user=current_user,
        property_obj=property_obj,
    )


async def list_discoverable_profiles(
    db: AsyncSession,
    user_id: int,
    *,
    city: str | None = None,
    budget_min: int | None = None,
    budget_max: int | None = None,
    move_in: str | None = None,
    lat: float | None = None,
    lng: float | None = None,
    radius: float | None = None,
    non_negotiables_override: list[str] | None = None,
    cursor_payload: dict[str, Any] | None = None,
    limit: int = 20,
    with_total: bool = False,
) -> tuple[list[dict[str, Any]], dict[str, Any] | None, int | None]:
    from app.models.social import UserBlock  # noqa: WPS433 – avoid top-level circular risk
    from app.utils.distance import get_bounding_box

    blocked_stmt = select(UserBlock.blocked_user_id).where(
        UserBlock.blocker_user_id == user_id,
    )
    blocker_stmt = select(UserBlock.blocker_user_id).where(
        UserBlock.blocked_user_id == user_id,
    )
    blocked_ids = list((await db.execute(blocked_stmt)).scalars().all())
    blocker_ids = list((await db.execute(blocker_stmt)).scalars().all())
    excluded = {user_id, *blocked_ids, *blocker_ids}

    swiped_subq = select(UserSwipe.target_user_id).where(
        UserSwipe.user_id == user_id,
        UserSwipe.target_type == SwipeTargetType.user.value,
        UserSwipe.target_user_id.is_not(None),
    )

    # --- Deal-breaker (non-negotiables) filtering (P0-4) ---
    requesting_user = await db.get(User, user_id)
    non_negotiables: list[str] = []
    if non_negotiables_override is not None:
        non_negotiables = non_negotiables_override
    elif requesting_user and isinstance(requesting_user.preferences, dict):
        flatmates_prefs = requesting_user.preferences.get("flatmates")
        if isinstance(flatmates_prefs, dict):
            raw_nn = flatmates_prefs.get("non_negotiables")
            if isinstance(raw_nn, list):
                non_negotiables = [str(x) for x in raw_nn]

    # --- Exclude users with the same phone number (same-person dedup guard) ---
    if requesting_user and requesting_user.phone:
        base_phone = requesting_user.phone.split("_dup_")[0]
        phone_excluded_subq = select(User.id).where(
            or_(
                User.phone == base_phone,
                User.phone.like(f"{base_phone}_dup_%")
            ),
            User.id != user_id,
        )
        phone_dup_ids = list((await db.execute(phone_excluded_subq)).scalars().all())
        excluded.update(phone_dup_ids)

    filters = [
        User.id.notin_(excluded),
        User.id.notin_(swiped_subq),
        User.flatmates_onboarding_completed.is_(True),
        User.flatmates_profile_status == FlatmatesProfileStatus.active,
    ]

    for nn in non_negotiables:
        if nn == "food_veg_only":
            filters.append(User.flatmates_food_habits.in_(["vegetarian", "vegan"]))
        elif nn == "food_vegan_only":
            filters.append(User.flatmates_food_habits.in_(["vegan"]))
        elif nn == "no_smoking":
            filters.append(User.flatmates_smoking_drinking.in_(
                ["neither", "drink_occasionally"]
            ))
        elif nn == "no_drinking":
            filters.append(User.flatmates_smoking_drinking.in_(
                ["neither", "smoke_outside"]
            ))
        elif nn == "no_overnight_guests":
            filters.append(User.flatmates_guests_policy.in_(
                ["no_overnight_guests"]
            ))
        elif nn == "no_pets":
            # pets is stored inside preferences.flatmates.pets
            filters.append(
                func.coalesce(cast(User.preferences[("flatmates", "pets")], String), "no_pets") == "no_pets"
            )
        elif nn == "gender_female_only":
            # gender stored in preferences.flatmates.gender
            filters.append(
                func.coalesce(cast(User.preferences[("flatmates", "gender")], String), "").in_(
                    ["female", '"female"']
                )
            )
        elif nn == "gender_male_only":
            filters.append(
                func.coalesce(cast(User.preferences[("flatmates", "gender")], String), "").in_(
                    ["male", '"male"']
                )
            )
        elif nn == "no_parties":
            # parties_at_home stored in preferences.flatmates.parties_at_home
            # JSON text extraction returns quoted strings (e.g. '"never"'), so
            # we must include both quoted and unquoted variants.
            filters.append(
                func.coalesce(cast(User.preferences[("flatmates", "parties_at_home")], String), "").notin_(
                    [
                        "occasional_weekends", '"occasional_weekends"',
                        "party_friendly", '"party_friendly"',
                        "occasionally", '"occasionally"',
                        "regularly", '"regularly"',
                    ]
                )
            )
        elif nn == "min_tidy":
            filters.append(User.flatmates_cleanliness.in_(
                ["tidy", "spotless"]
            ))
        elif nn == "early_riser":
            filters.append(User.flatmates_sleep_schedule.in_(
                ["early_bird"]
            ))

    # --- Discovery filtering (P0-8) ---
    if city is not None:
        filters.append(User.flatmates_city == city)
    if budget_min is not None:
        filters.append(
            or_(
                User.flatmates_budget_max >= float(budget_min),
                User.flatmates_budget_max.is_(None),
            )
        )
    if budget_max is not None:
        filters.append(
            or_(
                User.flatmates_budget_min <= float(budget_max),
                User.flatmates_budget_min.is_(None),
            )
        )
    move_in_values = _move_in_profile_values(move_in)
    if move_in_values:
        filters.append(User.flatmates_move_in_timeline.in_(move_in_values))

    # --- Geolocation filtering ---
    if lat is not None and lng is not None and radius is not None:
        min_lat, max_lat, min_lon, max_lon = get_bounding_box(lat, lng, radius)
        filters.extend([
            User.current_latitude.between(min_lat, max_lat),
            User.current_longitude.between(min_lon, max_lon),
        ])

    _payload: dict[str, Any] = cursor_payload if cursor_payload is not None else {}
    _offset = read_offset(_payload)

    count_total: int | None = None
    if with_total:
        count_stmt = select(func.count(User.id)).where(*filters)
        count_total = int((await db.execute(count_stmt)).scalar() or 0)

    stmt = (
        select(User)
        .where(*filters)
        .order_by(User.flatmates_last_active_at.desc().nulls_last())
        .offset(_offset)
        .limit(limit + 1)
    )
    users = list((await db.execute(stmt)).scalars().all())
    next_payload: dict[str, Any] | None = None
    if len(users) > limit:
        users = users[:limit]
        next_payload = offset_payload(_offset + limit)

    # --- Batch load active flatmate/PG listings for all matched users (single query, no N+1) ---
    prop_map: dict[int, Property] = {}
    if users:
        owner_ids = [u.id for u in users]
        property_stmt = (
            select(Property)
            .options(
                selectinload(Property.images),
                selectinload(Property.property_amenities).selectinload(PropertyAmenity.amenity),
            )
            .where(
                Property.owner_id.in_(owner_ids),
                Property.property_type.in_([PropertyType.flatmate, PropertyType.pg]),
                Property.purpose == PropertyPurpose.rent,
                Property.is_available.is_(True),
            )
            .order_by(Property.created_at.desc())
        )
        prop_rows = (await db.execute(property_stmt)).scalars().all()
        for prop in prop_rows:
            # Keep the most recently created listing per owner (first encountered due to order_by desc)
            prop_map.setdefault(prop.owner_id, prop)

    profiles = [
        _build_peer_payload(
            u,
            current_user=requesting_user,
            property_obj=prop_map.get(u.id),
        )
        for u in users
    ]
    return profiles, next_payload, count_total


async def update_flatmates_profile(
    db: AsyncSession,
    user_id: int,
    payload: FlatmatesProfileUpdate,
) -> dict[str, Any]:
    user = await db.get(User, user_id)
    if user is None:
        raise BadRequestException(detail="User not found")

    update_data = payload.model_dump(exclude_unset=True)
    preference_patch = update_data.pop("preferences", None)

    if "full_name" in update_data:
        user.full_name = update_data.pop("full_name")
    if "profile_image_url" in update_data:
        url = update_data.pop("profile_image_url")
        if url is not None and not ValidationUtils.is_absolute_url(url):
            logger.warning("Non-absolute profile_image_url for user %s: %s", user_id, url)
        user.profile_image_url = url
    if "email" in update_data:
        user.email = update_data.pop("email")
    if "phone" in update_data:
        user.phone = update_data.pop("phone")

    preference_fields = ("age", "profession", "gender", "gender_preference")
    current_preferences = user.preferences if isinstance(user.preferences, dict) else {}
    flatmates_preferences = current_preferences.get("flatmates")
    if not isinstance(flatmates_preferences, dict):
        flatmates_preferences = {}
    for key in preference_fields:
        if key in update_data:
            value = update_data.pop(key)
            if value is None:
                flatmates_preferences.pop(key, None)
            else:
                flatmates_preferences[key] = value

    field_map = {
        "mode": "flatmates_mode",
        "profile_status": "flatmates_profile_status",
        "onboarding_completed": "flatmates_onboarding_completed",
        "bio": "flatmates_bio",
        "budget_min": "flatmates_budget_min",
        "budget_max": "flatmates_budget_max",
        "move_in_timeline": "flatmates_move_in_timeline",
        "city": "flatmates_city",
        "locality": "flatmates_locality",
        "sleep_schedule": "flatmates_sleep_schedule",
        "cleanliness": "flatmates_cleanliness",
        "food_habits": "flatmates_food_habits",
        "smoking_drinking": "flatmates_smoking_drinking",
        "guests_policy": "flatmates_guests_policy",
        "work_style": "flatmates_work_style",
    }

    for incoming_key, model_field in field_map.items():
        if incoming_key in update_data:
            setattr(user, model_field, update_data[incoming_key])

    if preference_patch is not None:
        flatmates_preferences.update(preference_patch)

    user.preferences = {
        **current_preferences,
        "flatmates": flatmates_preferences,
    }

    user.flatmates_last_active_at = datetime.now(timezone.utc)
    await db.flush()
    await db.refresh(user)
    return _build_profile_payload(user)


async def list_catalogs(db: AsyncSession) -> list[AppCatalog]:
    stmt = select(AppCatalog).where(AppCatalog.is_active.is_(True)).order_by(AppCatalog.key.asc())
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def list_flatmates_notifications(
    db: AsyncSession,
    user_id: int,
    *,
    cursor_payload: dict | None = None,
    limit: int = 20,
    with_total: bool = False,
) -> tuple[list[dict[str, Any]], dict | None, int | None]:
    user = await db.get(User, user_id)
    if user is None:
        raise BadRequestException(detail="User not found")
    rows, next_payload, total = await list_notifications_for_user(
        user.supabase_user_id,
        cursor_payload=cursor_payload or {},
        limit=limit,
        with_total=with_total,
    )
    return [_serialize_flatmate_notification(row) for row in rows], next_payload, total


async def mark_flatmates_notification_read(
    db: AsyncSession,
    user_id: int,
    notification_id: str,
) -> dict[str, Any]:
    user = await db.get(User, user_id)
    if user is None:
        raise BadRequestException(detail="User not found")
    supa = _supa()

    def _sync_mark_read():
        res = (
            supa.table("notifications")
            .select("id,data,target_user_id")
            .eq("id", notification_id)
            .eq("target_user_id", user.supabase_user_id)
            .limit(1)
            .execute()
        )
        if not res.data:
            return None
        row = res.data[0]
        data = dict(row.get("data") or {})
        data["is_read"] = True
        data["read_at"] = datetime.now(timezone.utc).isoformat()
        supa.table("notifications").update({"data": data}).eq("id", notification_id).execute()
        return True

    result = await asyncio.to_thread(_sync_mark_read)
    if result is None:
        raise BadRequestException(detail="Notification not found")
    return {"ok": True, "id": notification_id, "is_read": True}


async def mark_all_flatmates_notifications_read(db: AsyncSession, user_id: int) -> dict[str, Any]:
    user = await db.get(User, user_id)
    if user is None:
        raise BadRequestException(detail="User not found")

    def _sync_mark_all_read():
        supa = _supa()
        now = datetime.now(timezone.utc).isoformat()
        # Fetch only unread notifications to minimise round-trips
        res = (
            supa.table("notifications")
            .select("id,data")
            .eq("target_user_id", user.supabase_user_id)
            .execute()
        )
        count = 0
        for row in res.data or []:
            data = dict(row.get("data") or {})
            if data.get("is_read"):
                continue
            data["is_read"] = True
            data["read_at"] = now
            supa.table("notifications").update({"data": data}).eq("id", row["id"]).execute()
            count += 1
        return count

    count = await asyncio.to_thread(_sync_mark_all_read)
    return {"ok": True, "updated": count}


async def get_bootstrap(db: AsyncSession, user_id: int) -> dict[str, Any]:
    user = await db.get(User, user_id)
    if user is None:
        raise BadRequestException(detail="User not found")

    catalogs = await list_catalogs(db)

    listing_count_stmt = select(func.count(Property.id)).where(
        Property.owner_id == user_id,
        Property.property_type.in_([PropertyType.flatmate, PropertyType.pg]),
        Property.purpose == PropertyPurpose.rent,
        Property.is_available.is_(True),
    )
    listing_count = int((await db.execute(listing_count_stmt)).scalar() or 0)

    conversation_count_stmt = select(func.count(UserConversation.id)).where(
        or_(
            UserConversation.user_one_id == user_id,
            UserConversation.user_two_id == user_id,
        )
    )
    conversation_count = int((await db.execute(conversation_count_stmt)).scalar() or 0)

    unread_count_stmt = (
        select(func.count(UserMessage.id))
        .join(UserConversation, UserConversation.id == UserMessage.conversation_id)
        .where(
            or_(
                UserConversation.user_one_id == user_id,
                UserConversation.user_two_id == user_id,
            ),
            UserMessage.sender_id != user_id,
            UserMessage.read_at.is_(None),
        )
    )
    unread_count = int((await db.execute(unread_count_stmt)).scalar() or 0)

    return {
        "profile": _build_profile_payload(user),
        "catalogs": catalogs,
        "active_listing_count": listing_count,
        "conversation_count": conversation_count,
        "unread_message_count": unread_count,
    }
