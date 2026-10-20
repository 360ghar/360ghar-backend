"""
Guest discovery tools — public property search, detail, and recommendation.

These tools do not require authentication and allow unauthenticated users
to browse and discover properties. Search runs through the shared
``search_properties`` body in ``app.mcp.tool_ops`` (the MCP discovery tool uses it too).
"""

from __future__ import annotations

from typing import Any

from pydantic_ai import RunContext

from app.core.logging import get_logger
from app.mcp.tool_ops import search_properties
from app.mcp.utils import serialize_property_basic, serialize_property_full
from app.models.enums import PropertyPurpose, PropertyType
from app.schemas.pagination import decode_cursor, encode_cursor
from app.services.ai_agent.tools.helpers import AgentDeps
from app.services.visibility import Viewer, mask_owner_contact

logger = get_logger(__name__)

SEARCH_MAX_LIMIT = 50
RECOMMENDATION_MAX_LIMIT = 20


def _viewer(ctx: RunContext[AgentDeps]) -> Viewer:
    return Viewer.from_user(ctx.deps.user)


async def guest_property_search(
    ctx: RunContext[AgentDeps],
    query: str | None = None,
    city: str | None = None,
    locality: str | None = None,
    latitude: float | None = None,
    longitude: float | None = None,
    radius_km: int = 5,
    property_type: PropertyType | list[PropertyType] | None = None,
    purpose: PropertyPurpose | None = None,
    price_min: float | None = None,
    price_max: float | None = None,
    bedrooms_min: int | None = None,
    bedrooms_max: int | None = None,
    amenities: list[str] | None = None,
    cursor: str | None = None,
    limit: int = 20,
    include_total: bool = False,
) -> dict[str, Any]:
    """Search for properties with optional filters. No authentication required.

    ``property_type`` takes one type or a list of types. ``latitude``, ``longitude``
    and ``radius_km`` search around a point. ``cursor`` is the ``next_cursor`` of an
    earlier result, for the next page of the same search. ``total`` is set only when
    ``include_total`` is true.
    """
    db = ctx.deps.db
    assert db is not None

    limit = min(max(1, limit), SEARCH_MAX_LIMIT)
    types = [property_type] if isinstance(property_type, PropertyType) else property_type
    filter_key = {
        "query": query,
        "city": city,
        "locality": locality,
        "latitude": latitude,
        "longitude": longitude,
        "radius_km": radius_km,
        "property_type": [t.value for t in types] if types else None,
        "purpose": purpose.value if purpose else None,
        "price_min": price_min,
        "price_max": price_max,
        "bedrooms_min": bedrooms_min,
        "bedrooms_max": bedrooms_max,
        "amenities": amenities,
    }
    filter_key = {k: v for k, v in filter_key.items() if v is not None}
    cursor_payload = decode_cursor(cursor, filter_key) if cursor else {}

    user = ctx.deps.user
    rows, next_payload, total = await search_properties(
        db,
        query=query,
        latitude=latitude,
        longitude=longitude,
        radius_km=radius_km,
        amenities=amenities,
        property_type=types,
        purpose=purpose,
        price_min=price_min,
        price_max=price_max,
        bedrooms_min=bedrooms_min,
        bedrooms_max=bedrooms_max,
        city=city,
        locality=locality,
        user_id=getattr(user, "id", None),
        cursor_payload=cursor_payload,
        limit=limit,
        with_total=include_total,
    )
    viewer = _viewer(ctx)
    items = [serialize_property_basic(mask_owner_contact(p, viewer)) for p in rows]
    return {
        "items": items,
        "total": total,
        "limit": limit,
        "has_more": next_payload is not None,
        "next_cursor": encode_cursor(next_payload, filter_key) if next_payload else None,
    }


async def guest_property_details(
    ctx: RunContext[AgentDeps],
    property_id: int,
) -> dict[str, Any]:
    """Get full details for a specific property. No authentication required."""
    from app.services.property import get_property

    db = ctx.deps.db
    assert db is not None

    property_obj = await get_property(db, property_id)
    masked = mask_owner_contact(property_obj, _viewer(ctx))
    return {"property": dict(serialize_property_full(masked, viewer=_viewer(ctx)))}


async def guest_property_recommendations(
    ctx: RunContext[AgentDeps],
    city: str | None = None,
    purpose: PropertyPurpose | None = None,
    limit: int = 10,
) -> dict[str, Any]:
    """Get a list of recommended properties for discovery. No authentication required."""
    db = ctx.deps.db
    assert db is not None

    limit = min(max(1, limit), RECOMMENDATION_MAX_LIMIT)
    rows, _next, _total = await search_properties(
        db,
        purpose=purpose,
        city=city,
        user_id=getattr(ctx.deps.user, "id", None),
        limit=limit,
    )
    viewer = _viewer(ctx)
    items = [serialize_property_basic(mask_owner_contact(p, viewer)) for p in rows]
    return {"items": items, "limit": limit}
