"""Shared lease tool operations for MCP servers and tool bridge."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import BadRequestException, ConflictException, InsufficientPermissionsError
from app.core.logging import get_logger
from app.mcp.utils import serialize_lease
from app.models.enums import LeaseStatus
from app.models.pm_leases import Lease
from app.models.properties import Property
from app.models.users import User as UserModel
from app.schemas.pagination import encode_cursor, read_offset, trim_offset_lookahead
from app.schemas.user import User as UserSchema
from app.services.pm.occupancy import OCCUPIED_LEASE_STATUSES
from app.services.pm_authz import assert_can_access_property
from app.services.pm_leases import create_lease as create_pm_lease
from app.services.user import get_user_by_id

logger = get_logger(__name__)


def _user_schema(user: UserModel | UserSchema) -> UserSchema:
    return UserSchema.model_validate(user)


async def get_tenant_current_lease(
    db: AsyncSession,
    *,
    tenant_user_id: int,
    viewer: UserModel | UserSchema | None = None,
) -> dict:
    """Get the current active lease for a tenant. ``viewer`` is the caller (the tenant)."""
    stmt = (
        select(Lease)
        .where(
            Lease.tenant_user_id == tenant_user_id,
            Lease.status.in_(OCCUPIED_LEASE_STATUSES),
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

    lease_data = serialize_lease(lease, viewer)
    lease_data["property"] = property_data

    return {"lease": lease_data}


def _lease_scope(
    *,
    owner_id: int | None,
    property_id: int | None,
    accessible_owner_ids: list[int] | None,
) -> list[Any]:
    conditions: list[Any] = []
    if owner_id:
        conditions.append(Lease.owner_id == owner_id)
    if property_id:
        conditions.append(Lease.property_id == property_id)
    if accessible_owner_ids is not None:
        conditions.append(Lease.owner_id.in_(accessible_owner_ids))
    return conditions


async def lease_portfolio_stats(
    db: AsyncSession,
    *,
    owner_id: int | None = None,
    property_id: int | None = None,
    accessible_owner_ids: list[int] | None = None,
) -> dict[str, Any]:
    """Active lease count and monthly rent over every lease in scope, not over one page."""
    conditions = _lease_scope(
        owner_id=owner_id, property_id=property_id, accessible_owner_ids=accessible_owner_ids
    )
    active = Lease.status == LeaseStatus.active
    row = (
        await db.execute(
            select(
                func.count(Lease.id).filter(active),
                func.coalesce(func.sum(Lease.monthly_rent).filter(active), 0),
            ).where(*conditions)
        )
    ).one()
    return {"active_leases": int(row[0] or 0), "total_monthly_rent": round(float(row[1] or 0), 2)}


async def list_leases(
    db: AsyncSession,
    *,
    actor,
    owner_id: int | None = None,
    property_id: int | None = None,
    status: LeaseStatus | None = None,
    cursor_payload: dict | None = None,
    limit: int = 20,
    accessible_owner_ids: list[int] | None = None,
    filters: dict | None = None,
    include_total: bool = False,
) -> dict:
    """One page of leases in scope, with stats over every lease in scope.

    ``leases`` is the page. ``stats`` holds active_leases and total_monthly_rent for the
    whole scope. ``accessible_owner_ids`` is the caller's scope (None = all).
    ``filters`` binds the returned cursor. ``total`` is the count of matching leases
    when ``include_total`` is set, otherwise null.
    """
    limit = min(max(1, limit), 100)
    if cursor_payload is None:
        cursor_payload = {}
    offset = read_offset(cursor_payload)

    conditions = _lease_scope(
        owner_id=owner_id, property_id=property_id, accessible_owner_ids=accessible_owner_ids
    )
    if status:
        try:
            status_filter = Lease.status == LeaseStatus(status.lower())
        except ValueError:
            return {"error": True, "message": f"Invalid status: {status}"}
        conditions.append(status_filter)

    stmt = (
        select(Lease)
        .options(
            selectinload(Lease.property).selectinload(Property.images),
            selectinload(Lease.tenant_user),
        )
        .where(*conditions)
        .order_by(Lease.created_at.desc(), Lease.id.desc())
        .offset(offset)
        .limit(limit + 1)
    )
    leases = list((await db.execute(stmt)).scalars().all())
    page, next_payload = trim_offset_lookahead(leases, limit=limit, offset=offset)

    total = None
    if include_total:
        total = (await db.execute(select(func.count(Lease.id)).where(*conditions))).scalar_one()

    stats = await lease_portfolio_stats(
        db, owner_id=owner_id, property_id=property_id, accessible_owner_ids=accessible_owner_ids
    )
    return {
        "leases": [serialize_lease(lease, actor) for lease in page],
        "stats": stats,
        "total": total,
        "next_cursor": encode_cursor(next_payload, filters) if next_payload else None,
        "has_more": next_payload is not None,
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
    """Create an active lease through the PM lease service, with the same rules as REST.

    Unset payment_due_day and grace_period_days take the managed property values. A
    grace period of 0 is kept. ``terms`` is stored as ``lease_terms.terms``.
    """
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

    try:
        lease = await create_pm_lease(
            db,
            actor=actor_schema,
            owner_id=prop.owner_id,
            property_id=property_id,
            tenant_user_id=tenant_user_id,
            tenant_name=None,
            tenant_phone=None,
            tenant_email=None,
            status=LeaseStatus.active,
            start_date=sd,
            end_date=ed,
            monthly_rent=monthly_rent,
            security_deposit=security_deposit,
            payment_due_day=payment_due_day,
            grace_period_days=grace_period_days,
            lease_terms={"terms": terms} if terms else None,
            special_clauses=notes,
        )
    except (BadRequestException, ConflictException, InsufficientPermissionsError) as e:
        # The service maps a second occupying lease, bad references and missing rights to these.
        return {"error": True, "message": str(e.detail)}
    await db.commit()

    return {
        "message": "Lease created successfully",
        "lease": serialize_lease(lease, actor),
    }
