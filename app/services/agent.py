from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_
from typing import Optional, List, Dict, Any
from app.models.agents import Agent, AgentInteraction
from app.models.users import User
from app.models.properties import Visit
from app.schemas.agent import (
    Agent as AgentSchema,
    AgentCreate,
    AgentUpdate,
    AgentAssignment,
    AgentStats,
    AgentWithStats,
    AgentWorkload,
    AgentSystemStats
)
from datetime import datetime, timedelta
from app.core.logging import get_logger

logger = get_logger(__name__)


async def get_daily_interactions(db: AsyncSession, agent_id: int) -> int:
    """Get the count of interactions for an agent today."""
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    stmt = (
        select(func.count(AgentInteraction.id))
        .where(AgentInteraction.agent_id == agent_id)
        .where(AgentInteraction.created_at >= today_start)
    )
    result = await db.execute(stmt)
    return result.scalar() or 0


async def get_weekly_interactions(db: AsyncSession, agent_id: int) -> int:
    """Get the count of interactions for an agent in the last 7 days."""
    week_start = datetime.utcnow() - timedelta(days=7)
    stmt = (
        select(func.count(AgentInteraction.id))
        .where(AgentInteraction.agent_id == agent_id)
        .where(AgentInteraction.created_at >= week_start)
    )
    result = await db.execute(stmt)
    return result.scalar() or 0


async def get_all_agents(db: AsyncSession) -> List[AgentSchema]:
    """Get all agents"""
    stmt = select(Agent)
    result = await db.execute(stmt)
    agents = result.scalars().all()
    return [AgentSchema.model_validate(agent.__dict__) for agent in agents]

async def get_active_agents(db: AsyncSession) -> List[AgentSchema]:
    """Get all active agents"""
    stmt = select(Agent).where(Agent.is_active == True)
    result = await db.execute(stmt)
    agents = result.scalars().all()
    return [AgentSchema.model_validate(agent.__dict__) for agent in agents]

async def get_available_agents(db: AsyncSession) -> List[AgentSchema]:
    """Get all available agents (active and available)"""
    stmt = select(Agent).where(and_(Agent.is_active == True, Agent.is_available == True))
    result = await db.execute(stmt)
    agents = result.scalars().all()
    return [AgentSchema.model_validate(agent.__dict__) for agent in agents]

async def _paginate_agents(
    db: AsyncSession,
    base_stmt,
    page: int = 1,
    limit: int = 20,
):
    offset = (page - 1) * limit
    # Page rows
    page_stmt = base_stmt.offset(offset).limit(limit)
    result = await db.execute(page_stmt)
    rows = result.scalars().all()
    items = [AgentSchema.model_validate(r.__dict__) for r in rows]

    # Total count
    count_stmt = base_stmt.with_only_columns(func.count(Agent.id)).order_by(None)
    count_result = await db.execute(count_stmt)
    total = int(count_result.scalar() or 0)

    total_pages = (total + limit - 1) // limit if limit else 1
    has_next = page < total_pages
    has_prev = page > 1 and total > 0

    return {
        "items": items,
        "total": total,
        "page": page,
        "limit": limit,
        "total_pages": total_pages,
        "has_next": has_next,
        "has_prev": has_prev,
    }

async def get_available_agents_paginated(
    db: AsyncSession,
    *,
    page: int = 1,
    limit: int = 20,
    agent_type: Optional[str] = None,
) -> Dict[str, Any]:
    """Paginated available agents, optionally filtered by type."""
    stmt = select(Agent).where(and_(Agent.is_active == True, Agent.is_available == True))
    if agent_type:
        stmt = stmt.where(Agent.agent_type == agent_type)
    stmt = stmt.order_by(Agent.id.desc())
    return await _paginate_agents(db, stmt, page, limit)

async def get_agents_by_type_paginated(
    db: AsyncSession,
    *,
    page: int = 1,
    limit: int = 20,
    agent_type: str,
) -> Dict[str, Any]:
    stmt = select(Agent).where(and_(Agent.is_active == True, Agent.agent_type == agent_type)).order_by(Agent.id.desc())
    return await _paginate_agents(db, stmt, page, limit)

