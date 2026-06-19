from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.api_v1.dependencies.auth import (
    get_current_active_user,
    get_current_admin,
    get_current_agent,
)
from app.core.database import get_db
from app.schemas.agent import (
    Agent,
    AgentAssignment,
    AgentCreate,
    AgentSystemStats,
    AgentUpdate,
    AgentWithStats,
    AgentWorkload,
)
from app.schemas.common import MessageResponse
from app.schemas.pagination import CursorPage, CursorParams, build_cursor_page
from app.schemas.user import User as UserSchema
from app.schemas.visit import Visit as VisitSchema
from app.services.agent import (
    assign_agent_to_user,
    create_agent,
    delete_agent,
    get_agent_by_id,
    get_agent_with_stats,
    get_agents_by_specialization_paginated,
    get_agents_by_type_paginated,
    get_all_agents_paginated,
    get_available_agents_paginated,
    get_system_stats,
    get_user_agent,
    get_workload_distribution_paginated,
    update_agent,
    update_agent_availability,
)
from app.services.visit import get_agent_visits

router = APIRouter()

# =============================================================================
# Static path routes MUST come before dynamic /{agent_id} routes
# =============================================================================


# User-facing agent endpoints
@router.get("/assigned", response_model=Agent, summary="Get my assigned agent")
async def get_my_agent(
    current_user: UserSchema = Depends(get_current_active_user), db: AsyncSession = Depends(get_db)
):
    """Get the current user's assigned agent"""
    agent = await get_user_agent(db, current_user.id)
    if not agent:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No agent assigned yet")
    return agent


@router.post("/assign", response_model=AgentAssignment, summary="Assign agent to me")
async def assign_my_agent(
    agent_id: int | None = None,
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
@router.get("/available", response_model=CursorPage[Agent], summary="List available agents")
async def list_available_agents(
    specialization: str | None = Query(None, description="Filter by specialization"),
    agent_type: str | None = Query(None, description="Filter by agent type"),
    page: CursorParams = Depends(),
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Get list of available agents with optional filters"""
    if specialization:
        rows, next_payload, total = await get_agents_by_specialization_paginated(
            db, cursor_payload=page.decoded(), limit=page.limit, with_total=page.include_total, specialization=specialization
        )
    else:
        rows, next_payload, total = await get_available_agents_paginated(
            db, cursor_payload=page.decoded(), limit=page.limit, with_total=page.include_total, agent_type=agent_type
        )
    return build_cursor_page(
        [Agent.model_validate(r) for r in rows],
        limit=page.limit,
        next_payload=next_payload,
        total=total,
    )


@router.get("/types/{agent_type}", response_model=CursorPage[Agent], summary="List agents by type")
async def get_agents_by_agent_type(
    agent_type: str,
    page: CursorParams = Depends(),
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Get agents by type (general, specialist, senior)"""
    rows, next_payload, total = await get_agents_by_type_paginated(
        db, cursor_payload=page.decoded(), limit=page.limit, with_total=page.include_total, agent_type=agent_type
    )
    return build_cursor_page(
        [Agent.model_validate(r) for r in rows],
        limit=page.limit,
        next_payload=next_payload,
        total=total,
    )


@router.get("/specializations/{specialization}", response_model=CursorPage[Agent], summary="List agents by specialization")
async def get_agents_by_agent_specialization(
    specialization: str,
    page: CursorParams = Depends(),
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Get agents by specialization - returns all active agents"""
    rows, next_payload, total = await get_agents_by_specialization_paginated(
        db, cursor_payload=page.decoded(), limit=page.limit, with_total=page.include_total, specialization=specialization
    )
    return build_cursor_page(
        [Agent.model_validate(r) for r in rows],
        limit=page.limit,
        next_payload=next_payload,
        total=total,
    )


# System monitoring endpoints (must be before /{agent_id})
@router.get("/system/workload", response_model=CursorPage[AgentWorkload], summary="Get system workload")
async def get_system_workload(
    page: CursorParams = Depends(),
    current_user: UserSchema = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Get workload distribution across all agents (admin endpoint)"""
    rows, next_payload, total = await get_workload_distribution_paginated(
        db,
        cursor_payload=page.decoded(),
        limit=page.limit,
        with_total=page.include_total,
    )
    return build_cursor_page(rows, limit=page.limit, next_payload=next_payload, total=total)


@router.get("/system/stats", response_model=AgentSystemStats, summary="Get system statistics")
async def get_system_statistics(
    current_user: UserSchema = Depends(get_current_admin), db: AsyncSession = Depends(get_db)
):
    """Get overall agent system statistics (admin endpoint)"""
    return await get_system_stats(db)


# Agent self profile endpoint (must be before /{agent_id})
@router.get("/me", response_model=Agent, summary="Get my agent profile")
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


@router.get("/{agent_id}", response_model=Agent, summary="Get agent details")
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


@router.get("/{agent_id}/stats", response_model=AgentWithStats, summary="Get agent statistics")
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


@router.get("/{agent_id}/visits", response_model=CursorPage[VisitSchema], summary="Get agent visit history")
async def get_agent_visit_history(
    agent_id: int,
    page: CursorParams = Depends(),
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
        items, next_payload, total = await get_agent_visits(
            db, agent_id, page.decoded(), page.limit, page.include_total
        )
        return build_cursor_page(items, limit=page.limit, next_payload=next_payload, total=total)

    # Agent can access their own visits (if their user account is linked to agent_id)
    # Regular users can view visits for their assigned agent
    user_agent = await get_user_agent(db, current_user.id)

    if user_role == "agent":
        # Check if this agent_id belongs to the current user
        if user_agent and user_agent.id == agent_id:
            items, next_payload, total = await get_agent_visits(
                db, agent_id, page.decoded(), page.limit, page.include_total
            )
            return build_cursor_page(items, limit=page.limit, next_payload=next_payload, total=total)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="You can only view your own agent visits"
        )

    # Regular users can view visits for their assigned agent
    if user_agent and user_agent.id == agent_id:
        items, next_payload, total = await get_agent_visits(
            db, agent_id, page.decoded(), page.limit, page.include_total
        )
        return build_cursor_page(items, limit=page.limit, next_payload=next_payload, total=total)

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="You don't have permission to view this agent's visits",
    )


# Admin endpoints
@router.get("", response_model=CursorPage[Agent], summary="List all agents")
async def list_all_agents(
    include_inactive: bool = Query(False, description="Include inactive agents"),
    page: CursorParams = Depends(),
    current_user: UserSchema = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Get list of all agents (admin endpoint)"""
    rows, next_payload, total = await get_all_agents_paginated(
        db, cursor_payload=page.decoded(), limit=page.limit, with_total=page.include_total, include_inactive=include_inactive
    )
    return build_cursor_page(
        [Agent.model_validate(r) for r in rows],
        limit=page.limit,
        next_payload=next_payload,
        total=total,
    )


@router.post("", response_model=Agent, summary="Create agent")
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


@router.put("/{agent_id}", response_model=Agent, summary="Update agent")
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


@router.delete("/{agent_id}", response_model=MessageResponse, summary="Deactivate agent")
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


@router.patch("/{agent_id}/availability", response_model=MessageResponse, summary="Update agent availability")
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
