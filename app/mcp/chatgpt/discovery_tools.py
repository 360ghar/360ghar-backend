"""
Discovery tools for ChatGPT App.

These tools enable property discovery features:
- Search properties with comprehensive filters
- Get property details
- Discovery feed (swipe-style)
- List amenities
- Record swipes (likes/passes)
- Get shortlist (liked properties)
- Get AI recommendations
"""
from __future__ import annotations

from typing import Any

from app.core.database import AsyncSessionLocal
from app.core.exceptions import PropertyNotFoundException
from app.core.logging import get_logger
from app.mcp.apps_sdk import (
    MCP_SECURITY_SCHEMES_MIXED,
    MCP_SECURITY_SCHEMES_OAUTH2_ONLY,
    AppsSDKToolResult,
    AuthRequiredError,
    build_widget_tool_meta,
)
from app.mcp.chatgpt import get_widget_for_tool
from app.mcp.chatgpt.response_formatter import (
    format_auth_required_response,
    format_chatgpt_response,
    format_property_detail_summary,
    format_property_list_summary,
)
from app.mcp.errors import mcp_exception_payload
from app.mcp.tool_ops.search_ops import (
    build_empty_result_message,
    normalize_city,
    parse_natural_query,
)

# Import the user MCP server to register tools
from app.mcp.user.server import user_mcp
from app.mcp.utils import (
    get_user_from_mcp_context,
    serialize_property_basic,
    serialize_property_full,
)
from app.models.enums import PropertyPurpose, PropertyType
from app.schemas.pagination import decode_cursor, encode_cursor
from app.schemas.property import PropertySwipe, UnifiedPropertyFilter
from app.services.property.search_orchestration import (
    build_property_search_filters,
    run_property_search,
)

logger = get_logger(__name__)

# ChatGPT tool metadata for widget linkage
DISCOVERY_SEARCH_META = build_widget_tool_meta(
    widget_uri="ui://widget/propertysearchwidget.html",
    invoking="Searching for properties...",
    invoked="Found properties",
)

PROPERTY_DETAILS_META = build_widget_tool_meta(
    widget_uri="ui://widget/propertydetailswidget.html",
    invoking="Loading property details...",
    invoked="Property details loaded",
)

DISCOVERY_FEED_META = build_widget_tool_meta(
    widget_uri="ui://widget/propertyswipewidget.html",
    invoking="Loading discovery feed...",
    invoked="Discovery feed ready",
)

SHORTLIST_META = build_widget_tool_meta(
    widget_uri="ui://widget/propertysearchwidget.html",
    invoking="Loading your shortlist...",
    invoked="Shortlist loaded",
)


async def _get_db():
    """Get database session."""
    async with AsyncSessionLocal() as db:
        yield db


async def _get_optional_user(db):
    """Get user if authenticated, None for guests."""
    return await get_user_from_mcp_context(db)


def _safe_discovery_error_response(
    *,
    exc: Exception,
    tool_name: str,
    fallback_message: str,
) -> AppsSDKToolResult:
    """Return a safe ChatGPT Apps error response for unexpected failures."""
    payload = mcp_exception_payload(
        exc,
        logger=logger,
        tool_name=tool_name,
        fallback_message=fallback_message,
    )
    return format_chatgpt_response(
        data=payload,
        content_summary=payload["message"],
        is_error=True,
        widget_uri=get_widget_for_tool(tool_name),
    )


# ============================================================================
# Guest-Accessible Discovery Tools
# ============================================================================


