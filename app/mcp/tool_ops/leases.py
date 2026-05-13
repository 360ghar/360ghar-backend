"""Shared lease tool operations for MCP servers and tool bridge."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.mcp.utils import serialize_lease
from app.models.enums import LeaseStatus
from app.models.pm_leases import Lease
from app.models.properties import Property
from app.schemas.user import User as UserSchema
from app.services.pm_authz import assert_can_access_lease, assert_can_access_property
from app.services.user import get_user_by_id

logger = get_logger(__name__)


def _user_schema(user) -> UserSchema:
    return UserSchema.model_validate(user)


async def get_tenant_current_lease(
    db: AsyncSession,
    *,
    tenant_user_id: int,
) -> dict:
    """Get the current active lease for a tenant."""
    stmt = (
        select(Lease)
        .where(
            Lease.tenant_user_id == tenant_user_id,
            Lease.status == LeaseStatus.active,
        )
        .order_by(Lease.created_at.desc())
        .limit(1)
    )
    result = await db.execute(stmt)
    lease = result.scalar_one_or_none()

    if not lease:
        return {"lease": None, "message": "No active lease found."}

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

    return {"lease": lease_data}


async def list_leases(
    db: AsyncSession,
    *,
    actor,
    owner_id: int | None = None,
    property_id: int | None = None,
    status: str | None = None,
    page: int = 1,
    limit: int = 20,
    accessible_owner_ids: list[int] | None = None,
) -> dict:
    """List leases with optional filters."""
    limit = min(max(1, limit), 100)

    stmt = select(Lease)

    if owner_id:
        stmt = stmt.where(Lease.owner_id == owner_id)
    if property_id:
        stmt = stmt.where(Lease.property_id == property_id)
    if status:
        try:
            lease_status = LeaseStatus(status.lower())
            stmt = stmt.where(Lease.status == lease_status)
        except ValueError:
            return {"error": True, "message": f"Invalid status: {status}"}

    if accessible_owner_ids is not None:
        stmt = stmt.where(Lease.owner_id.in_(accessible_owner_ids))

    stmt = stmt.order_by(Lease.created_at.desc()).offset((page - 1) * limit).limit(limit)

    result = await db.execute(stmt)
    leases = result.scalars().all()

    items = [serialize_lease(lease) for lease in leases]

    return {
        "items": items,
        "total": len(items),
        "page": page,
        "limit": limit,
    }


async def create_lease(
    db: AsyncSession,
    *,
    actor,
    property_id: int,
    tenant_user_id: int,
    start_date: str,
    end_date: str,
    monthly_rent: float,
    security_deposit: float = 0,
    payment_due_day: int | None = None,
    grace_period_days: int | None = None,
    terms: str | None = None,
    notes: str | None = None,
) -> dict:
    """Create a new lease agreement."""
    actor_schema = _user_schema(actor)

    # Verify property access
    try:
        prop = await assert_can_access_property(db, actor=actor_schema, property_id=property_id)
    except Exception as e:
        return {"error": True, "message": str(e)}

    # Verify tenant exists
    tenant = await get_user_by_id(db, tenant_user_id)
    if not tenant:
        return {"error": True, "message": f"Tenant user {tenant_user_id} not found."}

    # Parse dates
    try:
        sd = datetime.fromisoformat(start_date).date()
        ed = datetime.fromisoformat(end_date).date()
    except (ValueError, TypeError):
        return {"error": True, "message": "Invalid date format. Use ISO-8601."}

    if ed <= sd:
        return {"error": True, "message": "End date must be after start date."}

    lease = Lease(
        property_id=property_id,
        owner_id=prop.owner_id,
        tenant_user_id=tenant_user_id,
        start_date=sd,
        end_date=ed,
        monthly_rent=monthly_rent,
        security_deposit=security_deposit,
        payment_due_day=payment_due_day or 1,
        grace_period_days=grace_period_days or 5,
        lease_terms=terms,
        special_clauses=notes,
        status=LeaseStatus.active,
    )
    db.add(lease)
    await db.flush()
    await db.refresh(lease)
    await db.commit()

    return {
        "message": "Lease created successfully",
        "lease": serialize_lease(lease),
    }


async def terminate_lease(
    db: AsyncSession,
    *,
    actor,
    lease_id: int,
    reason: str,
    termination_date: str | None = None,
) -> dict:
    """Terminate an active lease."""
    actor_schema = _user_schema(actor)

    try:
        lease = await assert_can_access_lease(db, actor=actor_schema, lease_id=lease_id)
    except Exception as e:
        return {"error": True, "message": str(e)}

    if lease.status != LeaseStatus.active:
        return {
            "error": True,
            "message": f"Cannot terminate lease with status: {lease.status.value}",
        }

    lease.status = LeaseStatus.terminated

    if termination_date:
        try:
            td = datetime.fromisoformat(termination_date).date()
            lease.end_date = td
        except (ValueError, TypeError):
            pass

    existing_notes = getattr(lease, "special_clauses", "") or ""
    lease.special_clauses = f"{existing_notes}\nTerminated: {reason}".strip()

    await db.flush()
    await db.commit()

    return {
        "message": "Lease terminated successfully",
        "lease": serialize_lease(lease),
    }
