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

from typing import Any, Dict, List, Optional

from app.core.database import AsyncSessionLocal
from app.core.logging import get_logger
from app.mcp.apps_sdk import AuthRequiredError, MCP_SECURITY_SCHEMES_MIXED, build_widget_tool_meta
from app.mcp.chatgpt.response_formatter import (
    format_chatgpt_response,
    format_auth_required_response,
    format_property_list_summary,
    format_property_detail_summary,
)
from app.mcp.utils import (
    get_user_from_mcp_context,
    serialize_property_basic,
    serialize_property_full,
)
from app.schemas.property import UnifiedPropertyFilter, PropertySwipe

# Import the user MCP server to register tools
from app.mcp.user_server import user_mcp

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


# ============================================================================
# Guest-Accessible Discovery Tools
# ============================================================================


@user_mcp.tool(
    "discovery_search",
    annotations={
        "title": "Search Properties",
        "readOnlyHint": True,
        "securitySchemes": MCP_SECURITY_SCHEMES_MIXED,
    },
    meta=DISCOVERY_SEARCH_META,
)
async def discovery_search(
    query: Optional[str] = None,
    latitude: Optional[float] = None,
    longitude: Optional[float] = None,
    radius_km: int = 5,
    property_type: Optional[str] = None,
    purpose: Optional[str] = None,
    price_min: Optional[float] = None,
    price_max: Optional[float] = None,
    bedrooms_min: Optional[int] = None,
    bedrooms_max: Optional[int] = None,
    amenities: Optional[List[str]] = None,
    city: Optional[str] = None,
    locality: Optional[str] = None,
    page: int = 1,
    limit: int = 20,
) -> Dict[str, Any]:
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
        page: Page number (default 1)
        limit: Results per page (max 50)

    Returns:
        Property search results with pagination info.
    """
    try:
        from app.services.property import get_unified_properties_optimized

        # Validate and clamp limit
        limit = min(max(1, limit), 50)
        page = max(1, page)

        async with AsyncSessionLocal() as db:
            # Get optional user for personalization
            user = await _get_optional_user(db)
            user_id = user.id if user else None

            # Build filter object
            filter_data = {
                "search_query": query,
                "latitude": latitude,
                "longitude": longitude,
                "property_type": property_type,
                "purpose": purpose,
                "price_min": price_min,
                "price_max": price_max,
                "bedrooms_min": bedrooms_min,
                "bedrooms_max": bedrooms_max,
                "amenities": amenities,
                "city": city,
                "locality": locality,
            }
            # Only include radius_km when location search is active
            if latitude and longitude:
                filter_data["radius_km"] = radius_km

            filters = UnifiedPropertyFilter(**filter_data)

            # Execute search
            result = await get_unified_properties_optimized(
                db,
                filters=filters,
                user_id=user_id,
                page=page,
                limit=limit,
            )

            # Serialize properties
            properties = [serialize_property_basic(p) for p in result.get("items", [])]
            total = result.get("total", 0)
            total_pages = result.get("total_pages", 0)

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

            return format_chatgpt_response(
                data={
                    "properties": properties,
                    "total": total,
                    "page": page,
                    "limit": limit,
                    "total_pages": total_pages,
                    "filters_applied": filters_applied,
                },
                content_summary=format_property_list_summary(properties, total, filters_applied),
                meta={
                    "search_center": {"latitude": latitude, "longitude": longitude} if latitude and longitude else None,
                },
            )

    except Exception as e:
        logger.error(f"Error in discovery_search: {e}", exc_info=True)
        return format_chatgpt_response(
            data={"error": True, "message": str(e)},
            content_summary=f"Sorry, there was an error searching properties: {str(e)}",
        )


@user_mcp.tool(
    "discovery_property_get",
    annotations={
        "title": "Get Property Details",
        "readOnlyHint": True,
        "securitySchemes": MCP_SECURITY_SCHEMES_MIXED,
    },
    meta=PROPERTY_DETAILS_META,
)
async def discovery_property_get(
    property_id: int,
) -> Dict[str, Any]:
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
            property_data = serialize_property_full(property_obj)

            # Check if user has liked this property
            if user:
                from app.services.swipe import get_user_like_for_property
                liked = await get_user_like_for_property(db, user.id, property_id)
                property_data["user_liked"] = liked

            return format_chatgpt_response(
                data={"property": property_data},
                content_summary=format_property_detail_summary(property_data),
            )

    except Exception as e:
        logger.error(f"Error in discovery.property.get: {e}", exc_info=True)
        if "not found" in str(e).lower():
            return format_chatgpt_response(
                data={"error": True, "code": "NOT_FOUND", "property_id": property_id},
                content_summary=f"Property with ID {property_id} was not found.",
            )
        return format_chatgpt_response(
            data={"error": True, "message": str(e)},
            content_summary=f"Sorry, there was an error retrieving the property: {str(e)}",
        )


@user_mcp.tool(
    "discovery_feed",
    annotations={
        "title": "Property Discovery Feed",
        "readOnlyHint": True,
        "securitySchemes": MCP_SECURITY_SCHEMES_MIXED,
    },
    meta=DISCOVERY_FEED_META,
)
async def discovery_feed(
    latitude: Optional[float] = None,
    longitude: Optional[float] = None,
    purpose: Optional[str] = None,
    limit: int = 10,
) -> Dict[str, Any]:
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
        from app.services.property import get_unified_properties_optimized
        from sqlalchemy import select

        limit = min(max(1, limit), 20)

        async with AsyncSessionLocal() as db:
            user = await _get_optional_user(db)
            user_id = user.id if user else None

            # Build filters
            filters = UnifiedPropertyFilter(
                latitude=latitude,
                longitude=longitude,
                radius_km=50 if latitude and longitude else None,  # Wider radius for feed
                purpose=purpose,
            )

            # Get properties
            result = await get_unified_properties_optimized(
                db,
                filters=filters,
                user_id=user_id,
                page=1,
                limit=limit,
            )

            properties = [serialize_property_basic(p) for p in result.get("items", [])]

            return format_chatgpt_response(
                data={
                    "properties": properties,
                    "count": len(properties),
                    "is_personalized": user_id is not None,
                },
                content_summary=f"Here are {len(properties)} properties for you to discover. Swipe right to like or left to pass.",
            )

    except Exception as e:
        logger.error(f"Error in discovery.feed: {e}", exc_info=True)
        return format_chatgpt_response(
            data={"error": True, "message": str(e)},
            content_summary=f"Sorry, there was an error loading the discovery feed: {str(e)}",
        )


@user_mcp.tool(
    "discovery_amenities",
    annotations={
        "title": "List Property Amenities",
        "readOnlyHint": True,
        "securitySchemes": MCP_SECURITY_SCHEMES_MIXED,
    },
)
async def discovery_amenities() -> Dict[str, Any]:
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

            amenity_list = [
                {"id": a.id, "name": a.title, "icon": a.icon}
                for a in amenities
            ]

            return format_chatgpt_response(
                data={"amenities": amenity_list, "count": len(amenity_list)},
                content_summary=f"There are {len(amenity_list)} amenities available for filtering, including {', '.join([a['name'] for a in amenity_list[:5]])} and more.",
            )

    except Exception as e:
        logger.error(f"Error in discovery.amenities: {e}", exc_info=True)
        return format_chatgpt_response(
            data={"error": True, "message": str(e)},
            content_summary=f"Sorry, there was an error loading amenities: {str(e)}",
        )


# ============================================================================
# Authentication Required Discovery Tools
# ============================================================================


@user_mcp.tool(
    "discovery_swipe",
    annotations={
        "title": "Like or Pass Property",
        "readOnlyHint": False,
        "securitySchemes": MCP_SECURITY_SCHEMES_MIXED,
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
) -> Dict[str, Any]:
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
            )

    except AuthRequiredError:
        raise
    except Exception as e:
        logger.error(f"Error in discovery.swipe: {e}", exc_info=True)
        return format_chatgpt_response(
            data={"error": True, "message": str(e)},
            content_summary=f"Sorry, there was an error recording your swipe: {str(e)}",
        )


@user_mcp.tool(
    "discovery_shortlist",
    annotations={
        "title": "View Shortlisted Properties",
        "readOnlyHint": True,
        "securitySchemes": MCP_SECURITY_SCHEMES_MIXED,
    },
    meta=SHORTLIST_META,
)
async def discovery_shortlist(
    page: int = 1,
    limit: int = 20,
) -> Dict[str, Any]:
    """Get the user's shortlisted (liked) properties.

    Retrieves all properties the user has liked/swiped right on.

    This tool requires authentication.

    Args:
        page: Page number for pagination
        limit: Results per page (max 50)

    Returns:
        List of shortlisted properties.
    """
    try:
        from app.services.swipe import get_swipe_history

        limit = min(max(1, limit), 50)
        page = max(1, page)

        async with AsyncSessionLocal() as db:
            user = await _get_optional_user(db)

            if not user:
                return format_auth_required_response(
                    action="shortlist",
                    message="To view your shortlisted properties, please log in to your 360Ghar account.",
                )

            # Get liked properties
            filters = UnifiedPropertyFilter()
            result = await get_swipe_history(
                db,
                user_id=user.id,
                filters=filters,
                page=page,
                limit=limit,
                is_liked=True,  # Only liked properties
            )

            # Serialize properties from swipe items
            properties = []
            for swipe in result.get("items", []):
                if swipe.property:
                    prop_data = serialize_property_basic(swipe.property)
                    prop_data["swiped_at"] = swipe.created_at.isoformat() if swipe.created_at else None
                    properties.append(prop_data)

            total = result.get("total", 0)
            total_pages = result.get("total_pages", 0)

            return format_chatgpt_response(
                data={
                    "properties": properties,
                    "total": total,
                    "page": page,
                    "limit": limit,
                    "total_pages": total_pages,
                },
                content_summary=f"You have {total} properties in your shortlist. Showing {len(properties)} on this page.",
            )

    except AuthRequiredError:
        raise
    except Exception as e:
        logger.error(f"Error in discovery.shortlist: {e}", exc_info=True)
        return format_chatgpt_response(
            data={"error": True, "message": str(e)},
            content_summary=f"Sorry, there was an error loading your shortlist: {str(e)}",
        )


@user_mcp.tool(
    "discovery_recommendations",
    annotations={
        "title": "Get Property Recommendations",
        "readOnlyHint": True,
        "securitySchemes": MCP_SECURITY_SCHEMES_MIXED,
    },
    meta=build_widget_tool_meta(
        widget_uri="ui://widget/propertysearchwidget.html",
        invoking="Finding recommended properties...",
        invoked="Recommendations ready",
    ),
)
async def discovery_recommendations(
    latitude: Optional[float] = None,
    longitude: Optional[float] = None,
    limit: int = 10,
) -> Dict[str, Any]:
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
            recommendations = await get_property_recommendations(
                db,
                user_id=user.id,
                latitude=latitude,
                longitude=longitude,
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
            )

    except AuthRequiredError:
        raise
    except Exception as e:
        logger.error(f"Error in discovery.recommendations: {e}", exc_info=True)
        return format_chatgpt_response(
            data={"error": True, "message": str(e)},
            content_summary=f"Sorry, there was an error generating recommendations: {str(e)}",
        )
