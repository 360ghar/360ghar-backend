from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.api_v1.dependencies.auth import (
    get_current_active_user,
    get_current_admin,
    get_current_agent,
)
from app.core.database import get_db
from app.core.exceptions import ForbiddenException
from app.models.enums import AgentType
from app.schemas.agent import (
    Agent,
    AgentAssignment,
    AgentAvailabilityUpdate,
    AgentCreate,
    AgentSystemStats,
    AgentUpdate,
    AgentWithStats,
    AgentWorkload,
)
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
from app.services.property import attach_owner_agents
from app.services.visibility import Viewer, mask_visits_contacts
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
    """Get the current user's assigned agent. Reading never assigns an agent."""
    agent = await get_user_agent(db, current_user.id, auto_assign=False)
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
        # Empty inventory is a business state, not an infra outage.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "NO_AGENTS_AVAILABLE",
                "message": "No agents available at the moment",
            },
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
    filters = {"specialization": specialization, "agent_type": agent_type}
    cursor_payload = page.decoded(filters)
    if specialization:
        rows, next_payload, total = await get_agents_by_specialization_paginated(
            db,
            cursor_payload=cursor_payload,
            limit=page.limit,
            with_total=page.include_total,
            specialization=specialization,
        )
    else:
        rows, next_payload, total = await get_available_agents_paginated(
            db,
            cursor_payload=cursor_payload,
            limit=page.limit,
            with_total=page.include_total,
            agent_type=agent_type,
        )
    return build_cursor_page(
        [Agent.model_validate(r) for r in rows],
        limit=page.limit,
        next_payload=next_payload,
        total=total,
        filters=filters,
    )


@router.get("/types/{agent_type}", response_model=CursorPage[Agent], summary="List agents by type")
async def get_agents_by_agent_type(
    agent_type: str,
    page: CursorParams = Depends(),
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Get agents by type (general, specialist, senior)"""
    valid_types = {t.value for t in AgentType}
    if agent_type not in valid_types:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid agent_type. Must be one of: {', '.join(sorted(valid_types))}",
        )
    filters = {"agent_type": agent_type}
    rows, next_payload, total = await get_agents_by_type_paginated(
        db,
        cursor_payload=page.decoded(filters),
        limit=page.limit,
        with_total=page.include_total,
        agent_type=agent_type,
    )
    return build_cursor_page(
        [Agent.model_validate(r) for r in rows],
        limit=page.limit,
        next_payload=next_payload,
        total=total,
        filters=filters,
    )


@router.get(
    "/specializations/{specialization}",
    response_model=CursorPage[Agent],
    summary="List agents by specialization",
)
async def get_agents_by_agent_specialization(
    specialization: str,
    page: CursorParams = Depends(),
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Get agents by specialization - returns all active agents"""
    filters = {"specialization": specialization}
    rows, next_payload, total = await get_agents_by_specialization_paginated(
        db,
        cursor_payload=page.decoded(filters),
        limit=page.limit,
        with_total=page.include_total,
        specialization=specialization,
    )
    return build_cursor_page(
        [Agent.model_validate(r) for r in rows],
        limit=page.limit,
        next_payload=next_payload,
        total=total,
        filters=filters,
    )


# System monitoring endpoints (must be before /{agent_id})
@router.get(
    "/system/workload", response_model=CursorPage[AgentWorkload], summary="Get system workload"
)
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
    """Get agent details with performance statistics. Admins and the agent themselves only."""
    viewer = Viewer.from_user(current_user)
    if not (viewer.is_admin or (viewer.is_agent and current_user.agent_id == agent_id)):
        raise ForbiddenException(
            detail="Agent statistics are visible to admins and to the agent", error_code="FORBIDDEN"
        )
    agent_with_stats = await get_agent_with_stats(db, agent_id)
    if not agent_with_stats:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")
    return agent_with_stats


@router.get(
    "/{agent_id}/visits", response_model=CursorPage[VisitSchema], summary="Get agent visit history"
)
async def get_agent_visit_history(
    agent_id: int,
    page: CursorParams = Depends(),
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Get visits handled by a specific agent.

    Authorization:
    - Admin users see every visit of any agent.
    - Agent users see the visits of their own agent.
    - Customers see only their own visits (as visitor or counterparty) with their assigned agent.
    """
    viewer = Viewer.from_user(current_user)
    filters = {"agent_id": agent_id}
    cursor_payload = page.decoded(filters)

    party_user_id: int | None = None
    if viewer.is_admin:
        pass
    elif viewer.is_agent:
        if current_user.agent_id != agent_id:
            raise ForbiddenException(
                detail="You can only view your own agent visits", error_code="FORBIDDEN"
            )
    else:
        user_agent = await get_user_agent(db, current_user.id, auto_assign=False)
        if user_agent is None or user_agent.id != agent_id:
            raise ForbiddenException(
                detail="You don't have permission to view this agent's visits",
                error_code="FORBIDDEN",
            )
        party_user_id = current_user.id

    rows, next_payload, total = await get_agent_visits(
        db,
        agent_id,
        cursor_payload,
        page.limit,
        page.include_total,
        party_user_id=party_user_id,
    )
    visits = [VisitSchema.model_validate(r, from_attributes=True) for r in rows]
    await attach_owner_agents(db, [v.property for v in visits])
    return build_cursor_page(
        mask_visits_contacts(visits, current_user),
        limit=page.limit,
        next_payload=next_payload,
        total=total,
        filters=filters,
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
    filters = {"include_inactive": include_inactive}
    rows, next_payload, total = await get_all_agents_paginated(
        db,
        cursor_payload=page.decoded(filters),
        limit=page.limit,
        with_total=page.include_total,
        include_inactive=include_inactive,
    )
    return build_cursor_page(
        [Agent.model_validate(r) for r in rows],
        limit=page.limit,
        next_payload=next_payload,
        total=total,
        filters=filters,
    )


@router.post("", response_model=Agent, status_code=status.HTTP_201_CREATED, summary="Create agent")
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
    """Update agent details (admin endpoint). Only the fields sent are changed."""
    updated_agent = await update_agent(db, agent_id, update_data)
    if not updated_agent:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")
    return updated_agent


@router.delete("/{agent_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Deactivate agent")
async def deactivate_agent(
    agent_id: int,
    current_user: UserSchema = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Deactivate an agent (admin endpoint)"""
    success = await delete_agent(db, agent_id)
    if not success:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.patch("/{agent_id}/availability", response_model=Agent, summary="Update agent availability")
async def update_agent_availability_status(
    agent_id: int,
    body: AgentAvailabilityUpdate,
    current_user: UserSchema = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Update agent availability (admin endpoint). Send {"is_available": true|false} as JSON."""
    success = await update_agent_availability(db, agent_id, body.is_available)
    if not success:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")
    updated = await get_agent_by_id(db, agent_id)
    if updated is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")
    return updated
