"""Shared helpers for the flatmates service package."""

from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.enums import FlatmatesProfileStatus, UserMatchStatus
from app.models.properties import Property
from app.models.social import UserBlock, UserMatch
from app.models.users import User
from app.utils.geo import wkt_point

logger = get_logger(__name__)


def _canonical_pair(user_id: int, other_user_id: int) -> tuple[int, int]:
    return (user_id, other_user_id) if user_id < other_user_id else (other_user_id, user_id)


def _flatmates_preferences(user: User) -> dict[str, Any]:
    if not isinstance(user.preferences, dict):
        return {}
    raw = user.preferences.get("flatmates")
    return raw if isinstance(raw, dict) else {}


def _profile_age(user: User, prefs: dict[str, Any]) -> int | None:
    raw_age = prefs.get("age")
    if isinstance(raw_age, int):
        return raw_age
    if isinstance(raw_age, float):
        return int(raw_age)
    if isinstance(raw_age, str) and raw_age.isdigit():
        return int(raw_age)
    if user.date_of_birth is None:
        return None
    today = date.today()
    born = user.date_of_birth.date() if hasattr(user.date_of_birth, "date") else user.date_of_birth
    return today.year - born.year - ((today.month, today.day) < (born.month, born.day))


def _profile_profession(prefs: dict[str, Any]) -> str | None:
    raw = prefs.get("profession")
    return str(raw).strip() if raw is not None and str(raw).strip() else None


def _profile_gender(prefs: dict[str, Any]) -> str | None:
    raw = prefs.get("gender")
    return str(raw).strip() if raw is not None and str(raw).strip() else None


def _profile_gender_preference(prefs: dict[str, Any]) -> str | None:
    raw = prefs.get("gender_preference")
    return str(raw).strip() if raw is not None and str(raw).strip() else None


def _profile_non_negotiables(prefs: dict[str, Any]) -> list[str]:
    raw = prefs.get("non_negotiables")
    if not isinstance(raw, list):
        return []
    return [str(value) for value in raw if str(value).strip()]


def _compatibility_percentage(current_user: User | None, peer: User) -> float | None:
    if current_user is None:
        return None
    fields = (
        ("flatmates_sleep_schedule", 18),
        ("flatmates_cleanliness", 18),
        ("flatmates_food_habits", 16),
        ("flatmates_smoking_drinking", 18),
        ("flatmates_guests_policy", 14),
        ("flatmates_work_style", 16),
    )
    possible = 0
    score = 0
    for attr, weight in fields:
        current_value = getattr(current_user, attr, None)
        peer_value = getattr(peer, attr, None)
        if current_value is None or peer_value is None:
            continue
        possible += weight
        if current_value == peer_value:
            score += weight
    if possible == 0:
        return None
    return round((score / possible) * 100, 1)


def _build_profile_payload(user: User) -> dict[str, Any]:
    prefs = _flatmates_preferences(user)
    return {
        "id": user.id,
        "full_name": user.full_name,
        "email": user.email,
        "phone": user.phone,
        "profile_image_url": user.profile_image_url,
        "mode": user.flatmates_mode,
        "profile_status": user.flatmates_profile_status or FlatmatesProfileStatus.draft,
        "onboarding_completed": user.flatmates_onboarding_completed,
        "bio": user.flatmates_bio,
        "age": _profile_age(user, prefs),
        "profession": _profile_profession(prefs),
        "budget_min": user.flatmates_budget_min,
        "budget_max": user.flatmates_budget_max,
        "move_in_timeline": user.flatmates_move_in_timeline,
        "city": user.flatmates_city,
        "locality": user.flatmates_locality,
        "sleep_schedule": user.flatmates_sleep_schedule,
        "cleanliness": user.flatmates_cleanliness,
        "food_habits": user.flatmates_food_habits,
        "smoking_drinking": user.flatmates_smoking_drinking,
        "guests_policy": user.flatmates_guests_policy,
        "work_style": user.flatmates_work_style,
        "gender": _profile_gender(prefs),
        "gender_preference": _profile_gender_preference(prefs),
        "preferences": prefs,
        "last_active_at": user.flatmates_last_active_at,
    }


def _build_peer_payload(user: User, current_user: User | None = None) -> dict[str, Any]:
    prefs = _flatmates_preferences(user)
    return {
        "id": user.id,
        "full_name": user.full_name,
        "profile_image_url": user.profile_image_url,
        "mode": user.flatmates_mode,
        "city": user.flatmates_city,
        "locality": user.flatmates_locality,
        "age": _profile_age(user, prefs),
        "profession": _profile_profession(prefs),
        "bio": user.flatmates_bio,
        "budget_min": user.flatmates_budget_min,
        "budget_max": user.flatmates_budget_max,
        "move_in_timeline": user.flatmates_move_in_timeline,
        "sleep_schedule": user.flatmates_sleep_schedule,
        "cleanliness": user.flatmates_cleanliness,
        "food_habits": user.flatmates_food_habits,
        "smoking_drinking": user.flatmates_smoking_drinking,
        "guests_policy": user.flatmates_guests_policy,
        "work_style": user.flatmates_work_style,
        "gender": _profile_gender(prefs),
        "gender_preference": _profile_gender_preference(prefs),
        "non_negotiables": _profile_non_negotiables(prefs),
        "has_pets": str(prefs.get("pets", "")).strip().lower()
        in {"have_pets", "has_pets", "yes", "true"},
        "party_habit": (
            str(prefs["parties_at_home"]) if prefs.get("parties_at_home") is not None else None
        ),
        "match_percentage": _compatibility_percentage(current_user, user),
        "phone_number": user.phone,
    }


