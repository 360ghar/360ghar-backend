"""
Admin MCP Server - For agents and administrators.

This server provides MCP tools for:
- Agents: Manage properties for assigned owners, handle leases, rent collection
- Admins: Full access to all properties, users, and system management

Mounted at: /mcp-admin
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from app.mcp.apps_sdk import (
    AppsSDKFastMCP,
    AuthRequiredError,
    MCP_SECURITY_SCHEMES_MIXED,
    raise_auth_required,
)

from app.core.database import AsyncSessionLocal
from app.core.exceptions import (
    InsufficientPermissionsError,
    PropertyNotFoundException,
    NotFoundException,
)
from app.core.logging import get_logger
from app.models.enums import UserRole
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
    get_user_role,
    is_admin,
    is_agent,
    serialize_property_basic,
    serialize_property_full,
    serialize_booking,
    serialize_lease,
    serialize_maintenance_request,
    serialize_user_basic,
)

logger = get_logger(__name__)

# Create the Admin MCP server instance
admin_mcp = AppsSDKFastMCP("ghar360-admin")


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


def _require_agent_or_admin(user) -> bool:
    """Check if user is agent or admin, return True if authorized."""
    role = get_user_role(user)
    return role in (UserRole.agent, UserRole.admin)


# ============================================================================
# Agent Property Management Tools
# ============================================================================


@admin_mcp.tool(
    "agent_properties_list",
    annotations={
        "title": "List Managed Properties",
        "readOnlyHint": True,
        "securitySchemes": MCP_SECURITY_SCHEMES_MIXED,
    },
)
async def agent_properties_list(
    owner_id: Optional[int] = None,
    page: int = 1,
    limit: int = 50,
    occupancy: Optional[str] = None,
    q: Optional[str] = None,
) -> Dict[str, Any]:
    """List managed properties for agents/admins.

    Agents see properties of their assigned owners.
    Admins see all properties.

    Args:
        owner_id: Filter by specific owner (required for agents)
        page: Page number
        limit: Items per page (max 100)
        occupancy: Filter by 'occupied' or 'vacant'
        q: Search query
    """
    try:
        limit = min(max(1, limit), 100)

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
                    "This endpoint is for agents and admins only"
                ).dict()

            from app.schemas.user import User as UserSchema
            from app.services.pm_properties import list_managed_properties

            user_schema = UserSchema.model_validate(user)

            try:
                properties = await list_managed_properties(
                    db,
                    actor=user_schema,
                    owner_id=owner_id,
                    occupancy=occupancy,
                    q=q,
                    limit=limit,
                    offset=(page - 1) * limit,
                )
            except InsufficientPermissionsError as e:
                return MCPResponse.failure(
                    MCPErrorCode.INSUFFICIENT_PERMISSIONS,
                    str(e)
                ).dict()

            items = [serialize_property_basic(p) for p in properties]

            return MCPResponse.success({
                "total": len(items),
                "page": page,
                "limit": limit,
                "items": items,
            }).dict()
    except AuthRequiredError:
        raise
    except Exception as e:
        logger.error(f"Error in agent.properties.list: {e}", exc_info=True)
        return internal_error_response(f"Failed to list properties: {str(e)}")


@admin_mcp.tool(
    "agent_properties_get",
    annotations={
        "title": "Get Managed Property Details",
        "readOnlyHint": True,
        "securitySchemes": MCP_SECURITY_SCHEMES_MIXED,
    },
)
async def agent_properties_get(
    property_id: int,
) -> Dict[str, Any]:
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
                    "This endpoint is for agents and admins only"
                ).dict()

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
                    MCPErrorCode.INSUFFICIENT_PERMISSIONS,
                    "You do not have access to this property"
                ).dict()

            prop = result["property"]
            active_lease = result.get("active_lease")

            property_data = serialize_property_full(prop)

            # Get owner info
            owner_data = None
            if prop.owner_id:
                from app.services.user import get_user_by_id
                owner = await get_user_by_id(db, prop.owner_id)
                if owner:
                    owner_data = serialize_user_basic(owner)

            lease_data = None
            tenant_data = None
            if active_lease:
                lease_data = serialize_lease(active_lease)
                if active_lease.tenant_user_id:
                    tenant = await get_user_by_id(db, active_lease.tenant_user_id)
                    if tenant:
                        tenant_data = serialize_user_basic(tenant)

            return MCPResponse.success({
                "property": property_data,
                "owner": owner_data,
                "active_lease": lease_data,
                "tenant": tenant_data,
            }).dict()
    except AuthRequiredError:
        raise
    except Exception as e:
        logger.error(f"Error in agent.properties.get: {e}", exc_info=True)
        return internal_error_response(f"Failed to get property: {str(e)}")


@admin_mcp.tool(
    "agent_properties_create_for_owner",
    annotations={
        "title": "Create Property For Owner",
        "readOnlyHint": False,
        "securitySchemes": MCP_SECURITY_SCHEMES_MIXED,
    },
)
async def agent_properties_create_for_owner(
    owner_id: int,
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
    monthly_rent: Optional[float] = None,
    daily_rate: Optional[float] = None,
    bedrooms: Optional[int] = None,
    bathrooms: Optional[int] = None,
    area_sqft: Optional[float] = None,
    main_image_url: Optional[str] = None,
    payment_due_day: int = 1,
    grace_period_days: int = 5,
) -> Dict[str, Any]:
    """Create a property for an owner (agent/admin only).

    Args:
        owner_id: ID of the property owner
        title: Property title
        property_type: house, apartment, builder_floor, room
        purpose: buy, rent, short_stay
        ... (other property fields)
    """
    try:
        from app.models.enums import PropertyType, PropertyPurpose

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
                    "This endpoint is for agents and admins only"
                ).dict()

            from app.schemas.user import User as UserSchema
            from app.schemas.property import PropertyCreate
            from app.services.pm_properties import create_managed_property

            user_schema = UserSchema.model_validate(user)

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
                    MCPErrorCode.INSUFFICIENT_PERMISSIONS,
                    str(e)
                ).dict()

            return MCPResponse.success({
                "message": "Property created successfully",
                "property": serialize_property_basic(prop),
            }).dict()
    except AuthRequiredError:
        raise
    except Exception as e:
        logger.error(f"Error in agent.properties.create_for_owner: {e}", exc_info=True)
        return internal_error_response(f"Failed to create property: {str(e)}")


@admin_mcp.tool(
    "agent_properties_verify",
    annotations={
        "title": "Verify Property Listing",
        "readOnlyHint": False,
        "securitySchemes": MCP_SECURITY_SCHEMES_MIXED,
    },
)
async def agent_properties_verify(
    property_id: int,
    is_verified: bool,
    verification_notes: Optional[str] = None,
) -> Dict[str, Any]:
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
                    "This endpoint is for agents and admins only"
                ).dict()

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
                    MCPErrorCode.INSUFFICIENT_PERMISSIONS,
                    "You do not have access to this property"
                ).dict()

            prop.is_verified = is_verified
            if verification_notes:
                # Store in features JSON if no dedicated field
                features = prop.features or {}
                features["verification_notes"] = verification_notes
                features["verified_by"] = user.id
                features["verified_at"] = datetime.utcnow().isoformat()
                prop.features = features

            await db.flush()
            await db.commit()

            status = "verified" if is_verified else "unverified"
            return MCPResponse.success({
                "message": f"Property marked as {status}",
                "property_id": property_id,
                "is_verified": is_verified,
            }).dict()
    except AuthRequiredError:
        raise
    except Exception as e:
        logger.error(f"Error in agent.properties.verify: {e}", exc_info=True)
        return internal_error_response(f"Failed to verify property: {str(e)}")


# ============================================================================
# Lease Management Tools
# ============================================================================


@admin_mcp.tool(
    "agent_leases_list",
    annotations={
        "title": "List Leases",
        "readOnlyHint": True,
        "securitySchemes": MCP_SECURITY_SCHEMES_MIXED,
    },
)
async def agent_leases_list(
    owner_id: Optional[int] = None,
    property_id: Optional[int] = None,
    status: Optional[str] = None,
    page: int = 1,
    limit: int = 20,
) -> Dict[str, Any]:
    """List leases for managed properties.

    Args:
        owner_id: Filter by owner
        property_id: Filter by property
        status: Filter by status (draft, active, expired, terminated)
        page: Page number
        limit: Items per page
    """
    try:
        from sqlalchemy import select
        from app.models.pm_leases import Lease
        from app.models.properties import Property
        from app.models.enums import LeaseStatus

        limit = min(max(1, limit), 100)

        async for db in get_db():
            user = await _get_user(db)
            if not user:
                _require_auth(
                    action="agent_leases_list",
                    message="Please log in to list leases.",
                    scope="mcp:read",
                )

            if not _require_agent_or_admin(user):
                return MCPResponse.failure(
                    MCPErrorCode.INSUFFICIENT_PERMISSIONS,
                    "This endpoint is for agents and admins only"
                ).dict()

            from app.services.pm_authz import get_accessible_owner_ids

            user_role = get_user_role(user)

            # Build query
            stmt = select(Lease)

            # Apply owner filter based on role
            if user_role != UserRole.admin:
                accessible_owners = await get_accessible_owner_ids(db, actor=user)
                if accessible_owners is not None:
                    if owner_id and owner_id not in accessible_owners:
                        return MCPResponse.failure(
                            MCPErrorCode.INSUFFICIENT_PERMISSIONS,
                            "You do not have access to this owner's leases"
                        ).dict()
                    stmt = stmt.where(Lease.owner_id.in_(accessible_owners))

            if owner_id:
                stmt = stmt.where(Lease.owner_id == owner_id)
            if property_id:
                stmt = stmt.where(Lease.property_id == property_id)
            if status:
                try:
                    status_enum = LeaseStatus(status.lower())
                    stmt = stmt.where(Lease.status == status_enum)
                except ValueError:
                    return invalid_input_response(f"Invalid status: {status}")

            offset = (page - 1) * limit
            stmt = stmt.order_by(Lease.created_at.desc()).offset(offset).limit(limit)

            result = await db.execute(stmt)
            leases = result.scalars().all()

            items = [serialize_lease(l) for l in leases]

            return MCPResponse.success({
                "total": len(items),
                "page": page,
                "limit": limit,
                "leases": items,
            }).dict()
    except AuthRequiredError:
        raise
    except Exception as e:
        logger.error(f"Error in agent.leases.list: {e}", exc_info=True)
        return internal_error_response(f"Failed to list leases: {str(e)}")


@admin_mcp.tool(
    "agent_leases_create",
    annotations={
        "title": "Create Lease",
        "readOnlyHint": False,
        "securitySchemes": MCP_SECURITY_SCHEMES_MIXED,
    },
)
async def agent_leases_create(
    property_id: int,
    tenant_user_id: int,
    start_date: str,
    end_date: str,
    monthly_rent: float,
    security_deposit: float,
    payment_due_day: int = 1,
    grace_period_days: int = 5,
    terms: Optional[str] = None,
    notes: Optional[str] = None,
) -> Dict[str, Any]:
    """Create a new lease for a property.

    Args:
        property_id: ID of the property
        tenant_user_id: ID of the tenant user
        start_date: Lease start date (ISO-8601)
        end_date: Lease end date (ISO-8601)
        monthly_rent: Monthly rent amount
        security_deposit: Security deposit amount
        payment_due_day: Day of month rent is due (1-28)
        grace_period_days: Grace period for late payments
        terms: Lease terms and conditions
        notes: Additional notes
    """
    try:
        from app.models.pm_leases import Lease
        from app.models.enums import LeaseStatus

        try:
            start = datetime.fromisoformat(start_date)
            end = datetime.fromisoformat(end_date)
        except ValueError:
            return invalid_input_response("Dates must be in ISO-8601 format")

        if end <= start:
            return invalid_input_response("End date must be after start date")

        async for db in get_db():
            user = await _get_user(db)
            if not user:
                _require_auth(
                    action="agent_leases_create",
                    message="Please log in to create a lease.",
                    scope="mcp:write",
                )

            if not _require_agent_or_admin(user):
                return MCPResponse.failure(
                    MCPErrorCode.INSUFFICIENT_PERMISSIONS,
                    "This endpoint is for agents and admins only"
                ).dict()

            from app.schemas.user import User as UserSchema
            from app.services.pm_authz import assert_can_access_property

            user_schema = UserSchema.model_validate(user)

            # Verify access to property
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

            # Verify tenant exists
            from app.services.user import get_user_by_id
            tenant = await get_user_by_id(db, tenant_user_id)
            if not tenant:
                return not_found_response("Tenant user", tenant_user_id)

            # Create lease
            lease = Lease(
                property_id=property_id,
                owner_id=prop.owner_id,
                tenant_user_id=tenant_user_id,
                start_date=start,
                end_date=end,
                monthly_rent=monthly_rent,
                security_deposit=security_deposit,
                payment_due_day=payment_due_day,
                grace_period_days=grace_period_days,
                terms=terms,
                notes=notes,
                status=LeaseStatus.active,
            )
            db.add(lease)
            await db.flush()
            await db.refresh(lease)
            await db.commit()

            return MCPResponse.success({
                "message": "Lease created successfully",
                "lease": serialize_lease(lease),
            }).dict()
    except AuthRequiredError:
        raise
    except Exception as e:
        logger.error(f"Error in agent.leases.create: {e}", exc_info=True)
        return internal_error_response(f"Failed to create lease: {str(e)}")


@admin_mcp.tool(
    "agent_leases_terminate",
    annotations={
        "title": "Terminate Lease",
        "readOnlyHint": False,
        "destructiveHint": True,
        "securitySchemes": MCP_SECURITY_SCHEMES_MIXED,
    },
)
async def agent_leases_terminate(
    lease_id: int,
    reason: str,
    termination_date: Optional[str] = None,
) -> Dict[str, Any]:
    """Terminate an active lease.

    Args:
        lease_id: ID of the lease
        reason: Reason for termination
        termination_date: Termination date (ISO-8601, defaults to today)
    """
    try:
        from app.models.enums import LeaseStatus

        term_date = datetime.utcnow()
        if termination_date:
            try:
                term_date = datetime.fromisoformat(termination_date)
            except ValueError:
                return invalid_input_response("termination_date must be in ISO-8601 format")

        async for db in get_db():
            user = await _get_user(db)
            if not user:
                _require_auth(
                    action="agent_leases_terminate",
                    message="Please log in to terminate a lease.",
                    scope="mcp:write",
                )

            if not _require_agent_or_admin(user):
                return MCPResponse.failure(
                    MCPErrorCode.INSUFFICIENT_PERMISSIONS,
                    "This endpoint is for agents and admins only"
                ).dict()

            from app.schemas.user import User as UserSchema
            from app.services.pm_authz import assert_can_access_lease

            user_schema = UserSchema.model_validate(user)

            try:
                lease = await assert_can_access_lease(
                    db, actor=user_schema, lease_id=lease_id
                )
            except NotFoundException:
                return not_found_response("Lease", lease_id)
            except InsufficientPermissionsError:
                return MCPResponse.failure(
                    MCPErrorCode.INSUFFICIENT_PERMISSIONS,
                    "You do not have access to this lease"
                ).dict()

            if lease.status != LeaseStatus.active:
                return MCPResponse.failure(
                    MCPErrorCode.OPERATION_FAILED,
                    f"Lease cannot be terminated (status: {lease.status.value})"
                ).dict()

            lease.status = LeaseStatus.terminated
            lease.end_date = term_date
            lease.notes = f"{lease.notes or ''}\nTerminated: {reason}".strip()

            await db.flush()
            await db.commit()

            return MCPResponse.success({
                "message": "Lease terminated successfully",
                "lease_id": lease_id,
                "termination_date": term_date.isoformat(),
            }).dict()
    except AuthRequiredError:
        raise
    except Exception as e:
        logger.error(f"Error in agent.leases.terminate: {e}", exc_info=True)
        return internal_error_response(f"Failed to terminate lease: {str(e)}")


# ============================================================================
# Rent Collection Tools
# ============================================================================


@admin_mcp.tool(
    "agent_rent_list_due",
    annotations={
        "title": "List Overdue Rent",
        "readOnlyHint": True,
        "securitySchemes": MCP_SECURITY_SCHEMES_MIXED,
    },
)
async def agent_rent_list_due(
    owner_id: Optional[int] = None,
    property_id: Optional[int] = None,
    overdue_only: bool = False,
    page: int = 1,
    limit: int = 20,
) -> Dict[str, Any]:
    """List due/overdue rent payments.

    Args:
        owner_id: Filter by owner
        property_id: Filter by property
        overdue_only: Only show overdue payments
        page: Page number
        limit: Items per page
    """
    try:
        from sqlalchemy import select, and_
        from app.models.pm_leases import Lease
        from app.models.enums import LeaseStatus

        limit = min(max(1, limit), 100)

        async for db in get_db():
            user = await _get_user(db)
            if not user:
                _require_auth(
                    action="agent_rent_list_due",
                    message="Please log in to view overdue rent.",
                    scope="mcp:read",
                )

            if not _require_agent_or_admin(user):
                return MCPResponse.failure(
                    MCPErrorCode.INSUFFICIENT_PERMISSIONS,
                    "This endpoint is for agents and admins only"
                ).dict()

            from app.services.pm_authz import get_accessible_owner_ids

            user_role = get_user_role(user)

            # Get active leases
            stmt = select(Lease).where(Lease.status == LeaseStatus.active)

            if user_role != UserRole.admin:
                accessible_owners = await get_accessible_owner_ids(db, actor=user)
                if accessible_owners is not None:
                    stmt = stmt.where(Lease.owner_id.in_(accessible_owners))

            if owner_id:
                stmt = stmt.where(Lease.owner_id == owner_id)
            if property_id:
                stmt = stmt.where(Lease.property_id == property_id)

            result = await db.execute(stmt)
            leases = result.scalars().all()

            # Calculate due amounts for each lease
            today = datetime.utcnow().date()
            due_items = []

            for lease in leases:
                payment_due_day = lease.payment_due_day or 1
                grace_days = lease.grace_period_days or 5

                # Determine if rent is due this month
                due_date = today.replace(day=min(payment_due_day, 28))
                grace_end = due_date.replace(day=min(payment_due_day + grace_days, 28))

                is_overdue = today > grace_end
                is_due = today >= due_date

                if overdue_only and not is_overdue:
                    continue

                if is_due:
                    due_items.append({
                        "lease_id": lease.id,
                        "property_id": lease.property_id,
                        "owner_id": lease.owner_id,
                        "tenant_user_id": lease.tenant_user_id,
                        "monthly_rent": float(lease.monthly_rent or 0),
                        "due_date": due_date.isoformat(),
                        "is_overdue": is_overdue,
                        "days_overdue": (today - grace_end).days if is_overdue else 0,
                    })

            # Paginate
            start = (page - 1) * limit
            end = start + limit
            paginated = due_items[start:end]

            return MCPResponse.success({
                "total": len(due_items),
                "overdue_count": sum(1 for i in due_items if i["is_overdue"]),
                "page": page,
                "limit": limit,
                "items": paginated,
            }).dict()
    except AuthRequiredError:
        raise
    except Exception as e:
        logger.error(f"Error in agent.rent.list_due: {e}", exc_info=True)
        return internal_error_response(f"Failed to list due rent: {str(e)}")


@admin_mcp.tool(
    "agent_rent_record_payment",
    annotations={
        "title": "Record Rent Payment",
        "readOnlyHint": False,
        "securitySchemes": MCP_SECURITY_SCHEMES_MIXED,
    },
)
async def agent_rent_record_payment(
    lease_id: int,
    amount: float,
    payment_date: str,
    payment_method: str,
    transaction_reference: Optional[str] = None,
    notes: Optional[str] = None,
) -> Dict[str, Any]:
    """Record a rent payment for a lease.

    Args:
        lease_id: ID of the lease
        amount: Payment amount
        payment_date: Date of payment (ISO-8601)
        payment_method: cash, bank_transfer, upi, cheque, online
        transaction_reference: Reference number
        notes: Additional notes
    """
    try:
        from app.models.pm_finance import RentPayment

        try:
            pay_date = datetime.fromisoformat(payment_date)
        except ValueError:
            return invalid_input_response("payment_date must be in ISO-8601 format")

        valid_methods = ['cash', 'bank_transfer', 'upi', 'cheque', 'online', 'other']
        if payment_method.lower() not in valid_methods:
            return invalid_input_response(f"payment_method must be one of: {', '.join(valid_methods)}")

        async for db in get_db():
            user = await _get_user(db)
            if not user:
                _require_auth(
                    action="agent_rent_record_payment",
                    message="Please log in to record a rent payment.",
                    scope="mcp:write",
                )

            if not _require_agent_or_admin(user):
                return MCPResponse.failure(
                    MCPErrorCode.INSUFFICIENT_PERMISSIONS,
                    "This endpoint is for agents and admins only"
                ).dict()

            from app.schemas.user import User as UserSchema
            from app.services.pm_authz import assert_can_access_lease

            user_schema = UserSchema.model_validate(user)

            try:
                lease = await assert_can_access_lease(
                    db, actor=user_schema, lease_id=lease_id
                )
            except NotFoundException:
                return not_found_response("Lease", lease_id)
            except InsufficientPermissionsError:
                return MCPResponse.failure(
                    MCPErrorCode.INSUFFICIENT_PERMISSIONS,
                    "You do not have access to this lease"
                ).dict()

            # Create payment record
            payment = RentPayment(
                lease_id=lease_id,
                amount_paid=amount,
                paid_at=pay_date,
                payment_method=payment_method.lower(),
                reference=transaction_reference,
                notes=notes,
                recorded_by_user_id=user.id,
                status="completed",
            )
            db.add(payment)
            await db.flush()
            await db.refresh(payment)
            await db.commit()

            return MCPResponse.success({
                "message": "Payment recorded successfully",
                "payment": {
                    "id": payment.id,
                    "lease_id": payment.lease_id,
                    "amount": float(payment.amount_paid),
                    "payment_date": payment.paid_at.isoformat() if payment.paid_at else None,
                    "payment_method": payment.payment_method,
                    "status": payment.status,
                },
            }).dict()
    except AuthRequiredError:
        raise
    except Exception as e:
        logger.error(f"Error in agent.rent.record_payment: {e}", exc_info=True)
        return internal_error_response(f"Failed to record payment: {str(e)}")


# ============================================================================
# Maintenance Management Tools
# ============================================================================


@admin_mcp.tool(
    "agent_maintenance_list",
    annotations={
        "title": "List Maintenance Requests",
        "readOnlyHint": True,
        "securitySchemes": MCP_SECURITY_SCHEMES_MIXED,
    },
)
async def agent_maintenance_list(
    owner_id: Optional[int] = None,
    property_id: Optional[int] = None,
    status: Optional[str] = None,
    page: int = 1,
    limit: int = 20,
) -> Dict[str, Any]:
    """List maintenance requests for managed properties.

    Args:
        owner_id: Filter by owner
        property_id: Filter by property
        status: Filter by status (open, in_progress, scheduled, completed, cancelled)
        page: Page number
        limit: Items per page
    """
    try:
        from sqlalchemy import select
        from app.models.pm_maintenance import MaintenanceRequest
        from app.models.properties import Property
        from app.models.enums import MaintenanceRequestStatus, WorkOrderStatus

        limit = min(max(1, limit), 100)

        async for db in get_db():
            user = await _get_user(db)
            if not user:
                _require_auth(
                    action="agent_maintenance_list",
                    message="Please log in to view maintenance requests.",
                    scope="mcp:read",
                )

            if not _require_agent_or_admin(user):
                return MCPResponse.failure(
                    MCPErrorCode.INSUFFICIENT_PERMISSIONS,
                    "This endpoint is for agents and admins only"
                ).dict()

            from app.services.pm_authz import get_accessible_owner_ids

            user_role = get_user_role(user)

            # Build query with property join for owner filtering
            stmt = select(MaintenanceRequest).join(
                Property, MaintenanceRequest.property_id == Property.id
            )

            if user_role != UserRole.admin:
                accessible_owners = await get_accessible_owner_ids(db, actor=user)
                if accessible_owners is not None:
                    stmt = stmt.where(Property.owner_id.in_(accessible_owners))

            if owner_id:
                stmt = stmt.where(Property.owner_id == owner_id)
            if property_id:
                stmt = stmt.where(MaintenanceRequest.property_id == property_id)
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
                    return invalid_input_response(f"Invalid status: {status}")

            offset = (page - 1) * limit
            stmt = stmt.order_by(MaintenanceRequest.created_at.desc()).offset(offset).limit(limit)

            result = await db.execute(stmt)
            requests = result.scalars().all()

            items = [serialize_maintenance_request(r) for r in requests]

            return MCPResponse.success({
                "total": len(items),
                "page": page,
                "limit": limit,
                "requests": items,
            }).dict()
    except AuthRequiredError:
        raise
    except Exception as e:
        logger.error(f"Error in agent.maintenance.list: {e}", exc_info=True)
        return internal_error_response(f"Failed to list maintenance requests: {str(e)}")


@admin_mcp.tool(
    "agent_maintenance_update_status",
    annotations={
        "title": "Update Maintenance Status",
        "readOnlyHint": False,
        "securitySchemes": MCP_SECURITY_SCHEMES_MIXED,
    },
)
async def agent_maintenance_update_status(
    request_id: int,
    status: str,
    notes: Optional[str] = None,
    scheduled_date: Optional[str] = None,
    vendor_name: Optional[str] = None,
    vendor_contact: Optional[str] = None,
    estimated_cost: Optional[float] = None,
    actual_cost: Optional[float] = None,
) -> Dict[str, Any]:
    """Update the status of a maintenance request.

    Args:
        request_id: ID of the maintenance request
        status: New status (in_progress, scheduled, completed, cancelled)
        notes: Status update notes
        scheduled_date: Date scheduled for work (ISO-8601)
        vendor_name: Name of assigned vendor
        vendor_contact: Vendor contact info
        estimated_cost: Estimated cost
        actual_cost: Actual cost (when completed)
    """
    try:
        from sqlalchemy import select
        from app.models.pm_maintenance import MaintenanceRequest
        from app.models.enums import MaintenanceRequestStatus, WorkOrderStatus

        valid_statuses = ['open', 'in_progress', 'scheduled', 'completed', 'cancelled']
        if status.lower() not in valid_statuses:
            return invalid_input_response(f"status must be one of: {', '.join(valid_statuses)}")

        status_norm = status.lower().strip()

        async for db in get_db():
            user = await _get_user(db)
            if not user:
                _require_auth(
                    action="agent_maintenance_update_status",
                    message="Please log in to update maintenance status.",
                    scope="mcp:write",
                )

            if not _require_agent_or_admin(user):
                return MCPResponse.failure(
                    MCPErrorCode.INSUFFICIENT_PERMISSIONS,
                    "This endpoint is for agents and admins only"
                ).dict()

            # Get the request with property for auth check
            stmt = select(MaintenanceRequest).where(MaintenanceRequest.id == request_id)
            result = await db.execute(stmt)
            request = result.scalar_one_or_none()

            if not request:
                return not_found_response("Maintenance request", request_id)

            # Verify access to the property
            from app.schemas.user import User as UserSchema
            from app.services.pm_authz import assert_can_access_property

            user_schema = UserSchema.model_validate(user)

            try:
                await assert_can_access_property(
                    db, actor=user_schema, property_id=request.property_id
                )
            except InsufficientPermissionsError:
                return MCPResponse.failure(
                    MCPErrorCode.INSUFFICIENT_PERMISSIONS,
                    "You do not have access to this property's maintenance requests"
                ).dict()

            # Update the request
            if notes:
                existing = getattr(request, "completion_notes", None) or ""
                stamp = datetime.utcnow().isoformat()
                request.completion_notes = f"{existing}\n[{stamp}] {notes}".strip()
            if scheduled_date:
                try:
                    request.scheduled_for = datetime.fromisoformat(scheduled_date.replace("Z", "+00:00"))
                except ValueError:
                    return invalid_input_response("scheduled_date must be in ISO-8601 format")
            if estimated_cost is not None:
                request.estimated_cost = estimated_cost
            if actual_cost is not None:
                request.actual_cost = actual_cost

            if status_norm == "open":
                request.request_status = MaintenanceRequestStatus.open
                request.work_order_status = None
                request.scheduled_for = None
                request.completed_at = None
            elif status_norm == "scheduled":
                request.request_status = MaintenanceRequestStatus.work_order_created
                request.work_order_status = WorkOrderStatus.assigned
            elif status_norm == "in_progress":
                request.request_status = MaintenanceRequestStatus.work_order_created
                request.work_order_status = WorkOrderStatus.in_progress
            elif status_norm == "completed":
                request.request_status = MaintenanceRequestStatus.resolved
                request.work_order_status = WorkOrderStatus.completed
                if request.completed_at is None:
                    request.completed_at = datetime.utcnow()
            elif status_norm == "cancelled":
                request.request_status = MaintenanceRequestStatus.closed
                request.work_order_status = WorkOrderStatus.cancelled

            await db.flush()
            await db.commit()

            return MCPResponse.success({
                "message": "Maintenance request updated successfully",
                "request": serialize_maintenance_request(request),
            }).dict()
    except AuthRequiredError:
        raise
    except Exception as e:
        logger.error(f"Error in agent.maintenance.update_status: {e}", exc_info=True)
        return internal_error_response(f"Failed to update maintenance request: {str(e)}")


# ============================================================================
# Booking Management Tools (Admin view)
# ============================================================================


@admin_mcp.tool(
    "agent_bookings_list_all",
    annotations={
        "title": "List All Bookings",
        "readOnlyHint": True,
        "securitySchemes": MCP_SECURITY_SCHEMES_MIXED,
    },
)
async def agent_bookings_list_all(
    owner_id: Optional[int] = None,
    property_id: Optional[int] = None,
    status: Optional[str] = None,
    page: int = 1,
    limit: int = 20,
) -> Dict[str, Any]:
    """List all bookings for managed properties.

    Args:
        owner_id: Filter by property owner
        property_id: Filter by property
        status: Filter by booking status
        page: Page number
        limit: Items per page
    """
    try:
        limit = min(max(1, limit), 100)

        async for db in get_db():
            user = await _get_user(db)
            if not user:
                _require_auth(
                    action="agent_bookings_list_all",
                    message="Please log in to view bookings.",
                    scope="mcp:read",
                )

            if not _require_agent_or_admin(user):
                return MCPResponse.failure(
                    MCPErrorCode.INSUFFICIENT_PERMISSIONS,
                    "This endpoint is for agents and admins only"
                ).dict()

            from app.services import booking as booking_svc

            user_role = get_user_role(user)
            filter_agent_id = None

            # Agents can only see bookings for their assigned users/properties
            if user_role == UserRole.agent and user.agent_id:
                filter_agent_id = user.agent_id

            data = await booking_svc.get_all_bookings(
                db,
                page=page,
                limit=limit,
                status=status,
                filter_agent_id=filter_agent_id,
                property_id=property_id,
                user_id=None,
            )

            items = [serialize_booking(b) for b in data.get("bookings", [])]

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
        logger.error(f"Error in agent.bookings.list_all: {e}", exc_info=True)
        return internal_error_response(f"Failed to list bookings: {str(e)}")


@admin_mcp.tool(
    "agent_bookings_update_status",
    annotations={
        "title": "Update Booking Status",
        "readOnlyHint": False,
        "securitySchemes": MCP_SECURITY_SCHEMES_MIXED,
    },
)
async def agent_bookings_update_status(
    booking_id: int,
    status: str,
    notes: Optional[str] = None,
) -> Dict[str, Any]:
    """Update the status of a booking.

    Args:
        booking_id: ID of the booking
        status: New status (confirmed, checked_in, checked_out, cancelled, completed)
        notes: Status update notes
    """
    try:
        valid_statuses = ['confirmed', 'checked_in', 'checked_out', 'cancelled', 'completed']
        if status.lower() not in valid_statuses:
            return invalid_input_response(f"status must be one of: {', '.join(valid_statuses)}")

        async for db in get_db():
            user = await _get_user(db)
            if not user:
                _require_auth(
                    action="agent_bookings_update_status",
                    message="Please log in to update a booking status.",
                    scope="mcp:write",
                )

            if not _require_agent_or_admin(user):
                return MCPResponse.failure(
                    MCPErrorCode.INSUFFICIENT_PERMISSIONS,
                    "This endpoint is for agents and admins only"
                ).dict()

            from app.services import booking as booking_svc

            booking = await booking_svc.get_booking(db, booking_id)
            if not booking:
                return not_found_response("Booking", booking_id)

            # Update booking status
            from app.schemas.booking import BookingUpdate
            update_data = BookingUpdate(booking_status=status.lower())
            if notes:
                update_data.notes = notes

            updated = await booking_svc.update_booking(db, booking_id, update_data)
            await db.commit()

            return MCPResponse.success({
                "message": f"Booking status updated to {status}",
                "booking": serialize_booking(updated) if updated else None,
            }).dict()
    except AuthRequiredError:
        raise
    except Exception as e:
        logger.error(f"Error in agent.bookings.update_status: {e}", exc_info=True)
        return internal_error_response(f"Failed to update booking status: {str(e)}")


# ============================================================================
# Dashboard Tools
# ============================================================================


@admin_mcp.tool(
    "agent_dashboard_overview",
    annotations={
        "title": "Agent Dashboard Overview",
        "readOnlyHint": True,
        "securitySchemes": MCP_SECURITY_SCHEMES_MIXED,
    },
)
async def agent_dashboard_overview(
    owner_id: Optional[int] = None,
) -> Dict[str, Any]:
    """Get dashboard overview with key metrics.

    Args:
        owner_id: Filter by specific owner (optional for admins)
    """
    try:
        from sqlalchemy import select, func
        from app.models.properties import Property
        from app.models.pm_leases import Lease
        from app.models.pm_maintenance import MaintenanceRequest
        from app.models.bookings import Booking
        from app.models.enums import LeaseStatus, MaintenanceRequestStatus

        async for db in get_db():
            user = await _get_user(db)
            if not user:
                _require_auth(
                    action="agent_dashboard_overview",
                    message="Please log in to view the agent dashboard.",
                    scope="mcp:read",
                )

            if not _require_agent_or_admin(user):
                return MCPResponse.failure(
                    MCPErrorCode.INSUFFICIENT_PERMISSIONS,
                    "This endpoint is for agents and admins only"
                ).dict()

            from app.services.pm_authz import get_accessible_owner_ids

            user_role = get_user_role(user)

            # Get accessible owner IDs
            owner_filter = []
            if user_role != UserRole.admin:
                accessible_owners = await get_accessible_owner_ids(db, actor=user)
                if accessible_owners is not None:
                    owner_filter = list(accessible_owners)
            elif owner_id:
                owner_filter = [owner_id]

            # Count properties
            prop_stmt = select(func.count(Property.id)).where(Property.is_managed == True)
            if owner_filter:
                prop_stmt = prop_stmt.where(Property.owner_id.in_(owner_filter))
            prop_result = await db.execute(prop_stmt)
            total_properties = prop_result.scalar() or 0

            # Count active leases
            lease_stmt = select(func.count(Lease.id)).where(Lease.status == LeaseStatus.active)
            if owner_filter:
                lease_stmt = lease_stmt.where(Lease.owner_id.in_(owner_filter))
            lease_result = await db.execute(lease_stmt)
            active_leases = lease_result.scalar() or 0

            # Calculate occupancy rate
            occupancy_rate = (active_leases / total_properties * 100) if total_properties > 0 else 0

            # Count open maintenance requests
            maint_stmt = (
                select(func.count(MaintenanceRequest.id))
                .join(Property, MaintenanceRequest.property_id == Property.id)
                .where(MaintenanceRequest.request_status == MaintenanceRequestStatus.open)
            )
            if owner_filter:
                maint_stmt = maint_stmt.where(Property.owner_id.in_(owner_filter))
            maint_result = await db.execute(maint_stmt)
            open_maintenance = maint_result.scalar() or 0

            # Count upcoming bookings
            today = datetime.utcnow()
            booking_stmt = (
                select(func.count(Booking.id))
                .join(Property, Booking.property_id == Property.id)
                .where(
                    Booking.check_in_date > today,
                    Booking.booking_status.in_(["confirmed", "pending"])
                )
            )
            if owner_filter:
                booking_stmt = booking_stmt.where(Property.owner_id.in_(owner_filter))
            booking_result = await db.execute(booking_stmt)
            upcoming_bookings = booking_result.scalar() or 0

            # Calculate monthly rent expected
            rent_stmt = select(func.sum(Lease.monthly_rent)).where(Lease.status == LeaseStatus.active)
            if owner_filter:
                rent_stmt = rent_stmt.where(Lease.owner_id.in_(owner_filter))
            rent_result = await db.execute(rent_stmt)
            monthly_rent_expected = float(rent_result.scalar() or 0)

            return MCPResponse.success({
                "metrics": {
                    "total_properties": total_properties,
                    "active_leases": active_leases,
                    "occupancy_rate": round(occupancy_rate, 1),
                    "open_maintenance_requests": open_maintenance,
                    "upcoming_bookings": upcoming_bookings,
                    "monthly_rent_expected": monthly_rent_expected,
                },
                "user_role": user_role.value,
                "scope": "owner" if owner_id else ("agent" if user_role == UserRole.agent else "all"),
            }).dict()
    except AuthRequiredError:
        raise
    except Exception as e:
        logger.error(f"Error in agent.dashboard.overview: {e}", exc_info=True)
        return internal_error_response(f"Failed to get dashboard: {str(e)}")


# ============================================================================
# System Tools
# ============================================================================


@admin_mcp.tool(
    "admin_system_status",
    annotations={
        "title": "Admin System Status",
        "readOnlyHint": True,
        "securitySchemes": MCP_SECURITY_SCHEMES_MIXED,
    },
)
async def admin_system_status() -> Dict[str, Any]:
    """Get admin system status and available features."""
    try:
        auth_status = "unauthenticated"
        user_info = None
        is_authorized = False

        async for db in get_db():
            user = await _get_user(db)
            if user:
                auth_status = "authenticated"
                role = get_user_role(user)
                is_authorized = role in (UserRole.agent, UserRole.admin)
                user_info = {
                    "id": user.id,
                    "role": role.value,
                    "full_name": getattr(user, "full_name", None),
                    "is_authorized": is_authorized,
                }

        return MCPResponse.success({
            "status": "operational",
            "version": "2.0.0",
            "server": "admin",
            "auth": {
                "status": auth_status,
                "user": user_info,
            },
            "access": "granted" if is_authorized else "denied",
            "features": {
                "agent.properties": {
                    "list": True,
                    "get": True,
                    "create_for_owner": True,
                    "verify": True,
                },
                "agent.leases": {
                    "list": True,
                    "create": True,
                    "terminate": True,
                },
                "agent.rent": {
                    "list_due": True,
                    "record_payment": True,
                },
                "agent.maintenance": {
                    "list": True,
                    "update_status": True,
                },
                "agent.bookings": {
                    "list_all": True,
                    "update_status": True,
                },
                "agent.dashboard": {
                    "overview": True,
                },
            },
        }).dict()
    except AuthRequiredError:
        raise
    except Exception as e:
        logger.error(f"Error in admin.system.status: {e}", exc_info=True)
        return internal_error_response(f"Failed to get system status: {str(e)}")
