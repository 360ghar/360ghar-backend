from __future__ import annotations

from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import InsufficientPermissionsError, NotFoundException
from app.models.enums import LeaseStatus, UserRole
from app.models.pm_leases import Lease
from app.models.users import User
from app.services.pm_authz import assert_can_manage_owner_portfolio, get_accessible_owner_ids


async def list_tenants(
    db: AsyncSession,
    *,
    actor: User,
    owner_id: int | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """List tenant users across an owner's (or RM's) accessible portfolio."""
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
        case((Lease.status == LeaseStatus.active, 1), else_=0)
    ).label("active_leases_count")

    stmt = (
        select(
            User.id.label("user_id"),
            User.full_name,
            User.phone,
            User.email,
            active_count_expr,
        )
        .join(Lease, Lease.tenant_user_id == User.id)
        .where(Lease.tenant_user_id.is_not(None))
        .group_by(User.id)
        .order_by(active_count_expr.desc(), User.id.desc())
        .offset(offset)
        .limit(limit)
    )

    if owner_ids is not None:
        stmt = stmt.where(Lease.owner_id.in_(owner_ids))

    rows = (await db.execute(stmt)).all()
    return [
        {
            "user_id": int(r.user_id),
            "full_name": r.full_name,
            "phone": r.phone,
            "email": r.email,
            "active_leases_count": int(r.active_leases_count or 0),
        }
        for r in rows
    ]


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

    tenant = await db.get(User, tenant_user_id)
    if not tenant:
        raise NotFoundException(detail="Tenant user not found")

    lease_stmt = select(Lease).where(Lease.tenant_user_id == tenant_user_id)
    if owner_ids is not None:
        lease_stmt = lease_stmt.where(Lease.owner_id.in_(owner_ids))
    leases = list((await db.execute(lease_stmt.order_by(Lease.created_at.desc()))).scalars().all())

    return {
        "user_id": tenant.id,
        "full_name": tenant.full_name,
        "phone": tenant.phone,
        "email": tenant.email,
        "leases": leases,
    }

