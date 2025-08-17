from supabase import Client
from typing import Optional, List, Dict, Any
from app.repositories.agent import AgentRepository
from app.schemas.agent import (
    Agent, 
    AgentCreate,
    AgentUpdate,
    AgentAssignment, 
    AgentStats,
    AgentWithStats,
    AgentWorkload,
    AgentSystemStats
)
from app.db.types import AgentDB
from datetime import datetime
from app.core.logging import get_logger

logger = get_logger(__name__)

def _parse_agent_db_to_schema(agent_db: Optional[AgentDB]) -> Optional[Agent]:
    """Parse AgentDB dict to Pydantic Agent schema"""
    if not agent_db:
        return None
    
    agent_data = dict(agent_db)
    return Agent.model_validate(agent_data)

async def get_all_agents(supabase: Client) -> List[Agent]:
    """Get all agents"""
    repo = AgentRepository(supabase)
    agents_db = await repo.get_all_agents()
    
    agents = []
    for agent_db in agents_db:
        agent_schema = _parse_agent_db_to_schema(agent_db)
        if agent_schema:
            agents.append(agent_schema)
    
    return agents

async def get_active_agents(supabase: Client) -> List[Agent]:
    """Get all active agents"""
    repo = AgentRepository(supabase)
    agents_db = await repo.get_active_agents()
    
    agents = []
    for agent_db in agents_db:
        agent_schema = _parse_agent_db_to_schema(agent_db)
        if agent_schema:
            agents.append(agent_schema)
    
    return agents

async def get_available_agents(supabase: Client) -> List[Agent]:
    """Get all available agents (active and available)"""
    repo = AgentRepository(supabase)
    agents_db = await repo.get_available_agents()
    
    agents = []
    for agent_db in agents_db:
        agent_schema = _parse_agent_db_to_schema(agent_db)
        if agent_schema:
            agents.append(agent_schema)
    
    return agents

async def get_agent_by_id(supabase: Client, agent_id: int) -> Optional[Agent]:
    """Get a specific agent by ID"""
    repo = AgentRepository(supabase)
    agent_db = await repo.get_by_id(agent_id)
    return _parse_agent_db_to_schema(agent_db)

async def get_agent_by_code(supabase: Client, agent_code: str) -> Optional[Agent]:
    """Get agent by unique agent code"""
    repo = AgentRepository(supabase)
    agent_db = await repo.get_agent_by_code(agent_code)
    return _parse_agent_db_to_schema(agent_db)

async def create_agent(supabase: Client, agent_data: AgentCreate) -> Optional[Agent]:
    """Create a new agent"""
    repo = AgentRepository(supabase)
    
    # Check if agent code already exists
    existing_agent = await repo.get_agent_by_code(agent_data.agent_code)
    if existing_agent:
        logger.warning(f"Agent with code {agent_data.agent_code} already exists")
        return None
    
    # Create the agent
    agent_dict = agent_data.model_dump()
    agent_dict["is_active"] = True
    agent_dict["is_available"] = True
    agent_dict["total_users_assigned"] = 0
    agent_dict["total_interactions"] = 0
    agent_dict["average_response_time_seconds"] = 30
    agent_dict["user_satisfaction_rating"] = 0.0
    
    created_agent = await repo.create(agent_dict)
    return _parse_agent_db_to_schema(created_agent)

async def update_agent(supabase: Client, agent_id: int, update_data: AgentUpdate) -> Optional[Agent]:
    """Update agent details"""
    repo = AgentRepository(supabase)
    
    # Filter out None values
    update_dict = {k: v for k, v in update_data.model_dump().items() if v is not None}
    
    if not update_dict:
        # No valid updates
        return await get_agent_by_id(supabase, agent_id)
    
    updated_agent = await repo.update(agent_id, update_dict)
    return _parse_agent_db_to_schema(updated_agent)

async def delete_agent(supabase: Client, agent_id: int) -> bool:
    """Soft delete an agent (set as inactive)"""
    repo = AgentRepository(supabase)
    
    # Set agent as inactive instead of hard delete
    update_data = {
        "is_active": False,
        "is_available": False
    }
    
    updated_agent = await repo.update(agent_id, update_data)
    return updated_agent is not None

async def get_user_agent(supabase: Client, user_id: int, auto_assign: bool = True) -> Optional[Agent]:
    """Get the assigned agent for a user, auto-assign if none exists"""
    repo = AgentRepository(supabase)
    
    # Check if user already has an agent
    agent_db = await repo.get_user_agent(user_id)
    if agent_db:
        return _parse_agent_db_to_schema(agent_db)
    
    # Auto-assign if requested and no agent exists
    if auto_assign:
        logger.info(f"Auto-assigning agent for user {user_id}")
        assignment = await assign_agent_to_user(supabase, user_id)
        if assignment:
            return assignment.agent
    
    return None