async def get_agents_by_specialization_paginated(
    db: AsyncSession,
    *,
    page: int = 1,
    limit: int = 20,
    specialization: str,
) -> Dict[str, Any]:
    # We don't currently track specialization in DB; return active agents paginated
    stmt = select(Agent).where(Agent.is_active == True).order_by(Agent.id.desc())
    return await _paginate_agents(db, stmt, page, limit)

async def get_all_agents_paginated(
    db: AsyncSession,
    *,
    page: int = 1,
    limit: int = 20,
    include_inactive: bool = False,
) -> Dict[str, Any]:
    stmt = select(Agent)
    if not include_inactive:
        stmt = stmt.where(Agent.is_active == True)
    stmt = stmt.order_by(Agent.id.desc())
    return await _paginate_agents(db, stmt, page, limit)

async def get_agent_by_id(db: AsyncSession, agent_id: int) -> Optional[AgentSchema]:
    """Get a specific agent by ID"""
    stmt = select(Agent).where(Agent.id == agent_id)
    result = await db.execute(stmt)
    agent = result.scalar_one_or_none()
    return AgentSchema.model_validate(agent.__dict__) if agent else None


async def create_agent(db: AsyncSession, agent_data: AgentCreate) -> Optional[AgentSchema]:
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
    
    return AgentSchema.model_validate(db_agent.__dict__)

async def update_agent(db: AsyncSession, agent_id: int, update_data: AgentUpdate) -> Optional[AgentSchema]:
    """Update agent details"""
    stmt = select(Agent).where(Agent.id == agent_id)
    result = await db.execute(stmt)
    agent = result.scalar_one_or_none()
    
    if not agent:
        return None
    
    # Filter out None values
    update_dict = {k: v for k, v in update_data.model_dump().items() if v is not None}
    
    if not update_dict:
        # No valid updates
        return AgentSchema.model_validate(agent.__dict__)
    
    for field, value in update_dict.items():
        setattr(agent, field, value)
    
    await db.flush()
    await db.refresh(agent)
    return AgentSchema.model_validate(agent.__dict__)

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

async def get_user_agent(db: AsyncSession, user_id: int, auto_assign: bool = True) -> Optional[AgentSchema]:
    """Get the assigned agent for a user, auto-assign if none exists"""
    # Check if user already has an agent
    stmt = select(User).where(User.id == user_id)
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()
    
    if user and user.agent_id:
        stmt = select(Agent).where(Agent.id == user.agent_id)
        result = await db.execute(stmt)
        agent = result.scalar_one_or_none()
        if agent:
            return AgentSchema.model_validate(agent.__dict__)
    
    # Auto-assign if requested and no agent exists
    if auto_assign:
        logger.info(f"Auto-assigning agent for user {user_id}")
        assignment = await assign_agent_to_user(db, user_id)
        if assignment:
            return assignment.agent
    
    return None

async def assign_agent_to_user(db: AsyncSession, user_id: int, agent_id: Optional[int] = None) -> Optional[AgentAssignment]:
    """Assign an agent to a user (auto-assign if no agent_id provided)"""
    # Check if user already has an agent
    stmt = select(User).where(User.id == user_id)
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()
    
    if not user:
        logger.warning(f"User {user_id} not found")
        return None
    
    if user.agent_id:
        stmt = select(Agent).where(Agent.id == user.agent_id)
        result = await db.execute(stmt)
        existing_agent = result.scalar_one_or_none()
        if existing_agent:
            agent_schema = AgentSchema.model_validate(existing_agent.__dict__)
            return AgentAssignment(
                user_id=user_id,
                agent=agent_schema,
                assigned_at=datetime.utcnow(),
                assignment_reason="already_assigned"
            )
    
    # Determine which agent to assign
    if agent_id:
        # Specific agent requested
        stmt = select(Agent).where(Agent.id == agent_id)
        result = await db.execute(stmt)
        agent = result.scalar_one_or_none()
        if not agent or not agent.is_active or not agent.is_available:
            logger.warning(f"Requested agent {agent_id} is not available")
            return None
    else:
        # Auto-assign based on load balancing - get agent with least users
        stmt = select(Agent, func.count(User.id).label('user_count')).outerjoin(
            User, Agent.id == User.agent_id
        ).where(
            and_(Agent.is_active == True, Agent.is_available == True)
        ).group_by(Agent.id).order_by(func.count(User.id).asc()).limit(1)
        
        result = await db.execute(stmt)
        agent_with_count = result.first()
        
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
    
    agent_schema = AgentSchema.model_validate(agent.__dict__)
    return AgentAssignment(
        user_id=user_id,
        agent=agent_schema,
        assigned_at=datetime.utcnow(),
        assignment_reason="auto_assigned" if not agent_id else "manual_assigned"
    )

