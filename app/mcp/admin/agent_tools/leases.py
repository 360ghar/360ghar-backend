from __future__ import annotations

from datetime import datetime
from typing import Any

from app.core.exceptions import (
    InsufficientPermissionsError,
    NotFoundException,
    PropertyNotFoundException,
)
from app.mcp.admin.agent_tools.common import (
    MCP_SECURITY_SCHEMES_MIXED,
    AuthRequiredError,
    MCPErrorCode,
    MCPResponse,
    _get_user,
    _require_agent_or_admin,
    _require_auth,
    admin_mcp,
    get_db,
    get_user_role,
    internal_error_response,
    invalid_input_response,
    logger,
    not_found_response,
    serialize_lease,
    utc_now,
)
from app.models.enums import UserRole


@admin_mcp.tool(
    "agent_leases_list",
    annotations={
        "title": "List Leases",
        "readOnlyHint": True,
        "openWorldHint": False,
        "destructiveHint": False,
        "securitySchemes": MCP_SECURITY_SCHEMES_MIXED,
    },
)
async def agent_leases_list(
    owner_id: int | None = None,
    property_id: int | None = None,
    status: str | None = None,
    page: int = 1,
    limit: int = 20,
) -> dict[str, Any]:
    """List leases for managed properties.

    Args:
        owner_id: Filter by owner
        property_id: Filter by property
        status: Filter by status (draft, active, expired, terminated)
        page: Page number
        limit: Items per page
    """
    try:
        from sqlalchemy import func, select

        from app.models.enums import LeaseStatus
        from app.models.pm_leases import Lease

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
                ).model_dump()

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
                        ).model_dump()
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

            # Count total before applying pagination
            count_stmt = select(func.count()).select_from(stmt.subquery())
            total = (await db.execute(count_stmt)).scalar() or 0

            offset = (page - 1) * limit
            stmt = stmt.order_by(Lease.created_at.desc()).offset(offset).limit(limit)

            result = await db.execute(stmt)
            leases = result.scalars().all()

            items = [serialize_lease(lease) for lease in leases]

            return MCPResponse.success({
                "total": total,
                "page": page,
                "limit": limit,
                "leases": items,
            }).model_dump()
    except AuthRequiredError:
        raise
    except Exception as e:
        logger.error("Error in agent.leases.list: %s", e, exc_info=True)
        return internal_error_response(f"Failed to list leases: {str(e)}")
    return {}

@admin_mcp.tool(
    "agent_leases_create",
    annotations={
        "title": "Create Lease",
        "readOnlyHint": False,
        "destructiveHint": False,
        "openWorldHint": False,
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
    terms: str | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
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
        from app.models.enums import LeaseStatus
        from app.models.pm_leases import Lease

        try:
            start = datetime.fromisoformat(start_date).date()
            end = datetime.fromisoformat(end_date).date()
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
                ).model_dump()

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
                ).model_dump()

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
            }).model_dump()
    except AuthRequiredError:
        raise
    except Exception as e:
        logger.error("Error in agent.leases.create: %s", e, exc_info=True)
        return internal_error_response(f"Failed to create lease: {str(e)}")
    return {}

@admin_mcp.tool(
    "agent_leases_terminate",
    annotations={
        "title": "Terminate Lease",
        "readOnlyHint": False,
        "destructiveHint": True,
        "openWorldHint": False,
        "securitySchemes": MCP_SECURITY_SCHEMES_MIXED,
    },
)
async def agent_leases_terminate(
    lease_id: int,
    reason: str,
    termination_date: str | None = None,
) -> dict[str, Any]:
    """Terminate an active lease.

    Args:
        lease_id: ID of the lease
        reason: Reason for termination
        termination_date: Termination date (ISO-8601, defaults to today)
    """
    try:
        from app.models.enums import LeaseStatus

        term_date = utc_now().date()
        if termination_date:
            try:
                term_date = datetime.fromisoformat(termination_date).date()
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
                ).model_dump()

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
                ).model_dump()

            if lease.status != LeaseStatus.active:
                return MCPResponse.failure(
                    MCPErrorCode.OPERATION_FAILED,
                    f"Lease cannot be terminated (status: {lease.status.value})"
                ).model_dump()

            lease.status = LeaseStatus.terminated
            lease.end_date = term_date
            lease.notes = f"{lease.notes or ''}\nTerminated: {reason}".strip()  # type: ignore[attr-defined]

            await db.flush()
            await db.commit()

            return MCPResponse.success({
                "message": "Lease terminated successfully",
                "lease_id": lease_id,
                "termination_date": term_date.isoformat(),
            }).model_dump()
    except AuthRequiredError:
        raise
    except Exception as e:
        logger.error("Error in agent.leases.terminate: %s", e, exc_info=True)
        return internal_error_response(f"Failed to terminate lease: {str(e)}")
    return {}
