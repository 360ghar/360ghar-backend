"""Shared dashboard metric computation for MCP servers and tool bridge."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.enums import LeaseStatus, MaintenanceRequestStatus
from app.models.pm_leases import Lease
from app.models.pm_maintenance import MaintenanceRequest
from app.models.properties import Property

logger = get_logger(__name__)


async def compute_dashboard_metrics(
    db: AsyncSession,
    *,
    owner_ids: list[int] | None = None,
    managed_only: bool = True,
) -> dict:
    """Compute dashboard metrics for a set of owners.

    Args:
        owner_ids: If None, compute for all. If empty list, return zeros.
        managed_only: If True, only count managed properties.
    """
    if owner_ids is not None and len(owner_ids) == 0:
        return _empty_dashboard()

    # Property count
    prop_stmt = select(func.count(Property.id))
    if managed_only:
        prop_stmt = prop_stmt.where(Property.is_managed == True)  # noqa: E712
    if owner_ids is not None:
        prop_stmt = prop_stmt.where(Property.owner_id.in_(owner_ids))
    total_properties = (await db.execute(prop_stmt)).scalar() or 0

    # Active leases
    lease_stmt = select(func.count(Lease.id)).where(Lease.status == LeaseStatus.active)
    if owner_ids is not None:
        lease_stmt = lease_stmt.where(Lease.owner_id.in_(owner_ids))
    active_leases = (await db.execute(lease_stmt)).scalar() or 0

    # Occupancy rate
    occupancy_rate = (active_leases / total_properties * 100) if total_properties > 0 else 0.0

    # Open maintenance requests
    maint_stmt = select(func.count(MaintenanceRequest.id)).where(
        MaintenanceRequest.request_status == MaintenanceRequestStatus.open
    )
    if owner_ids is not None:
        maint_stmt = maint_stmt.where(MaintenanceRequest.owner_id.in_(owner_ids))
    open_maintenance = (await db.execute(maint_stmt)).scalar() or 0

    # Expected monthly rent from active leases
    rent_stmt = select(func.sum(Lease.monthly_rent)).where(Lease.status == LeaseStatus.active)
    if owner_ids is not None:
        rent_stmt = rent_stmt.where(Lease.owner_id.in_(owner_ids))
    monthly_rent_expected = float((await db.execute(rent_stmt)).scalar() or 0)

    return {
        "properties": {
            "total": total_properties,
            "occupied": active_leases,
            "vacant": total_properties - active_leases,
        },
        "leases": {
            "active": active_leases,
        },
        "occupancy_rate": round(occupancy_rate, 1),
        "maintenance": {
            "open": open_maintenance,
        },
        "rent": {
            "expected_monthly": monthly_rent_expected,
        },
    }


def _empty_dashboard() -> dict:
    """Return a dashboard with all metrics zeroed."""
    return {
        "properties": {"total": 0, "occupied": 0, "vacant": 0},
        "leases": {"active": 0},
        "occupancy_rate": 0.0,
        "maintenance": {"open": 0},
        "rent": {"expected_monthly": 0.0},
    }
