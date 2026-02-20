from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Dict, Any, Optional
from app.core.database import get_db
from app.api.api_v1.dependencies.auth import get_current_active_user
from app.api.api_v1.dependencies.auth import get_current_admin, get_current_agent
from app.schemas.user import User as UserSchema
from app.schemas.agent import (
    Agent,
    AgentCreate,
    AgentUpdate,
    AgentAssignment,
    AgentWithStats,
    AgentWorkload,
    AgentSystemStats,
)
from app.schemas.common import MessageResponse, PaginatedResponse
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
    get_available_agents_paginated,
    get_agents_by_type_paginated,
    get_agents_by_specialization_paginated,
    get_all_agents_paginated,
)
from app.services.visit import get_agent_visits

router = APIRouter()

# =============================================================================
# Static path routes MUST come before dynamic /{agent_id} routes
# =============================================================================


# User-facing agent endpoints
@router.get("/assigned", response_model=Agent)
async def get_my_agent(
    current_user: UserSchema = Depends(get_current_active_user), db: AsyncSession = Depends(get_db)
):
    """Get the current user's assigned agent"""
    agent = await get_user_agent(db, current_user.id)
    if not agent:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No agent assigned yet")
    return agent


@router.post("/assign", response_model=AgentAssignment)
async def assign_my_agent(
    agent_id: Optional[int] = None,
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Assign an agent to the current user (auto-assign if no agent_id provided)"""
    assignment = await assign_agent_to_user(db, current_user.id, agent_id)
    if not assignment:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="No agents available at the moment",
        )
    return assignment


# Public agent information endpoints
@router.get("/available", response_model=PaginatedResponse)
async def list_available_agents(
    specialization: Optional[str] = Query(None, description="Filter by specialization"),
    agent_type: Optional[str] = Query(None, description="Filter by agent type"),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Get list of available agents with optional filters"""
    if specialization:
        return await get_agents_by_specialization_paginated(
            db, page=page, limit=limit, specialization=specialization
        )
    return await get_available_agents_paginated(db, page=page, limit=limit, agent_type=agent_type)


@router.get("/types/{agent_type}", response_model=PaginatedResponse)
async def get_agents_by_agent_type(
    agent_type: str,
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Get agents by type (general, specialist, senior)"""
    return await get_agents_by_type_paginated(db, page=page, limit=limit, agent_type=agent_type)


@router.get("/specializations/{specialization}", response_model=PaginatedResponse)
async def get_agents_by_agent_specialization(
    specialization: str,
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Get agents by specialization - returns all active agents"""
    return await get_agents_by_specialization_paginated(
        db, page=page, limit=limit, specialization=specialization
    )


# System monitoring endpoints (must be before /{agent_id})
@router.get("/system/workload", response_model=List[AgentWorkload])
async def get_system_workload(
    current_user: UserSchema = Depends(get_current_admin), db: AsyncSession = Depends(get_db)
):
    """Get workload distribution across all agents (admin endpoint)"""
    return await get_workload_distribution(db)


@router.get("/system/stats", response_model=AgentSystemStats)
async def get_system_statistics(
    current_user: UserSchema = Depends(get_current_admin), db: AsyncSession = Depends(get_db)
):
    """Get overall agent system statistics (admin endpoint)"""
    return await get_system_stats(db)


# Agent self profile endpoint (must be before /{agent_id})
@router.get("/me", response_model=Agent)
async def get_my_agent_profile(
    current_user: UserSchema = Depends(get_current_agent), db: AsyncSession = Depends(get_db)
):
    """Return the current agent user's Agent profile.

    Assumes the agent user's `agent_id` links to their Agent record.
    """
    if not current_user.agent_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Agent profile not linked"
        )

    from app.services.agent import get_agent_by_id

    agent = await get_agent_by_id(db, current_user.agent_id)
    if not agent:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")
    return agent


# =============================================================================
# Dynamic path routes with {agent_id} - must come AFTER all static routes
# =============================================================================


@router.get("/{agent_id}", response_model=Agent)
async def get_agent_details(
    agent_id: int,
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Get details of a specific agent"""
    agent = await get_agent_by_id(db, agent_id)
    if not agent:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")
    return agent


@router.get("/{agent_id}/stats", response_model=AgentWithStats)
async def get_agent_statistics(
    agent_id: int,
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Get agent details with performance statistics"""
    agent_with_stats = await get_agent_with_stats(db, agent_id)
    if not agent_with_stats:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")
    return agent_with_stats


@router.get("/{agent_id}/visits", response_model=PaginatedResponse)
async def get_agent_visit_history(
    agent_id: int,
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(20, ge=1, le=100, description="Items per page"),
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Get visits handled by a specific agent.

    Authorization:
    - Admin users can view any agent's visits
    - Agent users can view their own visits
    - Regular users can view visits for their assigned agent
    """
    user_role = getattr(current_user, "role", None)

    # Admin can access all agent visits
    if user_role == "admin":
        visits = await get_agent_visits(db, agent_id, page, limit)
        return visits

    # Agent can access their own visits (if their user account is linked to agent_id)
    # Regular users can view visits for their assigned agent
    user_agent = await get_user_agent(db, current_user.id)

    if user_role == "agent":
        # Check if this agent_id belongs to the current user
        if user_agent and user_agent.id == agent_id:
            visits = await get_agent_visits(db, agent_id, page, limit)
            return visits
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="You can only view your own agent visits"
        )

    # Regular users can view visits for their assigned agent
    if user_agent and user_agent.id == agent_id:
        visits = await get_agent_visits(db, agent_id, page, limit)
        return visits

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="You don't have permission to view this agent's visits",
    )


# Admin endpoints
@router.get("", response_model=PaginatedResponse)
async def list_all_agents(
    include_inactive: bool = Query(False, description="Include inactive agents"),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    current_user: UserSchema = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Get list of all agents (admin endpoint)"""
    return await get_all_agents_paginated(
        db, page=page, limit=limit, include_inactive=include_inactive
    )


@router.post("", response_model=Agent)
async def create_new_agent(
    agent_data: AgentCreate,
    current_user: UserSchema = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Create a new agent (admin endpoint)"""
    agent = await create_agent(db, agent_data)
    if not agent:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Failed to create agent. Agent code might already exist.",
        )
    return agent


@router.put("/{agent_id}", response_model=Agent)
async def update_agent_details(
    agent_id: int,
    update_data: AgentUpdate,
    current_user: UserSchema = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Update agent details (admin endpoint)"""
    updated_agent = await update_agent(db, agent_id, update_data)
    if not updated_agent:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")
    return updated_agent


@router.delete("/{agent_id}", response_model=MessageResponse)
async def deactivate_agent(
    agent_id: int,
    current_user: UserSchema = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Deactivate an agent (admin endpoint)"""
    success = await delete_agent(db, agent_id)
    if not success:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")
    return MessageResponse(message="Agent deactivated successfully")


@router.patch("/{agent_id}/availability", response_model=MessageResponse)
async def update_agent_availability_status(
    agent_id: int,
    is_available: bool,
    current_user: UserSchema = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Update agent availability (admin endpoint)"""
    success = await update_agent_availability(db, agent_id, is_available)
    if not success:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")
    status_text = "available" if is_available else "unavailable"
    return MessageResponse(message=f"Agent marked as {status_text}")
