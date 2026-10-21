"""Shared helpers for the property service package."""

from __future__ import annotations

from typing import Any

from app.core.exceptions import BadRequestException, ValidationException
from app.core.logging import get_logger
from app.models.enums import PG_FLATMATE_TYPES, FurnishingLevel, PropertyPurpose, PropertyType
from app.utils.geo import wkt_point

logger = get_logger(__name__)


def validate_listing_contract(property_type: PropertyType, purpose: PropertyPurpose) -> None:
    """Ensure PG/flatmate listings use purpose 'rent'."""
    if property_type in PG_FLATMATE_TYPES and purpose != PropertyPurpose.rent:
        raise BadRequestException(detail="PG and flatmate listings must use purpose 'rent'")


_validate_listing_contract = validate_listing_contract


def build_location_wkt(latitude: float | None, longitude: float | None) -> str | None:
    """Build a PostGIS WKT POINT string with SRID=4326.

    Returns None if either coordinate is missing.
    """
    if latitude is not None and longitude is not None:
        return wkt_point(longitude, latitude)
    return None


# A listing is as furnished as its most furnished room.
_FURNISHING_RANK = {
    FurnishingLevel.unfurnished.value: 0,
    FurnishingLevel.semi_furnished.value: 1,
    FurnishingLevel.furnished.value: 2,
}


def derive_furnishing_level(preferences: Any) -> str | None:
    """Furnishing level of a listing that carries room-level furnishing, or None.

    Rooms are ``listing_preferences["rooms"]``: a list of objects, each with a
    ``furnishing_level``. The result is the highest level across rooms (furnished >
    semi_furnished > unfurnished). A room without a level does not count. None means no
    room carries a level, so the caller keeps the client's ``furnishing_level``.
    A level outside the three values gives 422.
    """
    rooms = preferences.get("rooms") if isinstance(preferences, dict) else None
    if not isinstance(rooms, list):
        return None
    levels: list[str] = []
    for index, room in enumerate(rooms):
        level = room.get("furnishing_level") if isinstance(room, dict) else None
        if level is None:
            continue
        if not isinstance(level, str) or level not in _FURNISHING_RANK:
            raise ValidationException(
                detail=(
                    f"listing_preferences.rooms[{index}].furnishing_level must be one of: "
                    + ", ".join(_FURNISHING_RANK)
                )
            )
        levels.append(level)
    return max(levels, key=_FURNISHING_RANK.__getitem__) if levels else None
