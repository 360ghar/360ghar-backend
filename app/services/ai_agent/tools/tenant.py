"""
Tenant tools — lease, rent, and maintenance tools for tenants.

These tools allow tenants to view their lease, check rent dues/payment
history, and submit/list maintenance requests.
"""
from __future__ import annotations

from typing import Any

from pydantic_ai import RunContext
from sqlalchemy import select

from app.core.logging import get_logger
from app.mcp.utils import (
    serialize_lease,
    serialize_maintenance_request,
    serialize_property_basic,
)
from app.services.ai_agent.tools.helpers import AgentDeps

logger = get_logger(__name__)


async def tenant_lease_current(
    ctx: RunContext[AgentDeps],
) -> dict[str, Any]:
    """Get the current active lease for the tenant."""
    from app.models.enums import LeaseStatus
    from app.models.pm_leases import Lease
    from app.models.properties import Property

    db, user = ctx.deps.db, ctx.deps.user
    stmt = (
        select(Lease)
        .where(Lease.tenant_user_id == user.id, Lease.status == LeaseStatus.active)
        .order_by(Lease.created_at.desc())
        .limit(1)
    )
    lease = (await db.execute(stmt)).scalar_one_or_none()
    if not lease:
        return {"lease": None, "message": "No active lease found."}

    prop = (await db.execute(
        select(Property).where(Property.id == lease.property_id)
    )).scalar_one_or_none()

    lease_data = serialize_lease(lease)
    if prop:
        lease_data["property"] = serialize_property_basic(prop)
    return {"lease": lease_data}


async def tenant_rent_history(
    ctx: RunContext[AgentDeps],
    page: int = 1,
    limit: int = 20,
) -> dict[str, Any]:
    """Get rent payment history for the tenant."""
    from app.models.pm_finance import RentPayment
    from app.models.pm_leases import Lease

    limit = min(max(1, limit), 100)
    db, user = ctx.deps.db, ctx.deps.user

    lease_ids = [
        r[0] for r in (await db.execute(
            select(Lease.id).where(Lease.tenant_user_id == user.id)
        )).all()
    ]
    if not lease_ids:
        return {"payments": [], "total": 0, "total_collected": 0, "page": page}

    stmt = (
        select(RentPayment)
        .where(RentPayment.lease_id.in_(lease_ids))
        .order_by(RentPayment.paid_at.desc())
        .offset((page - 1) * limit)
        .limit(limit)
    )
    payments = (await db.execute(stmt)).scalars().all()
    items = [
        {
            "id": p.id,
            "amount": float(p.amount_paid or 0),
            "payment_date": p.paid_at.isoformat() if p.paid_at else None,
            "payment_method": p.payment_method,
            "transaction_id": p.reference,
        }
        for p in payments
    ]
    return {
        "payments": items,
        "total": len(items),
        "total_collected": sum(p["amount"] for p in items),
        "page": page,
    }


async def tenant_maintenance_create(
    ctx: RunContext[AgentDeps],
    property_id: int,
    title: str,
    description: str,
    category: str,
    priority: str = "medium",
) -> dict[str, Any]:
    """Submit a maintenance request for a property the user is renting."""
    from app.models.enums import (
        LeaseStatus,
        MaintenanceCategory,
        MaintenanceRequestStatus,
        MaintenanceUrgency,
    )
    from app.models.pm_leases import Lease
    from app.models.pm_maintenance import MaintenanceRequest

    db, user = ctx.deps.db, ctx.deps.user
    cat = MaintenanceCategory(category.lower())
    urgency_map = {
        "low": MaintenanceUrgency.low, "medium": MaintenanceUrgency.medium,
        "high": MaintenanceUrgency.high, "urgent": MaintenanceUrgency.emergency,
        "emergency": MaintenanceUrgency.emergency,
    }
    urgency = urgency_map.get(priority.lower().strip())
    if urgency is None:
        return {"error": True, "message": f"Invalid priority: {priority}"}

    lease = (await db.execute(
        select(Lease).where(
            Lease.property_id == property_id,
            Lease.tenant_user_id == user.id,
            Lease.status == LeaseStatus.active,
        )
    )).scalar_one_or_none()
    if not lease:
        return {"error": True, "message": "You do not have an active lease for this property."}

    request = MaintenanceRequest(
        property_id=property_id, lease_id=lease.id, owner_id=lease.owner_id,
        tenant_user_id=user.id, title=title, description=description,
        category=cat, urgency=urgency, priority=priority.lower().strip(),
        request_status=MaintenanceRequestStatus.open,
    )
    db.add(request)
    await db.flush()
    await db.refresh(request)
    await db.commit()
    return {"request": serialize_maintenance_request(request)}


async def tenant_maintenance_list(
    ctx: RunContext[AgentDeps],
    page: int = 1,
    limit: int = 20,
    status: str | None = None,
) -> dict[str, Any]:
    """List maintenance requests submitted by the tenant."""
    from app.models.enums import MaintenanceRequestStatus, WorkOrderStatus
    from app.models.pm_maintenance import MaintenanceRequest

    limit = min(max(1, limit), 100)
    db, user = ctx.deps.db, ctx.deps.user

    stmt = select(MaintenanceRequest).where(MaintenanceRequest.tenant_user_id == user.id)
    if status:
        sn = status.lower().strip()
        filter_map = {
            "open": MaintenanceRequest.request_status == MaintenanceRequestStatus.open,
            "in_progress": MaintenanceRequest.work_order_status == WorkOrderStatus.in_progress,
            "scheduled": MaintenanceRequest.scheduled_for.is_not(None),
            "completed": MaintenanceRequest.completed_at.is_not(None),
            "cancelled": MaintenanceRequest.work_order_status == WorkOrderStatus.cancelled,
        }
        if sn in filter_map:
            stmt = stmt.where(filter_map[sn])
        else:
            return {"error": True, "message": f"Invalid status: {status}"}

    stmt = stmt.order_by(MaintenanceRequest.created_at.desc()).offset((page - 1) * limit).limit(limit)
    items = [serialize_maintenance_request(r) for r in (await db.execute(stmt)).scalars().all()]
    return {"items": items, "total": len(items), "page": page}
