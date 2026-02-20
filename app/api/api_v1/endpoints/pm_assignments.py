from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.api_v1.dependencies.auth import get_current_active_user
from app.core.database import get_db
from app.models.agents import Agent
from app.models.enums import UserRole
from app.models.users import User
from app.schemas.pm_assignment import (
    OwnerRMAssignmentCreate,
    OwnerRMAssignmentResponse,
    OwnerRMAssignmentUpdate,
)
from app.schemas.user import User as UserSchema
from app.services.pm_assignments import set_owner_relationship_manager

router = APIRouter()


@router.post("", response_model=OwnerRMAssignmentResponse)
async def create_rm_assignment(
    payload: OwnerRMAssignmentCreate,
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    owner_user_id = payload.owner_user_id
    if current_user.role == UserRole.user.value:
        owner_user_id = current_user.id
    elif current_user.role == UserRole.admin.value:
        if owner_user_id is None:
            from app.core.exceptions import BadRequestException

            raise BadRequestException(detail="owner_user_id is required for admin")
    else:
        from app.core.exceptions import InsufficientPermissionsError

        raise InsufficientPermissionsError("Access denied")

    owner = await set_owner_relationship_manager(
        db,
        owner_user_id=owner_user_id,
        agent_id=payload.agent_id,
        actor=current_user,
    )
    agent = await db.get(Agent, owner.agent_id) if owner.agent_id else None
    return OwnerRMAssignmentResponse(
        owner_user_id=owner.id,
        agent_id=owner.agent_id,
        agent=agent,
    )


@router.get("", response_model=list[OwnerRMAssignmentResponse])
async def list_rm_assignments(
    owner_id: Optional[int] = Query(None, description="Owner id (admin only)"),
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    if current_user.role == UserRole.user.value:
        owner_id = current_user.id
    elif current_user.role == UserRole.admin.value:
        pass
    else:
        from app.core.exceptions import InsufficientPermissionsError

        raise InsufficientPermissionsError("Access denied")

    stmt = select(User).where(User.agent_id.is_not(None))
    if owner_id is not None:
        stmt = stmt.where(User.id == owner_id)
    res = await db.execute(stmt)
    owners = list(res.scalars().all())

    # Load agents in one query
    agent_ids = {o.agent_id for o in owners if o.agent_id is not None}
    agents_by_id = {}
    if agent_ids:
        agents_res = await db.execute(select(Agent).where(Agent.id.in_(agent_ids)))
        agents_by_id = {a.id: a for a in agents_res.scalars().all()}

    return [
        OwnerRMAssignmentResponse(
            owner_user_id=o.id,
            agent_id=o.agent_id,
            agent=(agents_by_id.get(o.agent_id) if o.agent_id else None),
        )
        for o in owners
    ]


@router.patch("/{owner_user_id}", response_model=OwnerRMAssignmentResponse)
async def update_rm_assignment(
    owner_user_id: int,
    payload: OwnerRMAssignmentUpdate,
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    owner = await set_owner_relationship_manager(
        db,
        owner_user_id=owner_user_id,
        agent_id=payload.agent_id,
        actor=current_user,
    )
    agent = await db.get(Agent, owner.agent_id) if owner.agent_id else None
    return OwnerRMAssignmentResponse(
        owner_user_id=owner.id,
        agent_id=owner.agent_id,
        agent=agent,
    )
