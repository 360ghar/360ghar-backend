from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    AgentNotFoundException,
    InsufficientPermissionsError,
    UserNotFoundException,
)
from app.models.agents import Agent
from app.models.enums import UserRole
from app.models.users import User


async def set_owner_relationship_manager(
    db: AsyncSession,
    *,
    owner_user_id: int,
    agent_id: int | None,
    actor: User,
) -> User:
    """Assign/unassign a Relationship Manager (Agent) to an owner.

    Updated plan: we reuse `users.agent_id` as the owner↔RM assignment.
    """
    if actor.role == UserRole.admin.value:
        pass
    elif actor.role == UserRole.user.value:
        if owner_user_id != actor.id:
            raise InsufficientPermissionsError("Owners can only modify their own RM assignment")
    else:
        raise InsufficientPermissionsError("Only owners or admins can modify RM assignment")

    owner = await db.get(User, owner_user_id)
    if not owner:
        raise UserNotFoundException(detail="Owner not found")

    if agent_id is None:
        owner.agent_id = None
        await db.flush()
        await db.refresh(owner)
        return owner

    agent = await db.get(Agent, agent_id)
    if not agent or not getattr(agent, "is_active", False):
        raise AgentNotFoundException(detail="Agent not found or inactive")

    owner.agent_id = agent_id
    await db.flush()
    await db.refresh(owner)
    return owner

