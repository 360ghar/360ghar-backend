"""
Owner tools for User MCP Server.

Tools for property owners to manage their properties:
- List owned properties
- Create property listing
- Get property details
- Update property
- Toggle availability
"""
from __future__ import annotations

from typing import Any

from app.core.exceptions import (
    InsufficientPermissionsError,
    PropertyNotFoundException,
)
from app.core.logging import get_logger
from app.mcp.apps_sdk import (
    MCP_SECURITY_SCHEMES_MIXED,
    AuthRequiredError,
    build_widget_tool_meta,
    raise_auth_required,
)
from app.mcp.errors import (
    MCPErrorCode,
    MCPResponse,
    internal_error_response,
    invalid_input_response,
    not_found_response,
)
from app.mcp.tool_ops import (
    TOOL_OPS_FORBIDDEN,
    TOOL_OPS_NOT_FOUND,
    create_property,
    get_property_detail,
    list_properties_enriched,
    toggle_property_availability,
    update_property_fields,
)

# Import the user MCP server instance to register tools
from app.mcp.user.server import _get_user, _require_auth, user_mcp
from app.mcp.utils import get_db

logger = get_logger(__name__)

# ChatGPT widget linkage metadata
OWNER_DASHBOARD_META = build_widget_tool_meta(
    widget_uri="ui://widget/ownerdashboardwidget.html",
    invoking="Loading your properties...",
    invoked="Properties loaded",
)


# ============================================================================
# Owner Property Tools
# ============================================================================


@user_mcp.tool(
    "owner_properties_list",
    annotations={
        "title": "List My Properties",
        "readOnlyHint": True,
        "openWorldHint": False,
        "destructiveHint": False,
        "securitySchemes": MCP_SECURITY_SCHEMES_MIXED,
    },
    meta=OWNER_DASHBOARD_META,
)
async def owner_properties_list(
    page: int = 1,
    limit: int = 20,
    occupancy: str | None = None,
    q: str | None = None,
) -> dict[str, Any]:
    """List all properties owned by the current user.

    Args:
        page: Page number (default 1)
        limit: Items per page (default 20, max 100)
        occupancy: Filter by 'occupied' or 'vacant'
        q: Search query for title/address
    """
    try:
        async for db in get_db():
            user = await _get_user(db)
            if not user:
                raise_auth_required(
                    message="Please log in to view your property dashboard.",
                    error_description="Authentication required",
                    scope="mcp:read",
                    structured_content={
                        "requires_auth": True,
                        "action": "owner_properties_list",
                    },
                )

            clamped_limit = min(max(1, limit), 100)
            result = await list_properties_enriched(
                db,
                actor=user,
                owner_id=user.id,
                occupancy=occupancy,
                q=q,
                page=page,
                limit=clamped_limit,
            )
            return MCPResponse.success(result).model_dump()
    except AuthRequiredError:
        raise
    except Exception as e:
        logger.error("Error in owner.properties.list: %s", e, exc_info=True)
        return internal_error_response("Failed to list properties.")
    return {}


@user_mcp.tool(
    "owner_properties_create",
    annotations={
        "title": "Create Property Listing",
        "readOnlyHint": False,
        "destructiveHint": False,
        "openWorldHint": False,
        "securitySchemes": MCP_SECURITY_SCHEMES_MIXED,
    },
)
async def owner_properties_create(
    title: str,
    property_type: str,
    purpose: str,
    full_address: str,
    city: str,
    locality: str,
    latitude: float,
    longitude: float,
    base_price: float,
    description: str | None = None,
    sub_locality: str | None = None,
    pincode: str | None = None,
    state: str | None = None,
    monthly_rent: float | None = None,
    daily_rate: float | None = None,
    security_deposit: float | None = None,
    maintenance_charges: float | None = None,
    area_sqft: float | None = None,
    bedrooms: int | None = None,
    bathrooms: int | None = None,
    balconies: int | None = None,
    parking_spaces: int | None = None,
    floor_number: int | None = None,
    total_floors: int | None = None,
    max_occupancy: int | None = None,
    minimum_stay_days: int | None = None,
    main_image_url: str | None = None,
    virtual_tour_url: str | None = None,
    amenity_ids: list[int] | None = None,
) -> dict[str, Any]:
    """Create a new property listing for the current user.

    Args:
        title: Property title (5-200 chars)
        property_type: house, apartment, builder_floor, room
        purpose: buy, rent, short_stay
        full_address: Complete address
        city: City name
        locality: Locality/area name
        latitude: GPS latitude (-90 to 90)
        longitude: GPS longitude (-180 to 180)
        base_price: Base price for sale or display
        ... (other optional fields)
    """
    try:
        async for db in get_db():
            user = await _get_user(db)
            if not user:
                _require_auth(
                    action="owner_properties_create",
                    message="Please log in to create a property listing.",
                    scope="mcp:write",
                )

            result = await create_property(
                db,
                actor=user,
                owner_id=user.id,
                property_type=property_type,
                purpose=purpose,
                title=title,
                full_address=full_address,
                city=city,
                locality=locality,
                latitude=latitude,
                longitude=longitude,
                base_price=base_price,
                description=description,
                sub_locality=sub_locality,
                pincode=pincode,
                state=state,
                monthly_rent=monthly_rent,
                daily_rate=daily_rate,
                security_deposit=security_deposit,
                maintenance_charges=maintenance_charges,
                area_sqft=area_sqft,
                bedrooms=bedrooms,
                bathrooms=bathrooms,
                balconies=balconies,
                parking_spaces=parking_spaces,
                floor_number=floor_number,
                total_floors=total_floors,
                max_occupancy=max_occupancy,
                minimum_stay_days=minimum_stay_days,
                main_image_url=main_image_url,
                virtual_tour_url=virtual_tour_url,
                amenity_ids=amenity_ids,
            )

            if result.get("error"):
                return invalid_input_response(result.get("message", "Invalid input"))

            return MCPResponse.success(result).model_dump()
    except ValueError as e:
        return invalid_input_response(str(e))
    except AuthRequiredError:
        raise
    except Exception as e:
        logger.error("Error in owner.properties.create: %s", e, exc_info=True)
        return internal_error_response(f"Failed to create property: {str(e)}")
    return {}