async def get_agent_with_stats(db: AsyncSession, agent_id: int) -> Optional[AgentWithStats]:
    """Get agent with performance statistics"""
    stmt = select(Agent).where(Agent.id == agent_id)
    result = await db.execute(stmt)
    agent = result.scalar_one_or_none()
    
    if not agent:
        return None
    
    # Get current active users count
    stmt = select(func.count(User.id)).where(User.agent_id == agent_id)
    result = await db.execute(stmt)
    current_users = result.scalar() or 0
    
    # Get visit stats for efficiency calculation
    stmt = select(func.count(Visit.id)).where(Visit.agent_id == agent_id)
    result = await db.execute(stmt)
    total_visits = result.scalar() or 0

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
    
    agent_schema = AgentSchema.model_validate(agent.__dict__)
    return AgentWithStats(
        **agent_schema.model_dump(),
        stats=stats
    )

async def get_agents_by_specialization(db: AsyncSession, specialization: str) -> List[AgentSchema]:
    """Get agents that specialize in a specific area - simplified to return all active agents"""
    stmt = select(Agent).where(Agent.is_active == True)
    result = await db.execute(stmt)
    agents = result.scalars().all()
    return [AgentSchema.model_validate(agent.__dict__) for agent in agents]

async def get_agents_by_type(db: AsyncSession, agent_type: str) -> List[AgentSchema]:
    """Get agents by type (general, specialist, senior)"""
    stmt = select(Agent).where(
        and_(Agent.is_active == True, Agent.agent_type == agent_type)
    )
    result = await db.execute(stmt)
    agents = result.scalars().all()
    return [AgentSchema.model_validate(agent.__dict__) for agent in agents]

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

async def get_workload_distribution(db: AsyncSession) -> List[AgentWorkload]:
    """Get workload distribution across all active agents"""
    stmt = select(
        Agent,
        func.count(User.id).label('current_users')
    ).outerjoin(
        User, Agent.id == User.agent_id
    ).where(
        Agent.is_active == True
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

async def get_system_stats(db: AsyncSession) -> AgentSystemStats:
    """Get overall agent system statistics"""
    # Get all agents count
    stmt = select(func.count(Agent.id))
    result = await db.execute(stmt)
    total_agents = result.scalar() or 0
    
    # Get active agents count
    stmt = select(func.count(Agent.id)).where(Agent.is_active == True)
    result = await db.execute(stmt)
    active_agents = result.scalar() or 0
    
    # Get total users served
    stmt = select(func.sum(Agent.total_users_assigned)).where(Agent.is_active == True)
    result = await db.execute(stmt)
    total_users_served = result.scalar() or 0
    
    # Get average stats
    stmt = select(
        func.avg(Agent.user_satisfaction_rating)
    ).where(Agent.is_active == True)
    result = await db.execute(stmt)
    avg_satisfaction = result.scalar() or 0
    
    # Count agents by type
    stmt = select(Agent.agent_type, func.count(Agent.id)).where(
        Agent.is_active == True
    ).group_by(Agent.agent_type)
    result = await db.execute(stmt)
    agents_by_type = dict(result.all())
    
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
        return 50.0  # Default middle score
