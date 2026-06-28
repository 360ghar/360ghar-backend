"""
Guest discovery tools — public property search, detail, and recommendation.

These tools do not require authentication and allow unauthenticated users
to browse and discover properties.
"""
from __future__ import annotations

from typing import Any

from pydantic_ai import RunContext

from app.core.logging import get_logger
from app.mcp.utils import serialize_property_basic, serialize_property_full
from app.services.ai_agent.tools.helpers import AgentDeps

logger = get_logger(__name__)


async def guest_property_search(
    ctx: RunContext[AgentDeps],
    query: str | None = None,
    city: str | None = None,
    locality: str | None = None,
    property_type: str | None = None,
    purpose: str | None = None,
    price_min: float | None = None,
    price_max: float | None = None,
    bedrooms_min: int | None = None,
    bedrooms_max: int | None = None,
    page: int = 1,
    limit: int = 20,
) -> dict[str, Any]:
    """Search for properties with optional filters. No authentication required."""
    from app.schemas.property import UnifiedPropertyFilter
    from app.services.property import get_unified_properties_optimized

    limit = min(max(1, limit), 50)
    page = max(1, page)

    filter_data: dict[str, Any] = {}
    if query:
        filter_data["search_query"] = query
    if city:
        filter_data["city"] = city
    if locality:
        filter_data["locality"] = locality
    if property_type:
        filter_data["property_type"] = property_type
    if purpose:
        filter_data["purpose"] = purpose
    if price_min is not None:
        filter_data["price_min"] = price_min
    if price_max is not None:
        filter_data["price_max"] = price_max
    if bedrooms_min is not None:
        filter_data["bedrooms_min"] = bedrooms_min
    if bedrooms_max is not None:
        filter_data["bedrooms_max"] = bedrooms_max

    filters = UnifiedPropertyFilter(**filter_data)
    rows, _next, total_count = await get_unified_properties_optimized(
        ctx.deps.db,
        filters=filters,
        user_id=None,
        cursor_payload={},
        limit=limit,
    )

    properties = [serialize_property_basic(p) for p in rows]
    return {
        "properties": properties,
        "count": len(properties),
        "page": page,
    }


async def guest_property_details(
    ctx: RunContext[AgentDeps],
    property_id: int,
) -> dict[str, Any]:
    """Get full details for a specific property. No authentication required."""
    from app.services.property import get_property

    property_obj = await get_property(ctx.deps.db, property_id)
    return {"property": dict(serialize_property_full(property_obj))}  # type: ignore[arg-type]


async def guest_property_recommendations(
    ctx: RunContext[AgentDeps],
    city: str | None = None,
    purpose: str | None = None,
    limit: int = 10,
) -> dict[str, Any]:
    """Get a list of recommended properties for discovery. No authentication required."""
    from app.schemas.property import UnifiedPropertyFilter
    from app.services.property import get_unified_properties_optimized

    limit = min(max(1, limit), 20)

    filter_data: dict[str, Any] = {}
    if city:
        filter_data["city"] = city
    if purpose:
        filter_data["purpose"] = purpose

    filters = UnifiedPropertyFilter(**filter_data)
    rows, _next, _total = await get_unified_properties_optimized(
        ctx.deps.db,
        filters=filters,
        user_id=None,
        cursor_payload={},
        limit=limit,
    )

    properties = [serialize_property_basic(p) for p in rows]
    return {
        "properties": properties,
        "count": len(properties),
    }
