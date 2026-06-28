from __future__ import annotations

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.core.utils import utc_now
from app.models.agents import Agent
from app.models.users import User
from app.schemas.agent import (
    Agent as AgentSchema,
)
from app.schemas.agent import (
    AgentAssignment,
    AgentCreate,
    AgentUpdate,
)
from app.schemas.pagination import keyset_filter, keyset_payload, keyset_sort_value

logger = get_logger(__name__)


async def get_all_agents(db: AsyncSession) -> list[AgentSchema]:
    """Get all agents"""
    stmt = select(Agent)
    result = await db.execute(stmt)
    agents = result.scalars().all()
    return [AgentSchema.model_validate(agent) for agent in agents]

async def get_active_agents(db: AsyncSession) -> list[AgentSchema]:
    """Get all active agents"""
    stmt = select(Agent).where(Agent.is_active)
    result = await db.execute(stmt)
    agents = result.scalars().all()
    return [AgentSchema.model_validate(agent) for agent in agents]

async def get_available_agents(db: AsyncSession) -> list[AgentSchema]:
    """Get all available agents (active and available)"""
    stmt = select(Agent).where(and_(Agent.is_active, Agent.is_available))
    result = await db.execute(stmt)
    agents = result.scalars().all()
    return [AgentSchema.model_validate(agent) for agent in agents]

async def get_available_agents_paginated(
    db: AsyncSession,
    *,
    cursor_payload: dict,
    limit: int = 20,
    with_total: bool = False,
    agent_type: str | None = None,
) -> tuple[list[Agent], dict | None, int | None]:
    """Paginated available agents, optionally filtered by type."""
    stmt = select(Agent).where(and_(Agent.is_active, Agent.is_available))
    if agent_type:
        stmt = stmt.where(Agent.agent_type == agent_type)

    count_total = None
    if with_total:
        count_result = await db.execute(select(func.count()).select_from(stmt.subquery()))
        count_total = count_result.scalar_one()

    predicate = keyset_filter(Agent.created_at, Agent.id, cursor_payload, descending=True)
    if predicate is not None:
        stmt = stmt.where(predicate)
    stmt = stmt.order_by(Agent.created_at.desc(), Agent.id.desc()).limit(limit + 1)
    result = await db.execute(stmt)
    rows = list(result.scalars().all())

    next_payload = None
    if len(rows) > limit:
        rows = rows[:limit]
        next_payload = keyset_payload(keyset_sort_value(rows[-1].created_at), rows[-1].id)

    return rows, next_payload, count_total


async def get_agents_by_type_paginated(
    db: AsyncSession,
    *,
    cursor_payload: dict,
    limit: int = 20,
    with_total: bool = False,
    agent_type: str,
) -> tuple[list[Agent], dict | None, int | None]:
    stmt = select(Agent).where(and_(Agent.is_active, Agent.agent_type == agent_type))

    count_total = None
    if with_total:
        count_result = await db.execute(select(func.count()).select_from(stmt.subquery()))
        count_total = count_result.scalar_one()

    predicate = keyset_filter(Agent.created_at, Agent.id, cursor_payload, descending=True)
    if predicate is not None:
        stmt = stmt.where(predicate)
    stmt = stmt.order_by(Agent.created_at.desc(), Agent.id.desc()).limit(limit + 1)
    result = await db.execute(stmt)
    rows = list(result.scalars().all())

    next_payload = None
    if len(rows) > limit:
        rows = rows[:limit]
        next_payload = keyset_payload(keyset_sort_value(rows[-1].created_at), rows[-1].id)

    return rows, next_payload, count_total