def _build_property_context(property_obj: Property | None) -> dict[str, Any] | None:
    if property_obj is None:
        return None
    return {
        "id": property_obj.id,
        "title": property_obj.title,
        "locality": property_obj.locality,
        "city": property_obj.city,
        "monthly_rent": property_obj.monthly_rent,
        "main_image_url": property_obj.main_image_url,
        "owner_name": property_obj.owner_name,
        "owner_image_url": None,
    }


async def _is_blocked(db: AsyncSession, user_id: int, other_user_id: int) -> bool:
    stmt = select(UserBlock.id).where(
        or_(
            and_(
                UserBlock.blocker_user_id == user_id,
                UserBlock.blocked_user_id == other_user_id,
            ),
            and_(
                UserBlock.blocker_user_id == other_user_id,
                UserBlock.blocked_user_id == user_id,
            ),
        )
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none() is not None


def _notification_type(row: dict[str, Any]) -> str:
    data: dict[str, Any] = row.get("data") or {}
    raw_meta = data.get("_meta")
    meta = raw_meta if isinstance(raw_meta, dict) else {}
    return str(meta.get("type_key") or data.get("type") or data.get("type_key") or "general")


def _notification_reference_id(row: dict[str, Any]) -> int | None:
    data = row.get("data") or {}
    for key in ("reference_id", "conversation_id", "property_id", "visit_id", "listing_id"):
        raw = data.get(key)
        if raw is None:
            continue
        try:
            return int(raw)
        except (TypeError, ValueError):
            continue
    return None


def _serialize_flatmate_notification(row: dict[str, Any]) -> dict[str, Any]:
    data = row.get("data") or {}
    return {
        "id": str(row.get("id")),
        "type": _notification_type(row),
        "title": row.get("title") or "Notification",
        "body": row.get("body") or "",
        "is_read": bool(data.get("is_read") or data.get("read_at")),
        "reference_id": _notification_reference_id(row),
        "route": data.get("route") or data.get("deep_link"),
        "created_at": row.get("created_at"),
    }


async def _ensure_match(
    db: AsyncSession,
    *,
    user_id: int,
    other_user_id: int,
    context_property_id: int | None = None,
) -> UserMatch:
    user_one_id, user_two_id = _canonical_pair(user_id, other_user_id)
    stmt = select(UserMatch).where(
        UserMatch.user_one_id == user_one_id,
        UserMatch.user_two_id == user_two_id,
    )
    result = await db.execute(stmt)
    match = result.scalar_one_or_none()
    if match:
        if context_property_id is not None:
            match.context_property_id = context_property_id
        if match.status != UserMatchStatus.active.value:
            match.status = UserMatchStatus.active
        return match

    match = UserMatch(
        user_one_id=user_one_id,
        user_two_id=user_two_id,
        context_property_id=context_property_id,
        status=UserMatchStatus.active,
    )
    db.add(match)
    await db.flush()
    return match


async def geocode_listing(db: AsyncSession, property_id: int) -> None:
    """Best-effort geocoding for a listing. Uses Google Maps Geocoding API if configured."""
    import os

    api_key = os.getenv("GOOGLE_MAPS_API_KEY")
    if not api_key:
        return

    stmt = select(Property).where(Property.id == property_id)
    prop = (await db.execute(stmt)).scalar_one_or_none()
    if prop is None:
        return
    if prop.latitude is not None and prop.longitude is not None:
        if prop.location is None:
            prop.location = wkt_point(prop.longitude, prop.latitude)
            await db.flush()
        return

    address_parts = [prop.full_address, prop.locality, prop.city, prop.state]
    address = ", ".join(p for p in address_parts if p)
    if not address:
        return

    try:
        import httpx

        async with httpx.AsyncClient() as client:
            resp = await client.get(
                "https://maps.googleapis.com/maps/api/geocode/json",
                params={"address": address, "key": api_key},
                timeout=10,
            )
            data = resp.json()
            if data.get("results"):
                loc = data["results"][0]["geometry"]["location"]
                prop.latitude = loc["lat"]
                prop.longitude = loc["lng"]
                prop.location = wkt_point(prop.longitude, prop.latitude)
                await db.flush()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Property geocoding failed (best-effort): %s", exc, exc_info=True)
        pass
