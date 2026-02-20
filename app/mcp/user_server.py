"""
User MCP Server - For end users (owners, tenants, regular users).

This server provides MCP tools for:
- Property owners: Manage their own properties
- Tenants: View lease, submit maintenance requests
- Users: Search, book, and manage visits

Mounted at: /mcp
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from app.mcp.apps_sdk import (
    AppsSDKFastMCP,
    AuthRequiredError,
    MCP_SECURITY_SCHEMES_MIXED,
    build_widget_tool_meta,
    raise_auth_required,
)

from app.core.database import AsyncSessionLocal
from app.core.exceptions import (
    InsufficientPermissionsError,
    PropertyNotFoundException,
)
from app.core.logging import get_logger
from app.models.enums import PropertyType, PropertyPurpose
from app.mcp.errors import (
    MCPErrorCode,
    MCPResponse,
    internal_error_response,
    invalid_input_response,
    not_found_response,
    unauthorized_response,
)
from app.mcp.utils import (
    get_db,
    get_user_from_mcp_context,
    serialize_property_basic,
    serialize_property_full,
    serialize_booking,
    serialize_lease,
    serialize_maintenance_request,
)
from app.schemas.property import PropertyCreate
from app.schemas.booking import BookingCreate
from app.services.pm_properties import (
    create_managed_property,
    list_managed_properties,
    get_managed_property_detail,
    update_managed_property,
)
from app.services.pm_authz import assert_can_access_property
from app.services import booking as booking_svc

logger = get_logger(__name__)

# Create the User MCP server instance
user_mcp = AppsSDKFastMCP("ghar360-user")

# ChatGPT widget linkage metadata (used by Apps SDK)
OWNER_DASHBOARD_META = build_widget_tool_meta(
    widget_uri="ui://widget/ownerdashboardwidget.html",
    invoking="Loading your properties...",
    invoked="Properties loaded",
)

LEASE_DETAILS_META = build_widget_tool_meta(
    widget_uri="ui://widget/leasedetailswidget.html",
    invoking="Loading lease details...",
    invoked="Lease details loaded",
)

MAINTENANCE_WIDGET_META = build_widget_tool_meta(
    widget_uri="ui://widget/maintenancewidget.html",
    invoking="Loading maintenance requests...",
    invoked="Maintenance requests loaded",
)

TENANT_RENT_WIDGET_META = build_widget_tool_meta(
    widget_uri="ui://widget/tenantrentwidget.html",
    invoking="Loading your rent information...",
    invoked="Rent information loaded",
)


async def _get_user(db):
    """Get user from MCP OAuth context."""
    return await get_user_from_mcp_context(db)


def _require_auth(*, action: str, message: str, scope: str = "mcp:read mcp:write") -> None:
    raise_auth_required(
        message=message,
        error_description=message,
        scope=scope,
        structured_content={
            "requires_auth": True,
            "action": action,
        },
    )


# ============================================================================
# Owner Property Tools
# ============================================================================


@user_mcp.tool(
    "owner_properties_list",
    annotations={
        "title": "List My Properties",
        "readOnlyHint": True,
        "securitySchemes": MCP_SECURITY_SCHEMES_MIXED,
    },
    meta=OWNER_DASHBOARD_META,
)
async def owner_properties_list(
    page: int = 1,
    limit: int = 20,
    occupancy: Optional[str] = None,
    q: Optional[str] = None,
) -> Dict[str, Any]:
    """List all properties owned by the current user.

    Args:
        page: Page number (default 1)
        limit: Items per page (default 20, max 100)
        occupancy: Filter by 'occupied' or 'vacant'
        q: Search query for title/address
    """
    try:
        limit = min(max(1, limit), 100)
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

            # Import here to get the User schema
            from app.schemas.user import User as UserSchema
            from sqlalchemy import select

            from app.models.enums import LeaseStatus
            from app.models.pm_leases import Lease
            from app.models.users import User as UserModel
            user_schema = UserSchema.model_validate(user)

            properties = await list_managed_properties(
                db,
                actor=user_schema,
                owner_id=user.id,
                occupancy=occupancy,
                q=q,
                limit=limit,
                offset=(page - 1) * limit,
            )

            property_ids = [p.id for p in properties]
            active_lease_tenants: dict[int, str | None] = {}
            if property_ids:
                lease_stmt = (
                    select(Lease.property_id, UserModel.full_name)
                    .join(UserModel, UserModel.id == Lease.tenant_user_id)
                    .where(Lease.property_id.in_(property_ids), Lease.status == LeaseStatus.active)
                )
                lease_result = await db.execute(lease_stmt)
                for prop_id, tenant_name in lease_result.all():
                    if prop_id not in active_lease_tenants:
                        active_lease_tenants[prop_id] = tenant_name

            items: list[dict[str, Any]] = []
            for prop in properties:
                item = serialize_property_basic(prop)
                tenant_name = active_lease_tenants.get(prop.id)
                item["has_active_lease"] = prop.id in active_lease_tenants
                if tenant_name:
                    item["tenant_name"] = tenant_name
                items.append(item)

            occupied = sum(1 for p in items if p.get("has_active_lease"))
            vacant = len(items) - occupied
            total_monthly_income = sum(
                float(p.get("monthly_rent") or 0) for p in items if p.get("has_active_lease")
            )

            return {
                "items": items,
                "total": len(items),
                "page": page,
                "limit": limit,
                "stats": {
                    "total_properties": len(items),
                    "occupied": occupied,
                    "vacant": vacant,
                    "total_monthly_income": total_monthly_income,
                },
            }
    except AuthRequiredError:
        raise
    except Exception as e:
        logger.error(f"Error in owner.properties.list: {e}", exc_info=True)
        return {
            "error": True,
            "message": "Failed to list properties.",
        }


@user_mcp.tool(
    "owner_properties_create",
    annotations={
        "title": "Create Property Listing",
        "readOnlyHint": False,
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
    description: Optional[str] = None,
    sub_locality: Optional[str] = None,
    pincode: Optional[str] = None,
    state: Optional[str] = None,
    monthly_rent: Optional[float] = None,
    daily_rate: Optional[float] = None,
    security_deposit: Optional[float] = None,
    maintenance_charges: Optional[float] = None,
    area_sqft: Optional[float] = None,
    bedrooms: Optional[int] = None,
    bathrooms: Optional[int] = None,
    balconies: Optional[int] = None,
    parking_spaces: Optional[int] = None,
    floor_number: Optional[int] = None,
    total_floors: Optional[int] = None,
    max_occupancy: Optional[int] = None,
    minimum_stay_days: Optional[int] = None,
    main_image_url: Optional[str] = None,
    virtual_tour_url: Optional[str] = None,
    amenity_ids: Optional[List[int]] = None,
) -> Dict[str, Any]:
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
        # Validate property_type
        try:
            prop_type = PropertyType(property_type.lower())
        except ValueError:
            return invalid_input_response(f"Invalid property_type: {property_type}")

        # Validate purpose
        try:
            prop_purpose = PropertyPurpose(purpose.lower())
        except ValueError:
            return invalid_input_response(f"Invalid purpose: {purpose}")

        async for db in get_db():
            user = await _get_user(db)
            if not user:
                _require_auth(
                    action="owner_properties_create",
                    message="Please log in to create a property listing.",
                    scope="mcp:write",
                )

            from app.schemas.user import User as UserSchema
            user_schema = UserSchema.model_validate(user)

            # Build property data
            property_data = PropertyCreate(
                title=title,
                description=description,
                property_type=prop_type,
                purpose=prop_purpose,
                full_address=full_address,
                city=city,
                locality=locality,
                sub_locality=sub_locality,
                pincode=pincode,
                state=state,
                latitude=latitude,
                longitude=longitude,
                base_price=base_price,
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
            )

            prop = await create_managed_property(
                db,
                actor=user_schema,
                owner_id=user.id,
                property_data=property_data,
            )

            # Handle amenities if provided
            if amenity_ids:
                from app.models.properties import PropertyAmenity
                for amenity_id in amenity_ids:
                    property_amenity = PropertyAmenity(
                        property_id=prop.id,
                        amenity_id=amenity_id
                    )
                    db.add(property_amenity)

            await db.commit()

            return MCPResponse.success({
                "message": "Property created successfully",
                "property": serialize_property_basic(prop),
            }).dict()
    except ValueError as e:
        return invalid_input_response(str(e))
    except AuthRequiredError:
        raise
    except Exception as e:
        logger.error(f"Error in owner.properties.create: {e}", exc_info=True)
        return internal_error_response(f"Failed to create property: {str(e)}")


@user_mcp.tool(
    "owner_properties_get",
    annotations={
        "title": "Get Property Details (Owner)",
        "readOnlyHint": True,
        "securitySchemes": MCP_SECURITY_SCHEMES_MIXED,
    },
)
async def owner_properties_get(
    property_id: int,
) -> Dict[str, Any]:
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

            from app.schemas.user import User as UserSchema
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
                    MCPErrorCode.INSUFFICIENT_PERMISSIONS,
                    "You do not have access to this property"
                ).dict()

            prop = result["property"]
            active_lease = result.get("active_lease")

            property_data = serialize_property_full(prop)

            lease_data = None
            if active_lease:
                lease_data = serialize_lease(active_lease)

            return MCPResponse.success({
                "property": property_data,
                "active_lease": lease_data,
            }).dict()
    except AuthRequiredError:
        raise
    except Exception as e:
        logger.error(f"Error in owner.properties.get: {e}", exc_info=True)
        return internal_error_response(f"Failed to get property: {str(e)}")


@user_mcp.tool(
    "owner_properties_update",
    annotations={
        "title": "Update Property Listing",
        "readOnlyHint": False,
        "securitySchemes": MCP_SECURITY_SCHEMES_MIXED,
    },
)
async def owner_properties_update(
    property_id: int,
    title: Optional[str] = None,
    description: Optional[str] = None,
    base_price: Optional[float] = None,
    monthly_rent: Optional[float] = None,
    daily_rate: Optional[float] = None,
    is_available: Optional[bool] = None,
    max_occupancy: Optional[int] = None,
    main_image_url: Optional[str] = None,
) -> Dict[str, Any]:
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

            from app.schemas.user import User as UserSchema
            user_schema = UserSchema.model_validate(user)

            try:
                prop = await assert_can_access_property(
                    db, actor=user_schema, property_id=property_id
                )
            except PropertyNotFoundException:
                return not_found_response("Property", property_id)
            except InsufficientPermissionsError:
                return MCPResponse.failure(
                    MCPErrorCode.INSUFFICIENT_PERMISSIONS,
                    "You do not have access to this property"
                ).dict()

            # Apply updates
            if title is not None:
                prop.title = title
            if description is not None:
                prop.description = description
            if base_price is not None:
                prop.base_price = base_price
            if monthly_rent is not None:
                prop.monthly_rent = monthly_rent
            if daily_rate is not None:
                prop.daily_rate = daily_rate
            if is_available is not None:
                prop.is_available = is_available
            if max_occupancy is not None:
                prop.max_occupancy = max_occupancy
            if main_image_url is not None:
                prop.main_image_url = main_image_url

            await db.flush()
            await db.refresh(prop)
            await db.commit()

            return MCPResponse.success({
                "message": "Property updated successfully",
                "property": serialize_property_basic(prop),
            }).dict()
    except AuthRequiredError:
        raise
    except Exception as e:
        logger.error(f"Error in owner.properties.update: {e}", exc_info=True)
        return internal_error_response(f"Failed to update property: {str(e)}")


@user_mcp.tool(
    "owner_properties_toggle_availability",
    annotations={
        "title": "Toggle Property Availability",
        "readOnlyHint": False,
        "securitySchemes": MCP_SECURITY_SCHEMES_MIXED,
    },
)
async def owner_properties_toggle_availability(
    property_id: int,
    is_available: bool,
) -> Dict[str, Any]:
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

            from app.schemas.user import User as UserSchema
            user_schema = UserSchema.model_validate(user)

            try:
                prop = await assert_can_access_property(
                    db, actor=user_schema, property_id=property_id
                )
            except PropertyNotFoundException:
                return not_found_response("Property", property_id)
            except InsufficientPermissionsError:
                return MCPResponse.failure(
                    MCPErrorCode.INSUFFICIENT_PERMISSIONS,
                    "You do not have access to this property"
                ).dict()

            prop.is_available = is_available
            await db.flush()
            await db.commit()

            status = "available" if is_available else "unavailable"
            return MCPResponse.success({
                "message": f"Property marked as {status}",
                "property_id": property_id,
                "is_available": is_available,
            }).dict()
    except AuthRequiredError:
        raise
    except Exception as e:
        logger.error(f"Error in owner.properties.toggle_availability: {e}", exc_info=True)
        return internal_error_response(f"Failed to toggle availability: {str(e)}")


# ============================================================================
# Tenant Tools
# ============================================================================


@user_mcp.tool(
    "tenant_lease_current",
    annotations={
        "title": "View My Current Lease",
        "readOnlyHint": True,
        "securitySchemes": MCP_SECURITY_SCHEMES_MIXED,
    },
    meta=LEASE_DETAILS_META,
)
async def tenant_lease_current() -> Dict[str, Any]:
    """Get the current active lease for the tenant."""
    try:
        from sqlalchemy import select
        from app.models.pm_leases import Lease
        from app.models.enums import LeaseStatus

        async for db in get_db():
            user = await _get_user(db)
            if not user:
                _require_auth(
                    action="tenant_lease_current",
                    message="Please log in to view your lease details.",
                    scope="mcp:read",
                )

            # Find active lease for this tenant
            stmt = select(Lease).where(
                Lease.tenant_user_id == user.id,
                Lease.status == LeaseStatus.active,
            ).order_by(Lease.created_at.desc()).limit(1)

            result = await db.execute(stmt)
            lease = result.scalar_one_or_none()

            if not lease:
                return {
                    "lease": None,
                    "message": "No active lease found.",
                }

            # Get property details
            from app.models.properties import Property
            prop_stmt = select(Property).where(Property.id == lease.property_id)
            prop_result = await db.execute(prop_stmt)
            prop = prop_result.scalar_one_or_none()

            property_data = None
            if prop:
                property_data = {
                    "id": prop.id,
                    "title": prop.title,
                    "locality": prop.locality,
                    "city": prop.city,
                    "full_address": getattr(prop, "full_address", None),
                    "main_image_url": getattr(prop, "main_image_url", None),
                }

            lease_data = serialize_lease(lease)
            lease_data["property"] = property_data

            return {
                "lease": lease_data,
            }
    except AuthRequiredError:
        raise
    except Exception as e:
        logger.error(f"Error in tenant.lease.current: {e}", exc_info=True)
        return {
            "error": True,
            "message": "Failed to get current lease.",
        }


@user_mcp.tool(
    "tenant_rent_history",
    annotations={
        "title": "View My Rent Payment History",
        "readOnlyHint": True,
        "securitySchemes": MCP_SECURITY_SCHEMES_MIXED,
    },
    meta=TENANT_RENT_WIDGET_META,
)
async def tenant_rent_history(
    page: int = 1,
    limit: int = 20,
) -> Dict[str, Any]:
    """Get rent payment history for the tenant."""
    try:
        from sqlalchemy import select
        from app.models.pm_finance import RentPayment
        from app.models.pm_leases import Lease

        limit = min(max(1, limit), 100)

        async for db in get_db():
            user = await _get_user(db)
            if not user:
                _require_auth(
                    action="tenant_rent_history",
                    message="Please log in to view your rent payment history.",
                    scope="mcp:read",
                )

            # Get all leases for this tenant
            lease_stmt = select(Lease.id).where(Lease.tenant_user_id == user.id)
            lease_result = await db.execute(lease_stmt)
            lease_ids = [r[0] for r in lease_result.all()]

            if not lease_ids:
                return {
                    "payments": [],
                    "total": 0,
                    "total_collected": 0,
                    "page": page,
                    "limit": limit,
                }

            # Get rent payments for these leases
            offset = (page - 1) * limit
            stmt = (
                select(RentPayment)
                .where(RentPayment.lease_id.in_(lease_ids))
                .order_by(RentPayment.paid_at.desc())
                .offset(offset)
                .limit(limit)
            )
            result = await db.execute(stmt)
            payments = result.scalars().all()

            items = []
            for p in payments:
                items.append({
                    "id": p.id,
                    "rent_charge_id": p.charge_id,
                    "amount": float(p.amount_paid or 0),
                    "payment_date": p.paid_at.isoformat() if p.paid_at else None,
                    "payment_method": p.payment_method,
                    "transaction_id": p.reference,
                    "created_at": p.created_at.isoformat() if getattr(p, "created_at", None) else None,
                })

            total_collected = sum(p["amount"] for p in items)

            return {
                "payments": items,
                "total": len(items),
                "total_collected": total_collected,
                "page": page,
                "limit": limit,
            }
    except AuthRequiredError:
        raise
    except Exception as e:
        logger.error(f"Error in tenant.rent.history: {e}", exc_info=True)
        return {
            "error": True,
            "message": "Failed to get rent history.",
        }


@user_mcp.tool(
    "tenant_maintenance_create",
    annotations={
        "title": "Create Maintenance Request",
        "readOnlyHint": False,
        "securitySchemes": MCP_SECURITY_SCHEMES_MIXED,
    },
    meta=MAINTENANCE_WIDGET_META,
)
async def tenant_maintenance_create(
    property_id: int,
    title: str,
    description: str,
    category: str,
    priority: str = "medium",
) -> Dict[str, Any]:
    """Submit a maintenance request for a property you're renting.

    Args:
        property_id: ID of the property
        title: Short title for the issue
        description: Detailed description of the issue
        category: plumbing, electrical, hvac, appliance, structural, pest_control, cleaning, other
        priority: low, medium, high, urgent (default: medium)
    """
    try:
        from sqlalchemy import select
        from app.models.pm_leases import Lease
        from app.models.pm_maintenance import MaintenanceRequest
        from app.models.enums import (
            LeaseStatus,
            MaintenanceCategory,
            MaintenanceRequestStatus,
            MaintenanceUrgency,
        )

        # Validate category
        try:
            cat = MaintenanceCategory(category.lower())
        except ValueError:
            valid_categories = [c.value for c in MaintenanceCategory]
            return {
                "error": True,
                "message": f"Invalid category: {category}.",
                "valid_categories": valid_categories,
            }

        priority_norm = priority.lower().strip()
        urgency_map = {
            "low": MaintenanceUrgency.low,
            "medium": MaintenanceUrgency.medium,
            "high": MaintenanceUrgency.high,
            "urgent": MaintenanceUrgency.emergency,
            "emergency": MaintenanceUrgency.emergency,
        }
        urgency = urgency_map.get(priority_norm)
        if urgency is None:
            return {
                "error": True,
                "message": f"Invalid priority: {priority}.",
                "valid_priorities": ["low", "medium", "high", "urgent"],
            }

        async for db in get_db():
            user = await _get_user(db)
            if not user:
                _require_auth(
                    action="tenant_maintenance_create",
                    message="Please log in to submit a maintenance request.",
                    scope="mcp:write",
                )

            # Verify tenant has active lease for this property
            lease_stmt = select(Lease).where(
                Lease.property_id == property_id,
                Lease.tenant_user_id == user.id,
                Lease.status == LeaseStatus.active,
            )
            lease_result = await db.execute(lease_stmt)
            lease = lease_result.scalar_one_or_none()

            if not lease:
                return {
                    "error": True,
                    "code": "INSUFFICIENT_PERMISSIONS",
                    "message": "You do not have an active lease for this property.",
                }

            # Create maintenance request
            request = MaintenanceRequest(
                property_id=property_id,
                lease_id=lease.id,
                owner_id=lease.owner_id,
                tenant_user_id=user.id,
                title=title,
                description=description,
                category=cat,
                urgency=urgency,
                priority=priority_norm,
                request_status=MaintenanceRequestStatus.open,
            )
            db.add(request)
            await db.flush()
            await db.refresh(request)
            await db.commit()

            return {
                "request": serialize_maintenance_request(request),
            }
    except AuthRequiredError:
        raise
    except Exception as e:
        logger.error(f"Error in tenant.maintenance.create: {e}", exc_info=True)
        return {
            "error": True,
            "message": "Failed to create maintenance request.",
        }


@user_mcp.tool(
    "tenant_maintenance_list",
    annotations={
        "title": "List My Maintenance Requests",
        "readOnlyHint": True,
        "securitySchemes": MCP_SECURITY_SCHEMES_MIXED,
    },
    meta=MAINTENANCE_WIDGET_META,
)
async def tenant_maintenance_list(
    page: int = 1,
    limit: int = 20,
    status: Optional[str] = None,
) -> Dict[str, Any]:
    """List maintenance requests submitted by the tenant.

    Args:
        page: Page number (default 1)
        limit: Items per page (default 20)
        status: Filter by status (open, in_progress, scheduled, completed, cancelled)
    """
    try:
        from sqlalchemy import select
        from app.models.pm_maintenance import MaintenanceRequest
        from app.models.enums import MaintenanceRequestStatus, WorkOrderStatus

        limit = min(max(1, limit), 100)

        async for db in get_db():
            user = await _get_user(db)
            if not user:
                _require_auth(
                    action="tenant_maintenance_list",
                    message="Please log in to view your maintenance requests.",
                    scope="mcp:read",
                )

            stmt = select(MaintenanceRequest).where(
                MaintenanceRequest.tenant_user_id == user.id
            )

            if status:
                status_norm = status.lower().strip()
                if status_norm == "open":
                    stmt = stmt.where(MaintenanceRequest.request_status == MaintenanceRequestStatus.open)
                elif status_norm == "in_progress":
                    stmt = stmt.where(MaintenanceRequest.work_order_status == WorkOrderStatus.in_progress)
                elif status_norm == "scheduled":
                    stmt = stmt.where(MaintenanceRequest.scheduled_for.is_not(None))
                elif status_norm == "completed":
                    stmt = stmt.where(MaintenanceRequest.completed_at.is_not(None))
                elif status_norm == "cancelled":
                    stmt = stmt.where(MaintenanceRequest.work_order_status == WorkOrderStatus.cancelled)
                else:
                    return {
                        "error": True,
                        "message": f"Invalid status: {status}.",
                        "valid_statuses": [
                            "open",
                            "in_progress",
                            "scheduled",
                            "completed",
                            "cancelled",
                        ],
                    }

            offset = (page - 1) * limit
            stmt = stmt.order_by(MaintenanceRequest.created_at.desc()).offset(offset).limit(limit)

            result = await db.execute(stmt)
            requests = result.scalars().all()

            items = [serialize_maintenance_request(r) for r in requests]

            total = len(items)
            return {
                "items": items,
                "total": total,
                "page": page,
                "limit": limit,
                "total_pages": (total + limit - 1) // limit if total else 0,
            }
    except AuthRequiredError:
        raise
    except Exception as e:
        logger.error(f"Error in tenant.maintenance.list: {e}", exc_info=True)
        return {
            "error": True,
            "message": "Failed to list maintenance requests.",
        }


# ============================================================================
# Booking Tools (for short-stay properties)
# ============================================================================


@user_mcp.tool(
    "bookings_create",
    annotations={
        "title": "Create Booking",
        "readOnlyHint": False,
        "securitySchemes": MCP_SECURITY_SCHEMES_MIXED,
    },
)
async def bookings_create(
    property_id: int,
    check_in_date: str,
    check_out_date: str,
    guests: int = 1,
    special_requests: Optional[str] = None,
) -> Dict[str, Any]:
    """Create a new booking for a short-stay property.

    Args:
        property_id: ID of the property to book
        check_in_date: Check-in date (ISO-8601 format)
        check_out_date: Check-out date (ISO-8601 format)
        guests: Number of guests (default 1)
        special_requests: Any special requests
    """
    try:
        # Parse dates
        try:
            check_in = datetime.fromisoformat(check_in_date)
            check_out = datetime.fromisoformat(check_out_date)
        except ValueError:
            return invalid_input_response("Dates must be in ISO-8601 format")

        if check_out <= check_in:
            return invalid_input_response("Check-out date must be after check-in date")

        async for db in get_db():
            user = await _get_user(db)
            if not user:
                _require_auth(
                    action="bookings_create",
                    message="Please log in to create a booking.",
                    scope="mcp:write",
                )

            # Check availability
            availability = await booking_svc.check_availability(
                db, property_id, check_in_date, check_out_date, guests
            )

            if not availability.get("available"):
                return MCPResponse.failure(
                    MCPErrorCode.BOOKING_CONFLICT,
                    availability.get("reason", "Property not available for these dates")
                ).dict()

            # Create booking
            booking_data = BookingCreate(
                property_id=property_id,
                check_in_date=check_in,
                check_out_date=check_out,
                guests=guests,
                special_requests=special_requests,
            )

            booking = await booking_svc.create_booking(db, user.id, booking_data)
            await db.commit()

            return MCPResponse.success({
                "message": "Booking created successfully",
                "booking": serialize_booking(booking),
            }).dict()
    except AuthRequiredError:
        raise
    except Exception as e:
        logger.error(f"Error in bookings.create: {e}", exc_info=True)
        return internal_error_response(f"Failed to create booking: {str(e)}")


@user_mcp.tool(
    "bookings_list",
    annotations={
        "title": "List My Bookings",
        "readOnlyHint": True,
        "securitySchemes": MCP_SECURITY_SCHEMES_MIXED,
    },
)
async def bookings_list(
    page: int = 1,
    limit: int = 20,
    status: Optional[str] = None,
) -> Dict[str, Any]:
    """List the current user's bookings.

    Args:
        page: Page number
        limit: Items per page
        status: Filter by status (pending, confirmed, checked_in, checked_out, cancelled, completed)
    """
    try:
        limit = min(max(1, limit), 100)

        async for db in get_db():
            user = await _get_user(db)
            if not user:
                _require_auth(
                    action="bookings_list",
                    message="Please log in to view your bookings.",
                    scope="mcp:read",
                )

            data = await booking_svc.get_user_bookings(db, user.id)
            bookings = data.get("bookings", [])

            # Filter by status if provided
            if status:
                bookings = [b for b in bookings if b.booking_status == status]

            # Paginate
            start = (page - 1) * limit
            end = start + limit
            paginated = bookings[start:end]

            items = [serialize_booking(b) for b in paginated]

            return MCPResponse.success({
                "total": data.get("total", 0),
                "upcoming": data.get("upcoming", 0),
                "completed": data.get("completed", 0),
                "cancelled": data.get("cancelled", 0),
                "page": page,
                "limit": limit,
                "bookings": items,
            }).dict()
    except AuthRequiredError:
        raise
    except Exception as e:
        logger.error(f"Error in bookings.list: {e}", exc_info=True)
        return internal_error_response(f"Failed to list bookings: {str(e)}")


@user_mcp.tool(
    "bookings_get",
    annotations={
        "title": "Get Booking Details",
        "readOnlyHint": True,
        "securitySchemes": MCP_SECURITY_SCHEMES_MIXED,
    },
)
async def bookings_get(
    booking_id: int,
) -> Dict[str, Any]:
    """Get details of a specific booking.

    Args:
        booking_id: ID of the booking
    """
    try:
        async for db in get_db():
            user = await _get_user(db)
            if not user:
                _require_auth(
                    action="bookings_get",
                    message="Please log in to view this booking.",
                    scope="mcp:read",
                )

            booking = await booking_svc.get_booking(db, booking_id)

            if not booking:
                return not_found_response("Booking", booking_id)

            # Verify ownership
            if booking.user_id != user.id:
                return MCPResponse.failure(
                    MCPErrorCode.INSUFFICIENT_PERMISSIONS,
                    "You can only view your own bookings"
                ).dict()

            # Get property details
            from sqlalchemy import select
            from app.models.properties import Property
            prop_stmt = select(Property).where(Property.id == booking.property_id)
            prop_result = await db.execute(prop_stmt)
            prop = prop_result.scalar_one_or_none()

            property_data = serialize_property_basic(prop) if prop else None

            return MCPResponse.success({
                "booking": serialize_booking(booking),
                "property": property_data,
            }).dict()
    except AuthRequiredError:
        raise
    except Exception as e:
        logger.error(f"Error in bookings.get: {e}", exc_info=True)
        return internal_error_response(f"Failed to get booking: {str(e)}")


@user_mcp.tool(
    "bookings_cancel",
    annotations={
        "title": "Cancel Booking",
        "readOnlyHint": False,
        "destructiveHint": True,
        "securitySchemes": MCP_SECURITY_SCHEMES_MIXED,
    },
)
async def bookings_cancel(
    booking_id: int,
    reason: str,
) -> Dict[str, Any]:
    """Cancel a booking.

    Args:
        booking_id: ID of the booking to cancel
        reason: Reason for cancellation
    """
    try:
        async for db in get_db():
            user = await _get_user(db)
            if not user:
                _require_auth(
                    action="bookings_cancel",
                    message="Please log in to cancel a booking.",
                    scope="mcp:write",
                )

            booking = await booking_svc.get_booking(db, booking_id)

            if not booking:
                return not_found_response("Booking", booking_id)

            # Verify ownership
            if booking.user_id != user.id:
                return MCPResponse.failure(
                    MCPErrorCode.INSUFFICIENT_PERMISSIONS,
                    "You can only cancel your own bookings"
                ).dict()

            # Check if can be cancelled
            if booking.booking_status in ["cancelled", "completed", "checked_out"]:
                return MCPResponse.failure(
                    MCPErrorCode.OPERATION_FAILED,
                    f"Booking cannot be cancelled (status: {booking.booking_status})"
                ).dict()

            success = await booking_svc.cancel_booking(db, booking_id, reason)
            await db.commit()

            if success:
                return MCPResponse.success({
                    "message": "Booking cancelled successfully",
                    "booking_id": booking_id,
                }).dict()
            else:
                return internal_error_response("Failed to cancel booking")
    except AuthRequiredError:
        raise
    except Exception as e:
        logger.error(f"Error in bookings.cancel: {e}", exc_info=True)
        return internal_error_response(f"Failed to cancel booking: {str(e)}")


@user_mcp.tool(
    "bookings_check_availability",
    annotations={
        "title": "Check Booking Availability",
        "readOnlyHint": True,
        "securitySchemes": MCP_SECURITY_SCHEMES_MIXED,
    },
)
async def bookings_check_availability(
    property_id: int,
    check_in_date: str,
    check_out_date: str,
    guests: int = 1,
) -> Dict[str, Any]:
    """Check if a property is available for booking.

    Args:
        property_id: ID of the property
        check_in_date: Check-in date (ISO-8601)
        check_out_date: Check-out date (ISO-8601)
        guests: Number of guests
    """
    try:
        async for db in get_db():
            result = await booking_svc.check_availability(
                db, property_id, check_in_date, check_out_date, guests
            )

            return MCPResponse.success({
                "available": result.get("available", False),
                "reason": result.get("reason"),
                "max_occupancy": result.get("max_occupancy"),
            }).dict()
    except AuthRequiredError:
        raise
    except Exception as e:
        logger.error(f"Error in bookings.check_availability: {e}", exc_info=True)
        return internal_error_response(f"Failed to check availability: {str(e)}")


@user_mcp.tool(
    "bookings_get_pricing",
    annotations={
        "title": "Get Booking Pricing",
        "readOnlyHint": True,
        "securitySchemes": MCP_SECURITY_SCHEMES_MIXED,
    },
)
async def bookings_get_pricing(
    property_id: int,
    check_in_date: str,
    check_out_date: str,
    guests: int = 1,
) -> Dict[str, Any]:
    """Get pricing details for a potential booking.

    Args:
        property_id: ID of the property
        check_in_date: Check-in date (ISO-8601)
        check_out_date: Check-out date (ISO-8601)
        guests: Number of guests
    """
    try:
        try:
            check_in = datetime.fromisoformat(check_in_date)
            check_out = datetime.fromisoformat(check_out_date)
        except ValueError:
            return invalid_input_response("Dates must be in ISO-8601 format")

        async for db in get_db():
            pricing = await booking_svc.calculate_pricing(
                db, property_id, check_in, check_out, guests
            )

            if isinstance(pricing, dict) and pricing.get("error"):
                return MCPResponse.failure(
                    MCPErrorCode.INVALID_INPUT,
                    pricing["error"]
                ).dict()

            return MCPResponse.success({
                "pricing": pricing,
            }).dict()
    except AuthRequiredError:
        raise
    except Exception as e:
        logger.error(f"Error in bookings.get_pricing: {e}", exc_info=True)
        return internal_error_response(f"Failed to get pricing: {str(e)}")


# ============================================================================
# System Tools
# ============================================================================


@user_mcp.tool(
    "user_system_status",
    annotations={
        "title": "System Status",
        "readOnlyHint": True,
        "securitySchemes": MCP_SECURITY_SCHEMES_MIXED,
    },
)
async def user_system_status() -> Dict[str, Any]:
    """Get system status and available user features."""
    try:
        auth_status = "unauthenticated"
        user_info = None

        async for db in get_db():
            user = await _get_user(db)
            if user:
                auth_status = "authenticated"
                user_info = {
                    "id": user.id,
                    "role": getattr(user, "role", "user"),
                    "full_name": getattr(user, "full_name", None),
                }

        return MCPResponse.success({
            "status": "operational",
            "version": "2.0.0",
            "server": "user",
            "auth": {
                "status": auth_status,
                "user": user_info,
            },
            "features": {
                "owner": {
                    "properties.list": True,
                    "properties.create": True,
                    "properties.update": True,
                    "properties.toggle_availability": True,
                },
                "tenant": {
                    "lease.current": True,
                    "rent.history": True,
                    "maintenance.create": True,
                    "maintenance.list": True,
                },
                "bookings": {
                    "create": True,
                    "list": True,
                    "get": True,
                    "cancel": True,
                    "check_availability": True,
                    "get_pricing": True,
                },
            },
        }).dict()
    except AuthRequiredError:
        raise
    except Exception as e:
        logger.error(f"Error in user.system.status: {e}", exc_info=True)
        return internal_error_response(f"Failed to get system status: {str(e)}")


# ============================================================================
# ChatGPT App Tools Registration
# ============================================================================
# Import ChatGPT tools to register them on this MCP server
# These imports trigger the @user_mcp.tool decorators in the chatgpt module
try:
    from app.mcp.chatgpt import discovery_tools  # noqa: F401
    from app.mcp.chatgpt import visit_tools  # noqa: F401
    from app.mcp.chatgpt import pm_tools  # noqa: F401
    logger.info("ChatGPT App tools registered successfully")
except ImportError as e:
    logger.warning(f"ChatGPT tools not registered: {e}")