async def get_agents_by_specialization_paginated(
    db: AsyncSession,
    *,
    cursor_payload: dict,
    limit: int = 20,
    with_total: bool = False,
    specialization: str,
) -> tuple[list[Agent], dict | None, int | None]:
    # We don't currently track specialization in DB; return active agents paginated
    stmt = select(Agent).where(Agent.is_active)

    count_total = None
    if with_total:
        count_result = await db.execute(select(func.count()).select_from(stmt.subquery()))
        count_total = count_result.scalar_one()

    predicate = keyset_filter(Agent.created_at, Agent.id, cursor_payload, descending=True)
    if predicate is not None:
        stmt = stmt.where(predicate)
    stmt = stmt.order_by(Agent.created_at.desc(), Agent.id.desc()).limit(limit + 1)
    result = await db.execute(stmt)
    rows = list(result.scalars().all())

    next_payload = None
    if len(rows) > limit:
        rows = rows[:limit]
        next_payload = keyset_payload(keyset_sort_value(rows[-1].created_at), rows[-1].id)

    return rows, next_payload, count_total


async def get_all_agents_paginated(
    db: AsyncSession,
    *,
    cursor_payload: dict,
    limit: int = 20,
    with_total: bool = False,
    include_inactive: bool = False,
) -> tuple[list[Agent], dict | None, int | None]:
    stmt = select(Agent)
    if not include_inactive:
        stmt = stmt.where(Agent.is_active)

    count_total = None
    if with_total:
        count_result = await db.execute(select(func.count()).select_from(stmt.subquery()))
        count_total = count_result.scalar_one()

    predicate = keyset_filter(Agent.created_at, Agent.id, cursor_payload, descending=True)
    if predicate is not None:
        stmt = stmt.where(predicate)
    stmt = stmt.order_by(Agent.created_at.desc(), Agent.id.desc()).limit(limit + 1)
    result = await db.execute(stmt)
    rows = list(result.scalars().all())

    next_payload = None
    if len(rows) > limit:
        rows = rows[:limit]
        next_payload = keyset_payload(keyset_sort_value(rows[-1].created_at), rows[-1].id)

    return rows, next_payload, count_total

async def get_agent_by_id(db: AsyncSession, agent_id: int) -> AgentSchema | None:
    """Get a specific agent by ID"""
    stmt = select(Agent).where(Agent.id == agent_id)
    result = await db.execute(stmt)
    agent = result.scalar_one_or_none()
    return AgentSchema.model_validate(agent) if agent else None


async def create_agent(db: AsyncSession, agent_data: AgentCreate) -> AgentSchema | None:
    """Create a new agent"""
    # Create the agent
    agent_dict = agent_data.model_dump()
    agent_dict["is_active"] = True
    agent_dict["is_available"] = True
    agent_dict["total_users_assigned"] = 0
    agent_dict["user_satisfaction_rating"] = 0.0

    db_agent = Agent(**agent_dict)
    db.add(db_agent)
    await db.flush()
    await db.refresh(db_agent)

    return AgentSchema.model_validate(db_agent)

async def update_agent(db: AsyncSession, agent_id: int, update_data: AgentUpdate) -> AgentSchema | None:
    """Update agent details"""
    stmt = select(Agent).where(Agent.id == agent_id)
    result = await db.execute(stmt)
    agent = result.scalar_one_or_none()

    if not agent:
        return None

    # Only include fields the caller explicitly sent (allows clearing with null)
    update_dict = update_data.model_dump(exclude_unset=True)

    if not update_dict:
        # No valid updates
        return AgentSchema.model_validate(agent)

    for field, value in update_dict.items():
        setattr(agent, field, value)

    await db.flush()
    await db.refresh(agent)
    return AgentSchema.model_validate(agent)

async def delete_agent(db: AsyncSession, agent_id: int) -> bool:
    """Soft delete an agent (set as inactive)"""
    stmt = select(Agent).where(Agent.id == agent_id)
    result = await db.execute(stmt)
    agent = result.scalar_one_or_none()

    if not agent:
        return False

    # Set agent as inactive instead of hard delete
    agent.is_active = False
    agent.is_available = False

    await db.flush()
    return True

