from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.api_v1.dependencies.auth import get_current_active_user
from app.core.database import get_db
from app.models.agents import Agent
from app.models.enums import UserRole
from app.schemas.pm_assignment import (
    OwnerRMAssignmentCreate,
    OwnerRMAssignmentResponse,
    OwnerRMAssignmentUpdate,
)
from app.schemas.user import User as UserSchema
from app.services.pm_assignments import set_owner_relationship_manager

router = APIRouter()


@router.post("", response_model=OwnerRMAssignmentResponse, summary="Assign RM to owner")
async def create_rm_assignment(
    payload: OwnerRMAssignmentCreate,
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Assign RM to owner."""
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
        actor=current_user,  # type: ignore[arg-type]
    )
    agent = await db.get(Agent, owner.agent_id) if owner.agent_id else None
    return OwnerRMAssignmentResponse(
        owner_user_id=owner.id,
        agent_id=owner.agent_id,
        agent=agent,  # type: ignore[arg-type]
    )


@router.patch("/{owner_user_id}", response_model=OwnerRMAssignmentResponse, summary="Update RM assignment")
async def update_rm_assignment(
    owner_user_id: int,
    payload: OwnerRMAssignmentUpdate,
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Update RM assignment."""
    owner = await set_owner_relationship_manager(
        db,
        owner_user_id=owner_user_id,
        agent_id=payload.agent_id,
        actor=current_user,  # type: ignore[arg-type]
    )
    agent = await db.get(Agent, owner.agent_id) if owner.agent_id else None
    return OwnerRMAssignmentResponse(
        owner_user_id=owner.id,
        agent_id=owner.agent_id,
        agent=agent,  # type: ignore[arg-type]
    )