@user_mcp.tool(
    "discovery_search",
    annotations={
        "title": "Search Properties",
        "readOnlyHint": True,
        "openWorldHint": False,
        "destructiveHint": False,
        "securitySchemes": MCP_SECURITY_SCHEMES_MIXED,
    },
    meta=DISCOVERY_SEARCH_META,
)
async def discovery_search(
    query: str | None = None,
    latitude: float | None = None,
    longitude: float | None = None,
    radius_km: int = 5,
    property_type: str | None = None,
    purpose: str | None = None,
    price_min: float | None = None,
    price_max: float | None = None,
    bedrooms_min: int | None = None,
    bedrooms_max: int | None = None,
    amenities: list[str] | None = None,
    city: str | None = None,
    locality: str | None = None,
    cursor: str | None = None,
    limit: int | None = None,
    # ChatGPT / Apps SDK sometimes send multi-query batches and max_results
    # instead of the canonical query + limit shape.
    queries: list[dict[str, Any]] | None = None,
    max_results: int | None = None,
) -> AppsSDKToolResult:
    """Search properties with comprehensive filtering.

    Search for properties using text search, location-based search, or filters.
    Results are sorted by relevance for text search, or by distance for location search.

    This tool is guest-accessible - no authentication required.

    Args:
        query: Text search for property title, description, or locality
        latitude: Search center latitude for location-based search
        longitude: Search center longitude for location-based search
        radius_km: Search radius in kilometers (default 5, max 100)
        property_type: Filter by type (house, apartment, builder_floor, room)
        purpose: Filter by purpose (buy, rent, short_stay)
        price_min: Minimum price filter
        price_max: Maximum price filter
        bedrooms_min: Minimum number of bedrooms
        bedrooms_max: Maximum number of bedrooms
        amenities: List of required amenity names
        city: Filter by city name
        locality: Filter by locality/neighborhood
        cursor: Opaque pagination cursor from a prior response's next_cursor
        limit: Results per page (max 50). Canonical limit parameter.
        queries: Optional ChatGPT-style batch: list of {query, max_results}.
            First entry is used when query/limit are not set.
        max_results: Alias for limit (ChatGPT clients often send this).

    Returns:
        Property search results with pagination info.
    """
    try:
        # Normalize ChatGPT multi-query / max_results aliases into query + limit.
        # Only fill gaps: explicit top-level query/limit always win.
        if queries:
            first = queries[0] if isinstance(queries, list) and queries else None
            if isinstance(first, dict):
                if query is None and first.get("query") is not None:
                    query = str(first["query"]) or None
                if max_results is None and first.get("max_results") is not None:
                    try:
                        max_results = int(first["max_results"])
                    except (TypeError, ValueError):
                        pass
                # Some clients nest limit inside the batch item
                if limit is None and first.get("limit") is not None:
                    try:
                        limit = int(first["limit"])
                    except (TypeError, ValueError):
                        pass
        if limit is None:
            limit = max_results if max_results is not None else 20
        # Validate and clamp limit
        try:
            limit = min(max(1, int(limit)), 50)
        except (TypeError, ValueError):
            limit = 20
        cursor_payload = decode_cursor(cursor) if cursor else {}

        # Coerce amenities from string to list (MCP clients may send "wifi,pool" as a string)
        if isinstance(amenities, str):
            amenities = [a.strip() for a in amenities.split(",") if a.strip()]
        elif amenities is not None and not isinstance(amenities, list):
            amenities = [str(amenities)]

        # Apply city alias normalization
        if city:
            city = normalize_city(city)

        # Parse natural language query into structured filters
        parsed_query: dict[str, Any] = {}
        if query:
            parsed_query = parse_natural_query(query)
            # Merge parsed filters with explicit parameters (explicit params take precedence)
            if "bedrooms" in parsed_query:
                # BHK queries like "3BHK" should return exactly N-bedroom properties
                if bedrooms_min is None:
                    bedrooms_min = parsed_query["bedrooms"]
                if bedrooms_max is None:
                    bedrooms_max = parsed_query["bedrooms"]
            if price_max is None and "price_max" in parsed_query:
                price_max = parsed_query["price_max"]
            if price_min is None and "price_min" in parsed_query:
                price_min = parsed_query["price_min"]
            if city is None and "city" in parsed_query:
                city = parsed_query["city"]
            if property_type is None and "property_types" in parsed_query:
                property_type = parsed_query["property_types"][0]
            if purpose is None and "purpose" in parsed_query:
                purpose = parsed_query["purpose"]
            # Use cleaned query for FTS if available (empty string means all
            # meaningful tokens were extracted as structured filters)
            if "cleaned_query" in parsed_query:
                query = parsed_query["cleaned_query"] or None

        async with AsyncSessionLocal() as db:
            # Get optional user for personalization
            user = await _get_optional_user(db)
            user_id = user.id if user else None

            # Build filter object with validated enums
            purpose_val: PropertyPurpose | None = None
            if purpose:
                try:
                    purpose_val = PropertyPurpose(purpose)
                except ValueError:
                    valid = [e.value for e in PropertyPurpose]
                    return format_chatgpt_response(
                        data={"error": True, "message": f"Invalid purpose: '{purpose}'. Valid values: {valid}"},
                        content_summary=f"Invalid purpose '{purpose}'. Valid options are: {', '.join(valid)}.",
                        widget_uri=get_widget_for_tool("discovery_search"),
                    )

            property_type_val: list[PropertyType] | None = None
            if property_type:
                try:
                    property_type_val = [PropertyType(property_type)]
                except ValueError:
                    valid = [e.value for e in PropertyType]
                    return format_chatgpt_response(
                        data={"error": True, "message": f"Invalid property_type: '{property_type}'. Valid values: {valid}"},
                        content_summary=f"Invalid property type '{property_type}'. Valid options are: {', '.join(valid)}.",
                        widget_uri=get_widget_for_tool("discovery_search"),
                    )

            filters = build_property_search_filters(
                search_query=query,
                latitude=latitude,
                longitude=longitude,
                property_type=property_type_val,
                purpose=purpose_val,
                price_min=price_min,
                price_max=price_max,
                bedrooms_min=bedrooms_min,
                bedrooms_max=bedrooms_max,
                amenities=amenities,
                city=city,
                locality=locality,
                radius_km=radius_km if (latitude is not None and longitude is not None) else 5,
            )

            # Execute search
            rows, next_payload, total_count = await run_property_search(
                db=db,
                filters=filters,
                user_id=user_id,
                cursor_payload=cursor_payload,
                limit=limit,
                with_total=True,
                endpoint_name="discovery_search",
                stale_listing_context="ChatGPT discovery search",
                unavailable_detail="Property search is temporarily unavailable. Please retry shortly.",
            )

            # Serialize properties
            properties = [serialize_property_basic(p) for p in rows]
            total = total_count or 0

            # Format response
            filters_applied = {
                k: v for k, v in {
                    "query": query,
                    "property_type": property_type,
                    "purpose": purpose,
                    "price_min": price_min,
                    "price_max": price_max,
                    "bedrooms_min": bedrooms_min,
                    "bedrooms_max": bedrooms_max,
                    "city": city,
                    "locality": locality,
                }.items() if v is not None
            }

            # Provide helpful message when no results found
            if total == 0:
                content_summary = build_empty_result_message(filters_applied, city=city)
            else:
                content_summary = format_property_list_summary(properties, total, filters_applied)

            return format_chatgpt_response(
                data={
                    "properties": properties,
                    "total": total,
                    "next_cursor": encode_cursor(next_payload) if next_payload else None,
                    "has_more": next_payload is not None,
                    "limit": limit,
                    "filters_applied": filters_applied,
                },
                content_summary=content_summary,
                meta={
                    "search_center": {"latitude": latitude, "longitude": longitude} if latitude and longitude else None,
                },
                widget_uri=get_widget_for_tool("discovery_search"),
            )

    except Exception as e:
        return _safe_discovery_error_response(
            exc=e,
            tool_name="discovery_search",
            fallback_message=(
                "Sorry, there was an error searching properties. Please try again."
            ),
        )


