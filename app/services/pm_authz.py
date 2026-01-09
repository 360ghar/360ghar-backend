from __future__ import annotations

from typing import Optional, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import (
    InsufficientPermissionsError,
    NotFoundException,
    PropertyNotFoundException,
    UserNotFoundException,
)
from app.models.enums import LeaseStatus, UserRole
from app.models.pm_leases import Lease
from app.models.properties import Property
from app.models.users import User


def _get_actor_role(actor: User) -> UserRole:
    try:
        return UserRole(actor.role)
    except ValueError:
        return UserRole.user


async def assert_can_manage_owner_portfolio(
    db: AsyncSession, *, actor: User, owner_id: int
) -> None:
    """Assert the actor can manage an owner's portfolio (PM scope)."""
    role = _get_actor_role(actor)
    if role == UserRole.admin:
        return
    if role == UserRole.agent:
        if actor.agent_id is None:
            raise InsufficientPermissionsError("Agent is not linked to an agent profile")
        owner = await db.get(User, owner_id)
        if not owner:
            raise UserNotFoundException(detail="Owner not found")
        if owner.agent_id != actor.agent_id:
            raise InsufficientPermissionsError(
                "Agent not authorized for this owner",
                owner_id=owner_id,
                agent_id=actor.agent_id,
            )
        return

    # Regular user: must be the owner themselves
    if owner_id != actor.id:
        raise InsufficientPermissionsError(
            "Not authorized for this owner",
            owner_id=owner_id,
            actor_id=actor.id,
        )


async def assert_can_access_property(
    db: AsyncSession,
    *,
    actor: User,
    property_id: int,
    allow_tenant: bool = False,
) -> Property:
    """Assert the actor can access a property in PM context.

    - Owners can access their properties
    - Agents can access properties of owners assigned to them (users.agent_id)
    - Tenants (if allow_tenant=True) can access properties they have an active lease for
    """
    stmt = (
        select(Property)
        .options(selectinload(Property.owner), selectinload(Property.images))
        .where(Property.id == property_id)
    )
    res = await db.execute(stmt)
    prop = res.scalar_one_or_none()
    if not prop:
        raise PropertyNotFoundException(detail="Property not found")

    role = _get_actor_role(actor)
    if role == UserRole.admin:
        return prop

    if prop.owner_id == actor.id:
        return prop

    if role == UserRole.agent:
        if actor.agent_id is None:
            raise InsufficientPermissionsError("Agent is not linked to an agent profile")
        owner = getattr(prop, "owner", None)
        if not owner or owner.agent_id != actor.agent_id:
            raise InsufficientPermissionsError("Agent not authorized for this property")
        return prop

    if allow_tenant:
        # Tenant access is granted via active lease.
        stmt_lease = select(Lease.id).where(
            Lease.property_id == property_id,
            Lease.tenant_user_id == actor.id,
            Lease.status == LeaseStatus.active,
        )
        lease_res = await db.execute(stmt_lease)
        if lease_res.scalar_one_or_none() is not None:
            return prop

    raise InsufficientPermissionsError("Not authorized for this property")


async def assert_can_access_lease(
    db: AsyncSession,
    *,
    actor: User,
    lease_id: int,
) -> Lease:
    """Assert the actor can access a lease."""
    stmt = (
        select(Lease)
        .options(
            selectinload(Lease.property).selectinload(Property.images),
            selectinload(Lease.tenant_user),
        )
        .where(Lease.id == lease_id)
    )
    res = await db.execute(stmt)
    lease = res.scalar_one_or_none()
    if not lease:
        raise NotFoundException(detail="Lease not found")

    role = _get_actor_role(actor)
    if role == UserRole.admin:
        return lease

    if lease.owner_id == actor.id:
        return lease

    if role == UserRole.agent:
        if actor.agent_id is None:
            raise InsufficientPermissionsError("Agent is not linked to an agent profile")
        owner = await db.get(User, lease.owner_id)
        if not owner:
            raise UserNotFoundException(detail="Owner not found")
        if owner.agent_id != actor.agent_id:
            raise InsufficientPermissionsError("Agent not authorized for this lease")
        return lease

    # Tenant access
    if lease.tenant_user_id == actor.id:
        return lease

    raise InsufficientPermissionsError("Not authorized for this lease")


async def get_accessible_owner_ids(db: AsyncSession, *, actor: User) -> Optional[Sequence[int]]:
    """Return owner ids the actor can access for PM list endpoints.

    - admin: None (no filtering)
    - agent: list of owners assigned to their agent_id
    - user: [actor.id]
    """
    role = _get_actor_role(actor)
    if role == UserRole.admin:
        return None
    if role == UserRole.agent:
        if actor.agent_id is None:
            return []
        res = await db.execute(select(User.id).where(User.agent_id == actor.agent_id))
        return [int(r[0]) for r in res.all()]
    return [actor.id]

