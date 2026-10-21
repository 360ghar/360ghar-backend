from __future__ import annotations

from typing import Any, Literal

from app.core.exceptions import (
    BadRequestException,
    InsufficientPermissionsError,
    PropertyNotFoundException,
)
from app.mcp.admin.agent_tools.common import (
    MCP_SECURITY_SCHEMES_OAUTH2_ONLY,
    AuthRequiredError,
    MCPErrorCode,
    MCPResponse,
    _get_user,
    _require_agent_or_admin,
    _require_auth,
    admin_mcp,
    get_db,
    internal_error_response,
    invalid_input_response,
    logger,
    not_found_response,
    serialize_lease,
    serialize_property_basic,
    serialize_property_full,
    utc_now_iso,
)
from app.mcp.apps_sdk import build_widget_tool_meta
from app.mcp.tool_ops import compute_portfolio_stats, enrich_properties_with_lease_info
from app.mcp.tool_ops.scope import owner_scope
from app.models.enums import PropertyPurpose, PropertyType
from app.schemas.pagination import decode_cursor, encode_cursor
from app.services.property import attach_owner_agents
from app.services.visibility import mask_user_ref
from app.utils.validators import ValidationUtils

AGENT_PROPERTIES_LIST_META = build_widget_tool_meta(
    widget_uri="ui://widget/ownerdashboardwidget.html",
    invoking="Loading managed properties...",
    invoked="Managed properties loaded",
)

AGENT_PROPERTY_DETAILS_META = build_widget_tool_meta(
    widget_uri="ui://widget/propertydetailswidget.html",
    invoking="Loading property details...",
    invoked="Property details loaded",
)


@admin_mcp.tool(
    "agent_properties_list",
    annotations={
        "title": "List Managed Properties",
        "readOnlyHint": True,
        "openWorldHint": False,
        "destructiveHint": False,
        "securitySchemes": MCP_SECURITY_SCHEMES_OAUTH2_ONLY,
    },
    meta=AGENT_PROPERTIES_LIST_META,
)
async def agent_properties_list(
    owner_id: int | None = None,
    cursor: str | None = None,
    limit: int = 50,
    occupancy: Literal["occupied", "vacant"] | None = None,
    q: str | None = None,
    include_total: bool = False,
) -> dict[str, Any]:
    """List managed properties for agents/admins.

    Agents see properties of their assigned owners.
    Admins see all properties.

    Args:
        owner_id: Filter by specific owner (required for agents)
        cursor: Opaque pagination cursor from a prior response's next_cursor
        limit: Items per page (max 100)
        occupancy: Filter by 'occupied' or 'vacant'
        q: Search query
    """
    try:
        limit = min(max(1, limit), 100)
        filters = {"owner_id": owner_id, "occupancy": occupancy, "q": q}
        cursor_payload = decode_cursor(cursor, filters) if cursor else {}

        async for db in get_db():
            user = await _get_user(db)
            if not user:
                _require_auth(
                    action="agent_properties_list",
                    message="Please log in to list managed properties.",
                    scope="mcp:read",
                )

            if not _require_agent_or_admin(user):
                return MCPResponse.failure(
                    MCPErrorCode.INSUFFICIENT_PERMISSIONS,
                    "This endpoint is for agents and admins only",
                ).model_dump()

            from app.schemas.user import User as UserSchema
            from app.services.pm_properties import list_managed_properties

            user_schema = UserSchema.model_validate(user)

            try:
                rows, next_payload, total = await list_managed_properties(
                    db,
                    actor=user_schema,
                    owner_id=owner_id,
                    occupancy=occupancy,
                    q=q,
                    cursor_payload=cursor_payload,
                    limit=limit,
                    with_total=include_total,
                )
            except InsufficientPermissionsError as e:
                return MCPResponse.failure(
                    MCPErrorCode.INSUFFICIENT_PERMISSIONS, str(e)
                ).model_dump()

            # has_active_lease and tenant_name, the same enrichment as owner_properties_list.
            items, _page_stats = await enrich_properties_with_lease_info(db, rows)
            stats = await compute_portfolio_stats(
                db, owner_ids=await owner_scope(db, user, owner_id)
            )

            return MCPResponse.success(
                {
                    "total": total,
                    "next_cursor": encode_cursor(next_payload, filters) if next_payload else None,
                    "has_more": next_payload is not None,
                    "limit": limit,
                    "items": items,
                    "stats": stats,
                }
            ).model_dump()
    except AuthRequiredError:
        raise
    except BadRequestException as e:
        return invalid_input_response(str(e))
    except Exception as e:
        logger.error("Error in agent.properties.list: %s", e, exc_info=True)
        return internal_error_response(f"Failed to list properties: {str(e)}")
    return {}