@user_mcp.tool(
    "owner_properties_get",
    annotations={
        "title": "Get Property Details (Owner)",
        "readOnlyHint": True,
        "openWorldHint": False,
        "destructiveHint": False,
        "securitySchemes": MCP_SECURITY_SCHEMES_MIXED,
    },
)
async def owner_properties_get(
    property_id: int,
) -> dict[str, Any]:
    """Get detailed information about one of your properties.

    Args:
        property_id: ID of the property to retrieve
    """
    try:
        async for db in get_db():
            user = await _get_user(db)
            if not user:
                _require_auth(
                    action="owner_properties_get",
                    message="Please log in to view this property.",
                    scope="mcp:read",
                )

            result = await get_property_detail(
                db,
                actor=user,
                property_id=property_id,
            )

            if result.get("error"):
                code = result.get("code", "")
                if code == TOOL_OPS_NOT_FOUND:
                    return not_found_response("Property", property_id)
                if code == TOOL_OPS_FORBIDDEN:
                    return MCPResponse.failure(
                        MCPErrorCode.INSUFFICIENT_PERMISSIONS,
                        result.get("message", "Access denied"),
                    ).model_dump()
                return internal_error_response(result.get("message", "Failed to get property"))

            return MCPResponse.success(result).model_dump()
    except AuthRequiredError:
        raise
    except Exception as e:
        logger.error("Error in owner.properties.get: %s", e, exc_info=True)
        return internal_error_response(f"Failed to get property: {str(e)}")
    return {}


@user_mcp.tool(
    "owner_properties_update",
    annotations={
        "title": "Update Property Listing",
        "readOnlyHint": False,
        "destructiveHint": False,
        "openWorldHint": False,
        "securitySchemes": MCP_SECURITY_SCHEMES_MIXED,
    },
)
async def owner_properties_update(
    property_id: int,
    title: str | None = None,
    description: str | None = None,
    base_price: float | None = None,
    monthly_rent: float | None = None,
    daily_rate: float | None = None,
    is_available: bool | None = None,
    max_occupancy: int | None = None,
    main_image_url: str | None = None,
) -> dict[str, Any]:
    """Update one of your properties.

    Args:
        property_id: ID of the property to update
        ... (all other fields are optional for partial update)
    """
    try:
        async for db in get_db():
            user = await _get_user(db)
            if not user:
                _require_auth(
                    action="owner_properties_update",
                    message="Please log in to update a property listing.",
                    scope="mcp:write",
                )

            updates = {
                k: v for k, v in {
                    "title": title,
                    "description": description,
                    "base_price": base_price,
                    "monthly_rent": monthly_rent,
                    "daily_rate": daily_rate,
                    "is_available": is_available,
                    "max_occupancy": max_occupancy,
                    "main_image_url": main_image_url,
                }.items() if v is not None
            }

            try:
                result = await update_property_fields(
                    db,
                    actor=user,
                    property_id=property_id,
                    updates=updates,
                )
            except PropertyNotFoundException:
                return not_found_response("Property", property_id)
            except InsufficientPermissionsError:
                return MCPResponse.failure(
                    MCPErrorCode.INSUFFICIENT_PERMISSIONS,
                    "You do not have access to this property"
                ).model_dump()

            return MCPResponse.success(result).model_dump()
    except AuthRequiredError:
        raise
    except Exception as e:
        logger.error("Error in owner.properties.update: %s", e, exc_info=True)
        return internal_error_response(f"Failed to update property: {str(e)}")
    return {}


@user_mcp.tool(
    "owner_properties_toggle_availability",
    annotations={
        "title": "Toggle Property Availability",
        "readOnlyHint": False,
        "destructiveHint": False,
        "openWorldHint": False,
        "securitySchemes": MCP_SECURITY_SCHEMES_MIXED,
    },
)
async def owner_properties_toggle_availability(
    property_id: int,
    is_available: bool,
) -> dict[str, Any]:
    """Toggle a property's availability status.

    Args:
        property_id: ID of the property
        is_available: True to mark as available, False otherwise
    """
    try:
        async for db in get_db():
            user = await _get_user(db)
            if not user:
                _require_auth(
                    action="owner_properties_toggle_availability",
                    message="Please log in to update property availability.",
                    scope="mcp:write",
                )

            try:
                result = await toggle_property_availability(
                    db,
                    actor=user,
                    property_id=property_id,
                    is_available=is_available,
                )
            except PropertyNotFoundException:
                return not_found_response("Property", property_id)
            except InsufficientPermissionsError:
                return MCPResponse.failure(
                    MCPErrorCode.INSUFFICIENT_PERMISSIONS,
                    "You do not have access to this property"
                ).model_dump()

            return MCPResponse.success(result).model_dump()
    except AuthRequiredError:
        raise
    except Exception as e:
        logger.error("Error in owner.properties.toggle_availability: %s", e, exc_info=True)
        return internal_error_response(f"Failed to toggle availability: {str(e)}")
    return {}
