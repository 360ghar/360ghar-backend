from __future__ import annotations

from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import InsufficientPermissionsError, NotFoundException
from app.models.enums import TenantStatus, UserRole
from app.models.pm_leases import Lease
from app.models.properties import Property
from app.models.users import User
from app.schemas.pagination import offset_payload, read_offset
from app.services.pm.occupancy import OCCUPIED_LEASE_STATUSES
from app.services.pm_authz import assert_can_manage_owner_portfolio, get_accessible_owner_ids

# Contact fields come from the lease the owner typed, never from the user account. An owner can
# link any user id to a lease, so reading the account would expose that user's PII to the owner.


async def list_tenants(
    db: AsyncSession,
    *,
    actor: User,
    owner_id: int | None = None,
    cursor_payload: dict,
    limit: int = 20,
    with_total: bool = False,
) -> tuple[list[dict[str, Any]], dict | None, int | None]:
    """List tenants across an owner's (or RM's) accessible portfolio."""
    owner_ids: list[int] | None = None
    if actor.role == UserRole.user.value:
        owner_ids = [actor.id]
    elif actor.role == UserRole.agent.value:
        if owner_id is not None:
            await assert_can_manage_owner_portfolio(db, actor=actor, owner_id=owner_id)
            owner_ids = [owner_id]
        else:
            owner_ids = list(await get_accessible_owner_ids(db, actor=actor) or [])
    elif actor.role == UserRole.admin.value:
        owner_ids = [owner_id] if owner_id is not None else None
    else:
        raise InsufficientPermissionsError("Not authorized")

    active_count_expr = func.sum(
        case((Lease.status.in_(OCCUPIED_LEASE_STATUSES), 1), else_=0)
    ).label("active_leases_count")

    stmt = (
        select(Lease.tenant_user_id.label("user_id"), active_count_expr)
        .where(Lease.tenant_user_id.is_not(None))
        .group_by(Lease.tenant_user_id)
    )

    if owner_ids is not None:
        stmt = stmt.where(Lease.owner_id.in_(owner_ids))

    count_total: int | None = None
    if with_total:
        count_stmt = select(func.count()).select_from(stmt.subquery())
        count_total = (await db.execute(count_stmt)).scalar_one()

    offset = read_offset(cursor_payload)
    stmt = (
        stmt.order_by(active_count_expr.desc(), Lease.tenant_user_id.desc())
        .offset(offset)
        .limit(limit + 1)
    )

    raw_rows = (await db.execute(stmt)).all()
    next_p = offset_payload(offset + limit) if len(raw_rows) > limit else None
    page_rows = raw_rows[:limit]

    page_ids = [int(r.user_id) for r in page_rows]
    contacts: dict[int, tuple[str | None, str | None, str | None]] = {}
    property_names: dict[int, str | None] = {}
    if page_ids:
        # Newest lease first. The newest lease in scope gives the contact fields. The newest
        # occupying lease gives the property name. Only the caller's own leases are read.
        lease_stmt = (
            select(
                Lease.tenant_user_id,
                Lease.tenant_name,
                Lease.tenant_phone,
                Lease.tenant_email,
                Lease.status,
                Property.title,
            )
            .join(Property, Property.id == Lease.property_id)
            .where(Lease.tenant_user_id.in_(page_ids))
            .order_by(Lease.tenant_user_id, Lease.created_at.desc(), Lease.id.desc())
        )
        if owner_ids is not None:
            lease_stmt = lease_stmt.where(Lease.owner_id.in_(owner_ids))
        for tenant_id, name, phone, email, lease_status, title in (
            await db.execute(lease_stmt)
        ).all():
            tid = int(tenant_id)
            contacts.setdefault(tid, (name, phone, email))
            if lease_status in OCCUPIED_LEASE_STATUSES:
                property_names.setdefault(tid, title)

    items: list[dict[str, Any]] = []
    for r in page_rows:
        tid = int(r.user_id)
        name, phone, email = contacts.get(tid, (None, None, None))
        active_count = int(r.active_leases_count or 0)
        items.append(
            {
                "user_id": tid,
                "full_name": name,
                "phone": phone,
                "email": email,
                "status": TenantStatus.active if active_count > 0 else TenantStatus.vacated,
                "property_name": property_names.get(tid),
                "active_leases_count": active_count,
            }
        )
    return items, next_p, count_total


async def get_tenant_detail(
    db: AsyncSession,
    *,
    actor: User,
    tenant_user_id: int,
    owner_id: int | None = None,
) -> dict[str, Any]:
    # Determine owner scope
    owner_ids: list[int] | None
    if actor.role == UserRole.user.value:
        owner_ids = [actor.id]
    elif actor.role == UserRole.agent.value:
        if owner_id is None:
            raise InsufficientPermissionsError("owner_id is required for agents")
        await assert_can_manage_owner_portfolio(db, actor=actor, owner_id=owner_id)
        owner_ids = [owner_id]
    elif actor.role == UserRole.admin.value:
        owner_ids = [owner_id] if owner_id is not None else None
    else:
        raise InsufficientPermissionsError("Not authorized")

    # A tenant is visible only through a lease in the caller's scope. Otherwise the answer is
    # the same 404 as an unknown id, so ids cannot be probed.
    lease_stmt = select(Lease).where(Lease.tenant_user_id == tenant_user_id)
    if owner_ids is not None:
        lease_stmt = lease_stmt.where(Lease.owner_id.in_(owner_ids))
    leases = list(
        (await db.execute(lease_stmt.order_by(Lease.created_at.desc(), Lease.id.desc())))
        .scalars()
        .all()
    )
    if not leases:
        raise NotFoundException(detail="Tenant user not found")

    newest = leases[0]
    return {
        "user_id": tenant_user_id,
        "full_name": newest.tenant_name,
        "phone": newest.tenant_phone,
        "email": newest.tenant_email,
        "leases": leases,
    }