@user_mcp.tool(
    "discovery_property_get",
    annotations={
        "title": "Get Property Details",
        "readOnlyHint": True,
        "openWorldHint": False,
        "destructiveHint": False,
        "securitySchemes": MCP_SECURITY_SCHEMES_MIXED,
    },
    meta=PROPERTY_DETAILS_META,
)
async def discovery_property_get(
    property_id: int,
) -> AppsSDKToolResult:
    """Get detailed information about a property.

    Retrieves full property details including images, amenities, and location.
    This tool is guest-accessible - no authentication required.

    Args:
        property_id: The property ID to retrieve

    Returns:
        Full property details.
    """
    try:
        from app.services.property import get_property

        async with AsyncSessionLocal() as db:
            # Get optional user to check if property is liked
            user = await _get_optional_user(db)

            # Get property details
            property_obj = await get_property(db, property_id)

            # Serialize with full details
            property_data = serialize_property_full(property_obj)  # type: ignore[arg-type]

            # Check if user has liked this property
            if user:
                from app.services.swipe import get_user_like_for_property
                liked = await get_user_like_for_property(db, user.id, property_id)
                property_data["user_liked"] = liked

            return format_chatgpt_response(
                data={"property": property_data},
                content_summary=format_property_detail_summary(property_data),
                widget_uri=get_widget_for_tool("discovery_property_get"),
            )

    except PropertyNotFoundException:
        return format_chatgpt_response(
            data={"error": True, "code": "NOT_FOUND", "property_id": property_id},
            content_summary=f"Property with ID {property_id} was not found.",
            is_error=True,
            widget_uri=get_widget_for_tool("discovery_property_get"),
        )
    except Exception as e:
        return _safe_discovery_error_response(
            exc=e,
            tool_name="discovery_property_get",
            fallback_message=(
                "Sorry, there was an error retrieving the property. Please try again."
            ),
        )


