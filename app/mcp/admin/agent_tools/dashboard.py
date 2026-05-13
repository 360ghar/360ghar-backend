from __future__ import annotations

from typing import Any

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
    logger,
    utc_now,
)
from app.models.enums import UserRole


@admin_mcp.tool(
    "agent_dashboard_overview",
    annotations={
        "title": "Agent Dashboard Overview",
        "readOnlyHint": True,
        "openWorldHint": False,
        "destructiveHint": False,
        "securitySchemes": MCP_SECURITY_SCHEMES_MIXED,
    },
)
async def agent_dashboard_overview(
    owner_id: int | None = None,
) -> dict[str, Any]:
    """Get dashboard overview with key metrics.

    Args:
        owner_id: Filter by specific owner (optional for admins)
    """
    try:
        from sqlalchemy import func, select

        from app.models.bookings import Booking
        from app.models.enums import LeaseStatus, MaintenanceRequestStatus
        from app.models.pm_leases import Lease
        from app.models.pm_maintenance import MaintenanceRequest
        from app.models.properties import Property

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
                ).model_dump()

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
            prop_stmt = select(func.count(Property.id)).where(Property.is_managed)
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
            today = utc_now()
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
            }).model_dump()
    except AuthRequiredError:
        raise
    except Exception as e:
        logger.error("Error in agent.dashboard.overview: %s", e, exc_info=True)
        return internal_error_response(f"Failed to get dashboard: {str(e)}")
    return {}
