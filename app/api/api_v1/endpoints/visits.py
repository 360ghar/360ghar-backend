from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.api_v1.dependencies.auth import get_current_active_user
from app.core.database import get_db
from app.models.enums import UserRole
from app.models.users import User
from app.schemas.pagination import CursorPage, CursorParams, build_cursor_page
from app.schemas.visit import (
    Visit,
    VisitCancel,
    VisitComplete,
    VisitCreate,
    VisitReschedule,
    VisitUpdate,
)
from app.services.pm_authz import can_access_visit
from app.services.visit import (
    cancel_visit,
    create_visit,
    get_all_visits,
    get_user_past_visits,
    get_user_upcoming_visits,
    get_user_visits,
    get_visit,
    mark_visit_completed,
    reschedule_visit,
    update_visit,
)

router = APIRouter()


@router.post(
    "",
    response_model=Visit,
    summary="Schedule a visit",
    openapi_extra={
        "requestBody": {
            "content": {
                "application/json": {
                    "examples": {
                        "create": {
                            "value": {
                                "property_id": 1,
                                "scheduled_date": "2026-07-01T10:00:00Z",
                                "visit_context": "property_tour",
                            }
                        },
                    }
                }
            }
        }
    },
)
async def schedule_visit(
    visit: VisitCreate,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """Schedule a visit."""
    return await create_visit(db, current_user.id, visit)

@router.get("", response_model=CursorPage[Visit], summary="List my visits")
async def get_my_visits(
    page: CursorParams = Depends(),
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """List my visits."""
    rows, next_payload, total = await get_user_visits(
        db, current_user.id,
        cursor_payload=page.decoded(), limit=page.limit, with_total=page.include_total,
    )
    return build_cursor_page(
        [Visit.model_validate(r, from_attributes=True) for r in rows],
        limit=page.limit, next_payload=next_payload, total=total,
    )

@router.get("/upcoming", response_model=CursorPage[Visit], summary="List upcoming visits")
async def get_upcoming_visits(
    page: CursorParams = Depends(),
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """List upcoming visits."""
    rows, next_payload, total = await get_user_upcoming_visits(
        db, current_user.id,
        cursor_payload=page.decoded(), limit=page.limit, with_total=page.include_total,
    )
    return build_cursor_page(
        [Visit.model_validate(r, from_attributes=True) for r in rows],
        limit=page.limit, next_payload=next_payload, total=total,
    )

@router.get("/past", response_model=CursorPage[Visit], summary="List past visits")
async def get_past_visits(
    page: CursorParams = Depends(),
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """List past visits."""
    rows, next_payload, total = await get_user_past_visits(
        db, current_user.id,
        cursor_payload=page.decoded(), limit=page.limit, with_total=page.include_total,
    )
    return build_cursor_page(
        [Visit.model_validate(r, from_attributes=True) for r in rows],
        limit=page.limit, next_payload=next_payload, total=total,
    )

@router.get("/all", response_model=CursorPage[Visit], summary="List all visits")
async def list_all_visits(
    page: CursorParams = Depends(),
    status: str | None = Query(None),
    agent_id: int | None = Query(None, description="Admin only: filter by agent id"),
    property_id: int | None = Query(None),
    user_id: int | None = Query(None),
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Global visits listing. Admins see all; agents see their managed users/properties."""
    effective_agent_id = None
    if current_user.role == UserRole.admin.value:
        effective_agent_id = agent_id
    elif current_user.role == UserRole.agent.value:
        effective_agent_id = current_user.agent_id
        if effective_agent_id is None:
            return build_cursor_page([], limit=page.limit, next_payload=None, total=0)
    else:
        raise HTTPException(status_code=403, detail="Access denied")

    rows, next_payload, total = await get_all_visits(
        db,
        cursor_payload=page.decoded(),
        limit=page.limit,
        with_total=page.include_total,
        status=status,
        filter_agent_id=effective_agent_id,
        property_id=property_id,
        user_id=user_id,
    )
    return build_cursor_page(
        [Visit.model_validate(r, from_attributes=True) for r in rows],
        limit=page.limit, next_payload=next_payload, total=total,
    )

@router.get("/{visit_id}", response_model=Visit, summary="Get visit details")
async def get_visit_details(
    visit_id: int,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """Get visit details."""
    visit = await get_visit(db, visit_id)
    if not visit:
        raise HTTPException(status_code=404, detail="Visit not found")

    if not await can_access_visit(db, actor=current_user, visit_user_id=visit.user_id, visit_property_id=visit.property_id, visit_counterparty_user_id=visit.counterparty_user_id, visit_agent_id=visit.agent_id):
        raise HTTPException(status_code=403, detail="Access denied")

    return visit

@router.put("/{visit_id}", response_model=Visit, summary="Update visit")
async def update_visit_details(
    visit_id: int,
    visit_update: VisitUpdate,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """Update visit."""
    visit = await get_visit(db, visit_id)
    if not visit:
        raise HTTPException(status_code=404, detail="Visit not found")

    if not await can_access_visit(db, actor=current_user, visit_user_id=visit.user_id, visit_property_id=visit.property_id, visit_counterparty_user_id=visit.counterparty_user_id, visit_agent_id=visit.agent_id):
        raise HTTPException(status_code=403, detail="Access denied")

    return await update_visit(db, visit_id, visit_update)

@router.post("/{visit_id}/reschedule", response_model=Visit, summary="Reschedule visit")
async def reschedule_visit_date(
    visit_id: int,
    reschedule_data: VisitReschedule,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """Reschedule visit."""
    visit = await get_visit(db, visit_id)
    if not visit:
        raise HTTPException(status_code=404, detail="Visit not found")

    if not await can_access_visit(db, actor=current_user, visit_user_id=visit.user_id, visit_property_id=visit.property_id, visit_counterparty_user_id=visit.counterparty_user_id, visit_agent_id=visit.agent_id):
        raise HTTPException(status_code=403, detail="Access denied")

    updated = await reschedule_visit(db, visit_id, reschedule_data.new_date, reschedule_data.reason)
    if not updated:
        raise HTTPException(status_code=400, detail="Failed to reschedule visit")
    return updated

@router.post("/{visit_id}/cancel", response_model=Visit, summary="Cancel visit")
async def cancel_visit_request(
    visit_id: int,
    cancel_data: VisitCancel,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """Cancel visit."""
    visit = await get_visit(db, visit_id)
    if not visit:
        raise HTTPException(status_code=404, detail="Visit not found")

    if not await can_access_visit(db, actor=current_user, visit_user_id=visit.user_id, visit_property_id=visit.property_id, visit_counterparty_user_id=visit.counterparty_user_id, visit_agent_id=visit.agent_id):
        raise HTTPException(status_code=403, detail="Access denied")

    updated = await cancel_visit(db, visit_id, cancel_data.reason)
    if not updated:
        raise HTTPException(status_code=400, detail="Failed to cancel visit")
    return updated


@router.post("/{visit_id}/complete", response_model=Visit, summary="Complete visit")
async def complete_visit(
    visit_id: int,
    payload: VisitComplete | None = None,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """Mark a visit as completed. Admins or responsible Agents only."""
    visit = await get_visit(db, visit_id)
    if not visit:
        raise HTTPException(status_code=404, detail="Visit not found")

    if not await can_access_visit(db, actor=current_user, visit_user_id=visit.user_id, visit_property_id=visit.property_id, visit_counterparty_user_id=visit.counterparty_user_id, visit_agent_id=visit.agent_id):
        raise HTTPException(status_code=403, detail="Access denied")

    notes = payload.notes if payload else None
    feedback = payload.feedback if payload else None
    ok = await mark_visit_completed(db, visit_id, notes, feedback)
    if not ok:
        raise HTTPException(status_code=400, detail="Failed to complete visit")

    updated = await get_visit(db, visit_id)
    return updated