@user_mcp.tool(
    "discovery_feed",
    annotations={
        "title": "Property Discovery Feed",
        "readOnlyHint": True,
        "openWorldHint": False,
        "destructiveHint": False,
        "securitySchemes": MCP_SECURITY_SCHEMES_MIXED,
    },
    meta=DISCOVERY_FEED_META,
)
async def discovery_feed(
    latitude: float | None = None,
    longitude: float | None = None,
    purpose: str | None = None,
    limit: int = 10,
) -> AppsSDKToolResult:
    """Get a discovery feed of properties for swipe-style browsing.

    Returns properties for a swipe-style discovery interface.
    If authenticated, excludes properties already swiped by the user.
    If location is provided, prioritizes nearby properties.

    This tool is guest-accessible - no authentication required.

    Args:
        latitude: User's current latitude for personalized recommendations
        longitude: User's current longitude for personalized recommendations
        purpose: Filter by purpose (buy, rent, short_stay)
        limit: Number of properties to return (max 20)

    Returns:
        List of properties for discovery feed.
    """
    try:
        limit = min(max(1, limit), 20)

        async with AsyncSessionLocal() as db:
            user = await _get_optional_user(db)
            user_id = user.id if user else None

            # Build filters
            purpose_val: PropertyPurpose | None = None
            if purpose:
                try:
                    purpose_val = PropertyPurpose(purpose)
                except ValueError:
                    valid = [e.value for e in PropertyPurpose]
                    return format_chatgpt_response(
                        data={"error": True, "message": f"Invalid purpose: '{purpose}'. Valid values: {valid}"},
                        content_summary=f"Invalid purpose '{purpose}'. Valid options are: {', '.join(valid)}.",
                        widget_uri=get_widget_for_tool("discovery_feed"),
                    )

            filters = build_property_search_filters(
                latitude=latitude,
                longitude=longitude,
                radius_km=50,  # Wider radius for feed
                purpose=purpose_val,
            )

            # Get properties
            rows, _next, _total = await run_property_search(
                db=db,
                filters=filters,
                user_id=user_id,
                cursor_payload={},
                limit=limit,
                endpoint_name="discovery_feed",
                stale_listing_context="ChatGPT discovery feed",
                unavailable_detail="Discovery feed is temporarily unavailable. Please retry shortly.",
            )

            properties = [serialize_property_basic(p) for p in rows]

            return format_chatgpt_response(
                data={
                    "properties": properties,
                    "count": len(properties),
                    "is_personalized": user_id is not None,
                },
                content_summary=f"Here are {len(properties)} properties for you to discover. Swipe right to like or left to pass.",
                widget_uri=get_widget_for_tool("discovery_feed"),
            )

    except Exception as e:
        return _safe_discovery_error_response(
            exc=e,
            tool_name="discovery_feed",
            fallback_message=(
                "Sorry, there was an error loading the discovery feed. Please try again."
            ),
        )