async def assign_agent_to_user(supabase: Client, user_id: int, agent_id: Optional[int] = None) -> Optional[AgentAssignment]:
    """Assign an agent to a user (auto-assign if no agent_id provided)"""
    repo = AgentRepository(supabase)
    
    # Check if user already has an agent
    existing_agent = await repo.get_user_agent(user_id)
    if existing_agent:
        agent_schema = _parse_agent_db_to_schema(existing_agent)
        if agent_schema:
            return AgentAssignment(
                user_id=user_id,
                agent=agent_schema,
                assigned_at=datetime.utcnow(),
                assignment_reason="already_assigned"
            )
    
    # Determine which agent to assign
    if agent_id:
        # Specific agent requested
        agent_db = await repo.get_by_id(agent_id)
        if not agent_db or not agent_db.get("is_active") or not agent_db.get("is_available"):
            logger.warning(f"Requested agent {agent_id} is not available")
            return None
    else:
        # Auto-assign based on load balancing
        agent_db = await repo.get_agent_with_least_users()
        if not agent_db:
            logger.warning("No available agents for assignment")
            return None
        agent_id = agent_db["id"]
    
    # Assign the agent
    success = await repo.assign_agent_to_user(user_id, agent_id)
    if not success:
        return None
    
    # Update last active timestamp
    await repo.update_last_active(agent_id)
    
    agent_schema = _parse_agent_db_to_schema(agent_db)
    if agent_schema:
        return AgentAssignment(
            user_id=user_id,
            agent=agent_schema,
            assigned_at=datetime.utcnow(),
            assignment_reason="auto_assigned" if not agent_id else "manual_assigned"
        )
    
    return None

async def get_agent_with_stats(supabase: Client, agent_id: int) -> Optional[AgentWithStats]:
    """Get agent with performance statistics"""
    repo = AgentRepository(supabase)
    
    agent_db = await repo.get_by_id(agent_id)
    if not agent_db:
        return None
    
    # Get agent stats
    stats_data = await repo.get_agent_stats(agent_id)
    
    stats = AgentStats(
        total_users_assigned=stats_data.get("total_users_assigned", 0),
        total_interactions=stats_data.get("total_interactions", 0),
        average_response_time_seconds=stats_data.get("average_response_time_seconds", 30),
        user_satisfaction_rating=stats_data.get("user_satisfaction_rating", 0.0),
        active_conversations=stats_data.get("current_active_users", 0),
        daily_interactions=0,  # TODO: Calculate from interaction logs
        weekly_interactions=0,  # TODO: Calculate from interaction logs
        efficiency_score=_calculate_efficiency_score(stats_data)
    )
    
    agent_schema = _parse_agent_db_to_schema(agent_db)
    if agent_schema:
        return AgentWithStats(
            **agent_schema.model_dump(),
            stats=stats
        )
    
    return None

async def get_agents_by_specialization(supabase: Client, specialization: str) -> List[Agent]:
    """Get agents that specialize in a specific area"""
    repo = AgentRepository(supabase)
    agents_db = await repo.get_agents_by_specialization(specialization)
    
    agents = []
    for agent_db in agents_db:
        agent_schema = _parse_agent_db_to_schema(agent_db)
        if agent_schema:
            agents.append(agent_schema)
    
    return agents

async def get_agents_by_type(supabase: Client, agent_type: str) -> List[Agent]:
    """Get agents by type (general, specialist, senior)"""
    repo = AgentRepository(supabase)
    agents_db = await repo.get_agents_by_type(agent_type)
    
    agents = []
    for agent_db in agents_db:
        agent_schema = _parse_agent_db_to_schema(agent_db)
        if agent_schema:
            agents.append(agent_schema)
    
    return agents

async def update_agent_availability(supabase: Client, agent_id: int, is_available: bool) -> bool:
    """Update agent availability status"""
    repo = AgentRepository(supabase)
    return await repo.update_agent_availability(agent_id, is_available)

async def get_workload_distribution(supabase: Client) -> List[AgentWorkload]:
    """Get workload distribution across all active agents"""
    repo = AgentRepository(supabase)
    workload_data = await repo.get_workload_distribution()
    
    workload = []
    for data in workload_data:
        workload.append(AgentWorkload(
            agent_id=data["agent_id"],
            agent_name=data["agent_name"],
            current_users=data["current_users"],
            max_users=data["max_users"],
            utilization_percentage=data["utilization_percentage"],
            is_available=data["is_available"],
            queue_length=data["queue_length"]
        ))
    
    return workload

async def get_system_stats(supabase: Client) -> AgentSystemStats:
    """Get overall agent system statistics"""
    repo = AgentRepository(supabase)
    
    all_agents = await repo.get_all_agents()
    active_agents = await repo.get_active_agents()
    workload = await get_workload_distribution(supabase)
    
    # Calculate aggregate stats
    total_users_served = sum(agent.get("total_users_assigned", 0) for agent in all_agents)
    total_interactions_today = 0  # TODO: Calculate from interaction logs
    avg_response_time = sum(agent.get("average_response_time_seconds", 30) for agent in active_agents) / len(active_agents) if active_agents else 30
    avg_satisfaction = sum(agent.get("user_satisfaction_rating", 0) for agent in active_agents) / len(active_agents) if active_agents else 0
    
    # Count agents by type
    agents_by_type = {}
    for agent in active_agents:
        agent_type = agent.get("agent_type", "general")
        agents_by_type[agent_type] = agents_by_type.get(agent_type, 0) + 1
    
    return AgentSystemStats(
        total_agents=len(all_agents),
        active_agents=len(active_agents),
        total_users_served=total_users_served,
        total_interactions_today=total_interactions_today,
        average_response_time=avg_response_time,
        system_satisfaction_score=avg_satisfaction,
        agents_by_type=agents_by_type,
        load_distribution=workload
    )

def _calculate_efficiency_score(stats_data: Dict[str, Any]) -> float:
    """Calculate agent efficiency score based on various metrics"""
    try:
        response_time = stats_data.get("average_response_time_seconds", 30)
        satisfaction = stats_data.get("user_satisfaction_rating", 0.0)
        utilization = stats_data.get("utilization_percentage", 0.0)
        
        # Normalize response time (lower is better, cap at 300 seconds)
        response_score = max(0, 100 - (response_time / 300 * 100))
        
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