async def get_user_agent(db: AsyncSession, user_id: int, auto_assign: bool = True) -> AgentSchema | None:
    """Get the assigned agent for a user, auto-assign if none exists"""
    # Check if user already has an agent
    user_stmt = select(User).where(User.id == user_id)
    user_result = await db.execute(user_stmt)
    user = user_result.scalar_one_or_none()

    if user and user.agent_id:
        agent_stmt = select(Agent).where(Agent.id == user.agent_id)
        agent_result = await db.execute(agent_stmt)
        agent = agent_result.scalar_one_or_none()
        if agent:
            return AgentSchema.model_validate(agent)

    # Auto-assign if requested and no agent exists
    if auto_assign:
        logger.info("Auto-assigning agent for user %s", user_id)
        assignment = await assign_agent_to_user(db, user_id)
        if assignment:
            return assignment.agent

    return None

async def assign_agent_to_user(db: AsyncSession, user_id: int, agent_id: int | None = None) -> AgentAssignment | None:
    """Assign an agent to a user (auto-assign if no agent_id provided)"""
    # Check if user already has an agent
    user_stmt = select(User).where(User.id == user_id)
    user_result = await db.execute(user_stmt)
    user = user_result.scalar_one_or_none()

    if not user:
        logger.warning("User %s not found", user_id)
        return None

    if user.agent_id:
        agent_stmt = select(Agent).where(Agent.id == user.agent_id)
        agent_result = await db.execute(agent_stmt)
        existing_agent = agent_result.scalar_one_or_none()
        if existing_agent:
            agent_schema = AgentSchema.model_validate(existing_agent)
            return AgentAssignment(
                user_id=user_id,
                agent=agent_schema,
                assigned_at=utc_now(),
                assignment_reason="already_assigned"
            )

    # Track whether a specific agent was explicitly requested (before reassignment)
    is_manual = agent_id is not None

    # Determine which agent to assign
    if agent_id:
        # Specific agent requested
        agent_stmt = select(Agent).where(Agent.id == agent_id)
        agent_result = await db.execute(agent_stmt)
        agent = agent_result.scalar_one_or_none()
        if not agent or not agent.is_active or not agent.is_available:
            logger.warning("Requested agent %s is not available", agent_id)
            return None
    else:
        # Auto-assign based on load balancing - get agent with least users
        load_stmt = select(Agent, func.count(User.id).label('user_count')).outerjoin(
            User, Agent.id == User.agent_id
        ).where(
            and_(Agent.is_active, Agent.is_available)
        ).group_by(Agent.id).order_by(func.count(User.id).asc()).limit(1)

        load_result = await db.execute(load_stmt)
        agent_with_count = load_result.first()

        if not agent_with_count:
            logger.warning("No available agents for assignment")
            return None

        agent = agent_with_count[0]
        agent_id = agent.id

    # Assign the agent
    user.agent_id = agent_id

    # Update agent stats
    agent.total_users_assigned = (agent.total_users_assigned or 0) + 1

    await db.flush()
    await db.refresh(agent)

    agent_schema = AgentSchema.model_validate(agent)
    return AgentAssignment(
        user_id=user_id,
        agent=agent_schema,
        assigned_at=utc_now(),
        assignment_reason="manual_assigned" if is_manual else "auto_assigned"
    )

async def get_agents_by_type(db: AsyncSession, agent_type: str) -> list[AgentSchema]:
    """Get agents by type (general, specialist, senior)"""
    stmt = select(Agent).where(
        and_(Agent.is_active, Agent.agent_type == agent_type)
    )
    result = await db.execute(stmt)
    agents = result.scalars().all()
    return [AgentSchema.model_validate(agent) for agent in agents]

async def update_agent_availability(db: AsyncSession, agent_id: int, is_available: bool) -> bool:
    """Update agent availability status"""
    stmt = select(Agent).where(Agent.id == agent_id)
    result = await db.execute(stmt)
    agent = result.scalar_one_or_none()

    if not agent:
        return False

    agent.is_available = is_available
    await db.flush()
    return True