@user_mcp.tool(
    "discovery_amenities",
    annotations={
        "title": "List Property Amenities",
        "readOnlyHint": True,
        "openWorldHint": False,
        "destructiveHint": False,
        "securitySchemes": MCP_SECURITY_SCHEMES_MIXED,
    },
)
async def discovery_amenities() -> AppsSDKToolResult:
    """Get list of available amenities for filtering.

    Returns all available amenities that can be used to filter property searches.
    This tool is guest-accessible - no authentication required.

    Returns:
        List of amenity names and IDs.
    """
    try:
        from sqlalchemy import select

        from app.models.properties import Amenity

        async with AsyncSessionLocal() as db:
            result = await db.execute(select(Amenity).order_by(Amenity.title))
            amenities = result.scalars().all()

            amenity_list: list[dict[str, Any]] = [
                {"id": a.id, "name": a.title, "icon": a.icon}
                for a in amenities
            ]

            return format_chatgpt_response(
                data={"amenities": amenity_list, "count": len(amenity_list)},
                content_summary=f"There are {len(amenity_list)} amenities available for filtering, including {', '.join([str(a['name']) for a in amenity_list[:5]])} and more.",
                widget_uri=get_widget_for_tool("discovery_amenities"),
            )

    except Exception as e:
        return _safe_discovery_error_response(
            exc=e,
            tool_name="discovery_amenities",
            fallback_message=(
                "Sorry, there was an error loading amenities. Please try again."
            ),
        )


# ============================================================================
# Authentication Required Discovery Tools
# ============================================================================


@user_mcp.tool(
    "discovery_swipe",
    annotations={
        "title": "Like or Pass Property",
        "readOnlyHint": False,
        "openWorldHint": False,
        "destructiveHint": False,
        "securitySchemes": MCP_SECURITY_SCHEMES_OAUTH2_ONLY,
    },
    meta=build_widget_tool_meta(
        widget_uri="ui://widget/propertyswipewidget.html",
        invoking="Recording your preference...",
        invoked="Preference saved",
    ),
)
async def discovery_swipe(
    property_id: int,
    is_liked: bool,
) -> AppsSDKToolResult:
    """Record a swipe action on a property (like or pass).

    Records the user's swipe action for a property. Use is_liked=true for
    liking (right swipe) and is_liked=false for passing (left swipe).

    This tool requires authentication.

    Args:
        property_id: Property ID being swiped
        is_liked: True for like (right swipe), False for pass (left swipe)

    Returns:
        Confirmation of the swipe action.
    """
    try:
        from app.services.swipe import record_swipe

        async with AsyncSessionLocal() as db:
            user = await _get_optional_user(db)

            if not user:
                return format_auth_required_response(
                    action="swipe",
                    message="To save properties to your shortlist, please log in to your 360Ghar account.",
                    context={"property_id": property_id, "is_liked": is_liked},
                )

            # Record swipe
            swipe_data = PropertySwipe(property_id=property_id, is_liked=is_liked)
            success = await record_swipe(db, user.id, swipe_data)
            await db.commit()

            action = "liked" if is_liked else "passed on"

            return format_chatgpt_response(
                data={
                    "success": success,
                    "property_id": property_id,
                    "is_liked": is_liked,
                },
                content_summary=f"You {action} this property. {'It has been added to your shortlist.' if is_liked else ''}",
                widget_uri=get_widget_for_tool("discovery_swipe"),
            )

    except AuthRequiredError:
        raise
    except Exception as e:
        return _safe_discovery_error_response(
            exc=e,
            tool_name="discovery_swipe",
            fallback_message=(
                "Sorry, there was an error recording your swipe. Please try again."
            ),
        )


