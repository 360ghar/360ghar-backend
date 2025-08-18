from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Dict, Any, Optional
from app.core.database import get_db
from app.api.api_v1.endpoints.auth import get_current_active_user
from app.schemas.user import User as UserSchema
from app.schemas.agent import (
    Agent, 
    AgentCreate,
    AgentUpdate,
    AgentAssignment,
    AgentWithStats,
    AgentWorkload,
    AgentSystemStats
)
from app.schemas.common import MessageResponse
from app.services.agent import (
    get_all_agents,
    get_active_agents,
    get_available_agents,
    get_agent_by_id,
    create_agent,
    update_agent,
    delete_agent,
    get_user_agent,
    assign_agent_to_user,
    get_agent_with_stats,
    get_agents_by_specialization,
    get_agents_by_type,
    update_agent_availability,
    get_workload_distribution,
    get_system_stats,
)
from app.services.visit import get_agent_visits

router = APIRouter()

# User-facing agent endpoints
@router.get("/assigned", response_model=Agent)
async def get_my_agent(
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """Get the current user's assigned agent"""
    agent = await get_user_agent(db, current_user.id)
    if not agent:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No agent assigned yet"
        )
    return agent

@router.post("/assign", response_model=AgentAssignment)
async def assign_my_agent(
    agent_id: Optional[int] = None,
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """Assign an agent to the current user (auto-assign if no agent_id provided)"""
    assignment = await assign_agent_to_user(db, current_user.id, agent_id)
    if not assignment:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="No agents available at the moment"
        )
    return assignment

# Public agent information endpoints
@router.get("/available", response_model=List[Agent])
async def list_available_agents(
    specialization: Optional[str] = Query(None, description="Filter by specialization"),
    agent_type: Optional[str] = Query(None, description="Filter by agent type"),
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """Get list of available agents with optional filters"""
    if specialization:
        agents = await get_agents_by_specialization(db, specialization)
        # Filter only available ones
        return [agent for agent in agents if agent.is_available]
    elif agent_type:
        agents = await get_agents_by_type(db, agent_type)
        # Filter only available ones
        return [agent for agent in agents if agent.is_available]
    else:
        return await get_available_agents(db)

@router.get("/types/{agent_type}", response_model=List[Agent])
async def get_agents_by_agent_type(
    agent_type: str,
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """Get agents by type (general, specialist, senior)"""
    agents = await get_agents_by_type(db, agent_type)
    return agents

@router.get("/specializations/{specialization}", response_model=List[Agent])
async def get_agents_by_agent_specialization(
    specialization: str,
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """Get agents by specialization - returns all active agents"""
    agents = await get_agents_by_specialization(db, specialization)
    return agents

@router.get("/{agent_id}", response_model=Agent)
async def get_agent_details(
    agent_id: int,
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """Get details of a specific agent"""
    agent = await get_agent_by_id(db, agent_id)
    if not agent:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Agent not found"
        )
    return agent


@router.get("/{agent_id}/stats", response_model=AgentWithStats)
async def get_agent_statistics(
    agent_id: int,
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """Get agent details with performance statistics"""
    agent_with_stats = await get_agent_with_stats(db, agent_id)
    if not agent_with_stats:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Agent not found"
        )
    return agent_with_stats

@router.get("/{agent_id}/visits")
async def get_agent_visit_history(
    agent_id: int,
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(20, ge=1, le=100, description="Items per page"),
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """Get visits handled by a specific agent"""
    # TODO: Add proper authorization - only allow agent admin or the agent's assigned users
    visits = await get_agent_visits(db, agent_id, page, limit)
    return visits

# Admin endpoints (TODO: Add admin role check)
@router.get("", response_model=List[Agent])
async def list_all_agents(
    include_inactive: bool = Query(False, description="Include inactive agents"),
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """Get list of all agents (admin endpoint)"""
    # TODO: Add admin role check
    if include_inactive:
        return await get_all_agents(db)
    else:
        return await get_active_agents(db)

@router.post("", response_model=Agent)
async def create_new_agent(
    agent_data: AgentCreate,
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """Create a new agent (admin endpoint)"""
    # TODO: Add admin role check
    agent = await create_agent(db, agent_data)
    if not agent:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Failed to create agent. Agent code might already exist."
        )
    return agent

@router.put("/{agent_id}", response_model=Agent)
async def update_agent_details(
    agent_id: int,
    update_data: AgentUpdate,
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """Update agent details (admin endpoint)"""
    # TODO: Add admin role check
    updated_agent = await update_agent(db, agent_id, update_data)
    if not updated_agent:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Agent not found"
        )
    return updated_agent

@router.delete("/{agent_id}", response_model=MessageResponse)
async def deactivate_agent(
    agent_id: int,
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """Deactivate an agent (admin endpoint)"""
    # TODO: Add admin role check
    success = await delete_agent(db, agent_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Agent not found"
        )
    return MessageResponse(message="Agent deactivated successfully")

@router.patch("/{agent_id}/availability", response_model=MessageResponse)
async def update_agent_availability_status(
    agent_id: int,
    is_available: bool,
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """Update agent availability (admin endpoint)"""
    # TODO: Add admin role check
    success = await update_agent_availability(db, agent_id, is_available)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Agent not found"
        )
    status_text = "available" if is_available else "unavailable"
    return MessageResponse(message=f"Agent marked as {status_text}")

# System monitoring endpoints
@router.get("/system/workload", response_model=List[AgentWorkload])
async def get_system_workload(
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """Get workload distribution across all agents (admin endpoint)"""
    # TODO: Add admin role check
    return await get_workload_distribution(db)

@router.get("/system/stats", response_model=AgentSystemStats)
async def get_system_statistics(
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """Get overall agent system statistics (admin endpoint)"""
    # TODO: Add admin role check
    return await get_system_stats(db)