from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.agents import Agent
from app.models.users import User
from app.schemas.agent import (
    Agent as AgentSchema,
)
from app.schemas.agent import (
    AgentStats,
    AgentSystemStats,
    AgentWithStats,
    AgentWorkload,
)
from app.schemas.pagination import offset_payload, read_offset
from app.services.agent.interactions import get_daily_interactions, get_weekly_interactions

logger = get_logger(__name__)


async def get_agent_with_stats(db: AsyncSession, agent_id: int) -> AgentWithStats | None:
    """Get agent with performance statistics"""
    stmt = select(Agent).where(Agent.id == agent_id)
    result = await db.execute(stmt)
    agent = result.scalar_one_or_none()

    if not agent:
        return None

    # Get current active users count
    count_stmt = select(func.count(User.id)).where(User.agent_id == agent_id)
    count_result = await db.execute(count_stmt)
    current_users = int(count_result.scalar() or 0)

    # Get real interaction counts
    daily_interactions = await get_daily_interactions(db, agent_id)
    weekly_interactions = await get_weekly_interactions(db, agent_id)

    stats = AgentStats(
        total_users_assigned=agent.total_users_assigned or 0,
        user_satisfaction_rating=float(agent.user_satisfaction_rating or 0.0),
        active_conversations=current_users,
        daily_interactions=daily_interactions,
        weekly_interactions=weekly_interactions,
        efficiency_score=_calculate_efficiency_score(agent, current_users)
    )

    # Validate from the ORM object directly (from_attributes=True handles it)
    # instead of agent.__dict__ which includes _sa_instance_state and
    # unloaded relationship proxies that can crash Pydantic validation.
    agent_schema = AgentSchema.model_validate(agent)
    return AgentWithStats(
        **agent_schema.model_dump(),
        stats=stats
    )


async def get_workload_distribution(db: AsyncSession) -> list[AgentWorkload]:
    """Get workload distribution across all active agents"""
    stmt = select(
        Agent,
        func.count(User.id).label('current_users')
    ).outerjoin(
        User, Agent.id == User.agent_id
    ).where(
        Agent.is_active
    ).group_by(Agent.id)

    result = await db.execute(stmt)
    agent_workloads = result.all()

    workload = []
    for agent, current_users in agent_workloads:
        max_users = 50  # Default max users
        utilization = (current_users / max_users * 100) if max_users > 0 else 0

        workload.append(AgentWorkload(
            agent_id=agent.id,
            agent_name=agent.name,
            current_users=current_users,
            utilization_percentage=round(utilization, 2),
            is_available=agent.is_available,
            queue_length=max(0, current_users - max_users) if current_users > max_users else 0
        ))

    return workload


async def get_workload_distribution_paginated(
    db: AsyncSession,
    *,
    cursor_payload: dict | None = None,
    limit: int = 20,
    with_total: bool = False,
) -> tuple[list[AgentWorkload], dict | None, int | None]:
    """Cursor-paginated workload distribution across all active agents."""
    if cursor_payload is None:
        cursor_payload = {}
    offset = read_offset(cursor_payload)

    total: int | None = None
    if with_total:
        total = (
            await db.execute(select(func.count(Agent.id)).where(Agent.is_active))
        ).scalar_one()

    stmt = (
        select(
            Agent,
            func.count(User.id).label("current_users"),
        )
        .outerjoin(User, Agent.id == User.agent_id)
        .where(Agent.is_active)
        .group_by(Agent.id)
        .offset(offset)
        .limit(limit + 1)
    )
    result = await db.execute(stmt)
    agent_workloads = result.all()

    has_more = len(agent_workloads) > limit
    agent_workloads = agent_workloads[:limit]
    next_payload = offset_payload(offset + limit) if has_more else None

    workload: list[AgentWorkload] = []
    for agent, current_users in agent_workloads:
        max_users = 50  # Default max users
        utilization = (current_users / max_users * 100) if max_users > 0 else 0
        workload.append(
            AgentWorkload(
                agent_id=agent.id,
                agent_name=agent.name,
                current_users=current_users,
                utilization_percentage=round(utilization, 2),
                is_available=agent.is_available,
                queue_length=max(0, current_users - max_users) if current_users > max_users else 0,
            )
        )
    return workload, next_payload, total


async def get_system_stats(db: AsyncSession) -> AgentSystemStats:
    """Get overall agent system statistics"""
    # Get all agents count
    stmt = select(func.count(Agent.id))
    result = await db.execute(stmt)
    total_agents = result.scalar() or 0

    # Get active agents count
    stmt = select(func.count(Agent.id)).where(Agent.is_active)
    result = await db.execute(stmt)
    active_agents = result.scalar() or 0

    # Get total users served
    stmt = select(func.sum(Agent.total_users_assigned)).where(Agent.is_active)
    result = await db.execute(stmt)
    total_users_served = result.scalar() or 0

    # Get average stats
    stmt = select(
        func.avg(Agent.user_satisfaction_rating)
    ).where(Agent.is_active)
    result = await db.execute(stmt)
    avg_satisfaction = result.scalar() or 0

    # Count agents by type
    type_stmt = select(Agent.agent_type, func.count(Agent.id)).where(
        Agent.is_active
    ).group_by(Agent.agent_type)
    result = await db.execute(type_stmt)
    agents_by_type: dict[str, int] = {}
    for at, count in result.all():
        agents_by_type[at.value] = count

    # Get workload distribution
    workload = await get_workload_distribution(db)

    return AgentSystemStats(
        total_agents=total_agents,
        active_agents=active_agents,
        total_users_served=int(total_users_served),
        system_satisfaction_score=float(avg_satisfaction or 0),
        agents_by_type=agents_by_type,
        load_distribution=workload
    )


def _calculate_efficiency_score(agent: Agent, current_users: int) -> float:
    """Calculate agent efficiency score based on various metrics"""
    try:
        satisfaction = float(agent.user_satisfaction_rating or 0.0)
        max_users = 50  # Default max users
        utilization = (current_users / max_users * 100) if max_users > 0 else 0

        # Default response score since we don't track response time anymore
        response_score = 75  # Assume average performance

        # Satisfaction score (0-5 scale, convert to 0-100)
        satisfaction_score = (satisfaction / 5.0) * 100 if satisfaction > 0 else 50

        # Utilization score (optimal around 70-80%)
        if utilization <= 80:
            utilization_score = utilization * 1.25  # Reward good utilization
        else:
            utilization_score = max(0, 100 - (utilization - 80) * 2)  # Penalize overload

        # Weighted average
        efficiency = (response_score * 0.3 + satisfaction_score * 0.4 + utilization_score * 0.3)
        return round(efficiency, 2)
    except Exception:
        logger.warning("Failed to calculate efficiency score for agent %s", agent.id, exc_info=True)
        return 50.0  # Default middle score