@user_mcp.tool(
    "discovery_shortlist",
    annotations={
        "title": "View Shortlisted Properties",
        "readOnlyHint": True,
        "openWorldHint": False,
        "destructiveHint": False,
        "securitySchemes": MCP_SECURITY_SCHEMES_OAUTH2_ONLY,
    },
    meta=SHORTLIST_META,
)
async def discovery_shortlist(
    cursor: str | None = None,
    limit: int = 20,
) -> AppsSDKToolResult:
    """Get the user's shortlisted (liked) properties.

    Retrieves all properties the user has liked/swiped right on.

    This tool requires authentication.

    Args:
        cursor: Opaque pagination cursor from a prior response's next_cursor
        limit: Results per page (max 50)

    Returns:
        List of shortlisted properties.
    """
    try:
        from app.services.swipe import get_swipe_history

        limit = min(max(1, limit), 50)
        cursor_payload = decode_cursor(cursor) if cursor else {}

        async with AsyncSessionLocal() as db:
            user = await _get_optional_user(db)

            if not user:
                return format_auth_required_response(
                    action="shortlist",
                    message="To view your shortlisted properties, please log in to your 360Ghar account.",
                )

            # Get liked properties
            filters = UnifiedPropertyFilter()
            swipes, next_payload, total_count = await get_swipe_history(
                db,
                user_id=user.id,
                filters=filters,
                cursor_payload=cursor_payload,
                limit=limit,
                is_liked=True,  # Only liked properties
                with_total=True,
            )

            # Serialize properties from swipe items
            properties = []
            for swipe in swipes:
                if swipe.property:
                    prop_data = serialize_property_basic(swipe.property)
                    prop_data["swiped_at"] = swipe.created_at.isoformat() if swipe.created_at else None
                    properties.append(prop_data)

            total = total_count or 0

            return format_chatgpt_response(
                data={
                    "properties": properties,
                    "total": total,
                    "next_cursor": encode_cursor(next_payload) if next_payload else None,
                    "has_more": next_payload is not None,
                    "limit": limit,
                },
                content_summary=f"You have {total} properties in your shortlist. Showing {len(properties)} on this page.",
                widget_uri=get_widget_for_tool("discovery_shortlist"),
            )

    except AuthRequiredError:
        raise
    except Exception as e:
        return _safe_discovery_error_response(
            exc=e,
            tool_name="discovery_shortlist",
            fallback_message=(
                "Sorry, there was an error loading your shortlist. Please try again."
            ),
        )


@user_mcp.tool(
    "discovery_recommendations",
    annotations={
        "title": "Get Property Recommendations",
        "readOnlyHint": True,
        "openWorldHint": False,
        "destructiveHint": False,
        "securitySchemes": MCP_SECURITY_SCHEMES_OAUTH2_ONLY,
    },
    meta=build_widget_tool_meta(
        widget_uri="ui://widget/propertysearchwidget.html",
        invoking="Finding recommended properties...",
        invoked="Recommendations ready",
    ),
)
async def discovery_recommendations(
    latitude: float | None = None,
    longitude: float | None = None,
    limit: int = 10,
) -> AppsSDKToolResult:
    """Get AI-powered property recommendations based on user preferences.

    Provides personalized property recommendations based on the user's
    swipe history, preferences, and current location.

    This tool requires authentication for personalized recommendations.

    Args:
        latitude: User's current latitude for location-aware recommendations
        longitude: User's current longitude for location-aware recommendations
        limit: Number of recommendations to return (max 20)

    Returns:
        List of recommended properties.
    """
    try:
        from app.services.property import get_property_recommendations

        limit = min(max(1, limit), 20)

        async with AsyncSessionLocal() as db:
            user = await _get_optional_user(db)

            if not user:
                return format_auth_required_response(
                    action="recommendations",
                    message="To get personalized property recommendations, please log in to your 360Ghar account.",
                )

            # Get recommendations
            recommendations, _next, _total = await get_property_recommendations(
                db,
                user_id=user.id,
                cursor_payload={},
                limit=limit,
            )

            properties = [serialize_property_basic(p) for p in recommendations]

            return format_chatgpt_response(
                data={
                    "properties": properties,
                    "count": len(properties),
                    "personalized": True,
                },
                content_summary=f"Based on your preferences, here are {len(properties)} properties we think you'll love.",
                widget_uri=get_widget_for_tool("discovery_recommendations"),
            )

    except AuthRequiredError:
        raise
    except Exception as e:
        return _safe_discovery_error_response(
            exc=e,
            tool_name="discovery_recommendations",
            fallback_message=(
                "Sorry, there was an error generating recommendations. Please try again."
            ),
        )