@admin_mcp.tool(
    "agent_properties_get",
    annotations={
        "title": "Get Managed Property Details",
        "readOnlyHint": True,
        "openWorldHint": False,
        "destructiveHint": False,
        "securitySchemes": MCP_SECURITY_SCHEMES_OAUTH2_ONLY,
    },
    meta=AGENT_PROPERTY_DETAILS_META,
)
async def agent_properties_get(
    property_id: int,
) -> dict[str, Any]:
    """Get detailed property information including lease and tenant data.

    Args:
        property_id: ID of the property
    """
    try:
        async for db in get_db():
            user = await _get_user(db)
            if not user:
                _require_auth(
                    action="agent_properties_get",
                    message="Please log in to view managed property details.",
                    scope="mcp:read",
                )

            if not _require_agent_or_admin(user):
                return MCPResponse.failure(
                    MCPErrorCode.INSUFFICIENT_PERMISSIONS,
                    "This endpoint is for agents and admins only",
                ).model_dump()

            from app.schemas.user import User as UserSchema
            from app.services.pm_properties import get_managed_property_detail

            user_schema = UserSchema.model_validate(user)

            try:
                result = await get_managed_property_detail(
                    db,
                    actor=user_schema,
                    property_id=property_id,
                )
            except PropertyNotFoundException:
                return not_found_response("Property", property_id)
            except InsufficientPermissionsError:
                return MCPResponse.failure(
                    MCPErrorCode.INSUFFICIENT_PERMISSIONS, "You do not have access to this property"
                ).model_dump()

            prop = result["property"]
            active_lease = result.get("active_lease")

            await attach_owner_agents(db, [prop])
            property_data = serialize_property_full(prop, viewer=user)

            # Get owner info
            owner_data = None
            if prop.owner_id:
                from app.services.user import get_user_by_id

                owner = await get_user_by_id(db, prop.owner_id)
                if owner:
                    owner_data = mask_user_ref(owner, user, owner_id=prop.owner_id)

            lease_data = None
            tenant_data = None
            if active_lease:
                lease_data = serialize_lease(active_lease, user)
                if active_lease.tenant_user_id:
                    tenant = await get_user_by_id(db, active_lease.tenant_user_id)
                    if tenant:
                        tenant_data = mask_user_ref(tenant, user, owner_id=prop.owner_id)

            return MCPResponse.success(
                {
                    "property": property_data,
                    "owner": owner_data,
                    "active_lease": lease_data,
                    "tenant": tenant_data,
                }
            ).model_dump()
    except AuthRequiredError:
        raise
    except BadRequestException as e:
        return invalid_input_response(str(e))
    except Exception as e:
        logger.error("Error in agent.properties.get: %s", e, exc_info=True)
        return internal_error_response(f"Failed to get property: {str(e)}")
    return {}


@admin_mcp.tool(
    "agent_properties_create_for_owner",
    annotations={
        "title": "Create Property For Owner",
        "readOnlyHint": False,
        "destructiveHint": False,
        "openWorldHint": False,
        "securitySchemes": MCP_SECURITY_SCHEMES_OAUTH2_ONLY,
    },
)
async def agent_properties_create_for_owner(
    owner_id: int,
    title: str,
    property_type: PropertyType,
    purpose: PropertyPurpose,
    full_address: str,
    city: str,
    locality: str,
    latitude: float,
    longitude: float,
    base_price: float,
    description: str | None = None,
    monthly_rent: float | None = None,
    daily_rate: float | None = None,
    bedrooms: int | None = None,
    bathrooms: int | None = None,
    area_sqft: float | None = None,
    main_image_url: str | None = None,
    payment_due_day: int = 1,
    grace_period_days: int = 5,
) -> dict[str, Any]:
    """Create a property for an owner (agent/admin only).

    Args:
        owner_id: ID of the property owner
        title: Property title
        property_type: house, apartment, builder_floor, room
        purpose: buy, rent, short_stay
        ... (other property fields)
    """
    try:
        from app.models.enums import PropertyPurpose, PropertyType

        try:
            prop_type = PropertyType(property_type.lower())
        except ValueError:
            return invalid_input_response(f"Invalid property_type: {property_type}")

        try:
            prop_purpose = PropertyPurpose(purpose.lower())
        except ValueError:
            return invalid_input_response(f"Invalid purpose: {purpose}")

        async for db in get_db():
            user = await _get_user(db)
            if not user:
                _require_auth(
                    action="agent_properties_create_for_owner",
                    message="Please log in to create a property for an owner.",
                    scope="mcp:write",
                )

            if not _require_agent_or_admin(user):
                return MCPResponse.failure(
                    MCPErrorCode.INSUFFICIENT_PERMISSIONS,
                    "This endpoint is for agents and admins only",
                ).model_dump()

            from app.schemas.property import PropertyCreate
            from app.schemas.user import User as UserSchema
            from app.services.pm_properties import create_managed_property

            user_schema = UserSchema.model_validate(user)

            if main_image_url is not None and not ValidationUtils.is_absolute_url(main_image_url):
                logger.warning(
                    "Non-absolute main_image_url in agent_properties_create_for_owner: %s",
                    main_image_url,
                )

            property_data = PropertyCreate(
                title=title,
                description=description,
                property_type=prop_type,
                purpose=prop_purpose,
                full_address=full_address,
                city=city,
                locality=locality,
                latitude=latitude,
                longitude=longitude,
                base_price=base_price,
                monthly_rent=monthly_rent,
                daily_rate=daily_rate,
                bedrooms=bedrooms,
                bathrooms=bathrooms,
                area_sqft=area_sqft,
                main_image_url=main_image_url,
            )

            try:
                prop = await create_managed_property(
                    db,
                    actor=user_schema,
                    owner_id=owner_id,
                    property_data=property_data,
                    payment_due_day=payment_due_day,
                    grace_period_days=grace_period_days,
                )
                await db.commit()
            except InsufficientPermissionsError as e:
                return MCPResponse.failure(
                    MCPErrorCode.INSUFFICIENT_PERMISSIONS, str(e)
                ).model_dump()

            return MCPResponse.success(
                {
                    "message": "Property created successfully",
                    "property": serialize_property_basic(prop),
                }
            ).model_dump()
    except AuthRequiredError:
        raise
    except BadRequestException as e:
        return invalid_input_response(str(e))
    except Exception as e:
        logger.error("Error in agent.properties.create_for_owner: %s", e, exc_info=True)
        return internal_error_response(f"Failed to create property: {str(e)}")
    return {}


@admin_mcp.tool(
    "agent_properties_verify",
    annotations={
        "title": "Verify Property Listing",
        "readOnlyHint": False,
        "destructiveHint": False,
        "openWorldHint": False,
        "securitySchemes": MCP_SECURITY_SCHEMES_OAUTH2_ONLY,
    },
)
async def agent_properties_verify(
    property_id: int,
    is_verified: bool,
    verification_notes: str | None = None,
) -> dict[str, Any]:
    """Mark a property as verified or unverified.

    Args:
        property_id: ID of the property
        is_verified: Verification status
        verification_notes: Notes about verification
    """
    try:
        async for db in get_db():
            user = await _get_user(db)
            if not user:
                _require_auth(
                    action="agent_properties_verify",
                    message="Please log in to verify a property listing.",
                    scope="mcp:write",
                )

            if not _require_agent_or_admin(user):
                return MCPResponse.failure(
                    MCPErrorCode.INSUFFICIENT_PERMISSIONS,
                    "This endpoint is for agents and admins only",
                ).model_dump()

            from app.schemas.user import User as UserSchema
            from app.services.pm_authz import assert_can_access_property

            user_schema = UserSchema.model_validate(user)

            try:
                prop = await assert_can_access_property(
                    db, actor=user_schema, property_id=property_id
                )
            except PropertyNotFoundException:
                return not_found_response("Property", property_id)
            except InsufficientPermissionsError:
                return MCPResponse.failure(
                    MCPErrorCode.INSUFFICIENT_PERMISSIONS, "You do not have access to this property"
                ).model_dump()

            preferences = dict(prop.listing_preferences or {})
            verification: dict[str, Any] = {
                "is_verified": is_verified,
                "verified_by": user.id,
                "verified_at": utc_now_iso(),
            }
            if verification_notes:
                verification["notes"] = verification_notes
            preferences["verification"] = verification
            prop.listing_preferences = preferences

            await db.flush()
            await db.commit()

            status = "verified" if is_verified else "unverified"
            return MCPResponse.success(
                {
                    "message": f"Property marked as {status}",
                    "property_id": property_id,
                    "is_verified": is_verified,
                }
            ).model_dump()
    except AuthRequiredError:
        raise
    except BadRequestException as e:
        return invalid_input_response(str(e))
    except Exception as e:
        logger.error("Error in agent.properties.verify: %s", e, exc_info=True)
        return internal_error_response(f"Failed to verify property: {str(e)}")
    return {}
