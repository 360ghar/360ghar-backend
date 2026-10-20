from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.api_v1.dependencies.auth import (
    get_current_active_user,
    get_current_cached_active_user,
)
from app.core.database import get_db
from app.core.db_resilience import raise_read_service_unavailable
from app.core.exceptions import BadRequestException, NotFoundException
from app.models.enums import VisitStatus
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
from app.services.auth_user_cache import AuthUserSnapshot
from app.services.pm_authz import can_access_visit
from app.services.property import attach_owner_agents
from app.services.visibility import Viewer, mask_visit_contacts, mask_visits_contacts
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


async def _visit_out(db: AsyncSession, visit, viewer) -> Visit:
    """Serialize a visit with the owner's agent, hiding contact details the viewer may not see."""
    out = Visit.model_validate(visit, from_attributes=True)
    await attach_owner_agents(db, [out.property])
    return mask_visit_contacts(out, viewer)


async def _visits_out(db: AsyncSession, rows, viewer) -> list[Visit]:
    """Serialize a page of visits. One query resolves the owners' agents."""
    visits = [Visit.model_validate(r, from_attributes=True) for r in rows]
    await attach_owner_agents(db, [v.property for v in visits])
    return mask_visits_contacts(visits, viewer)


async def _resolve_owner_id(db: AsyncSession, actor: User, requested_user_id: int | None) -> int:
    """Admins and agents may name the visit owner. Everyone else owns the visit."""
    viewer = Viewer.from_user(actor)
    if requested_user_id is None or not (viewer.is_admin or viewer.is_agent):
        return actor.id
    if await db.get(User, requested_user_id) is None:
        raise NotFoundException(detail="User not found", error_code="USER_NOT_FOUND")
    return requested_user_id


@router.post(
    "",
    response_model=Visit,
    status_code=status.HTTP_201_CREATED,
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
                                "time_slot_label": "morning",
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
    db: AsyncSession = Depends(get_db),
):
    """Schedule a visit."""
    owner_id = await _resolve_owner_id(db, current_user, visit.user_id)
    created = await create_visit(db, owner_id, visit)
    return await _visit_out(db, created, current_user)


@router.get("", response_model=CursorPage[Visit], summary="List my visits")
async def get_my_visits(
    page: CursorParams = Depends(),
    status: VisitStatus | None = Query(None, description="Filter by visit status"),
    current_user: AuthUserSnapshot = Depends(get_current_cached_active_user),
    db: AsyncSession = Depends(get_db),
):
    """List my visits."""
    filters = {"status": status}
    cursor_payload = page.decoded(filters)
    try:
        rows, next_payload, total = await get_user_visits(
            db,
            current_user.id,
            cursor_payload=cursor_payload,
            limit=page.limit,
            with_total=page.include_total,
            status=status,
        )
        return build_cursor_page(
            await _visits_out(db, rows, current_user),
            limit=page.limit,
            next_payload=next_payload,
            total=total,
            filters=filters,
        )
    except Exception as exc:
        raise_read_service_unavailable(
            exc,
            endpoint="visits_list",
            detail="Visits are temporarily unavailable. Please retry shortly.",
            extra={"user": current_user.id},
        )
        raise


@router.get("/upcoming", response_model=CursorPage[Visit], summary="List upcoming visits")
async def get_upcoming_visits(
    page: CursorParams = Depends(),
    current_user: AuthUserSnapshot = Depends(get_current_cached_active_user),
    db: AsyncSession = Depends(get_db),
):
    """List upcoming visits."""
    filters: dict = {}
    cursor_payload = page.decoded(filters)
    try:
        rows, next_payload, total = await get_user_upcoming_visits(
            db,
            current_user.id,
            cursor_payload=cursor_payload,
            limit=page.limit,
            with_total=page.include_total,
        )
        return build_cursor_page(
            await _visits_out(db, rows, current_user),
            limit=page.limit,
            next_payload=next_payload,
            total=total,
            filters=filters,
        )
    except Exception as exc:
        raise_read_service_unavailable(
            exc,
            endpoint="visits_upcoming",
            detail="Upcoming visits are temporarily unavailable. Please retry shortly.",
            extra={"user": current_user.id},
        )
        raise


@router.get("/past", response_model=CursorPage[Visit], summary="List past visits")
async def get_past_visits(
    page: CursorParams = Depends(),
    current_user: AuthUserSnapshot = Depends(get_current_cached_active_user),
    db: AsyncSession = Depends(get_db),
):
    """List past visits."""
    filters: dict = {}
    cursor_payload = page.decoded(filters)
    try:
        rows, next_payload, total = await get_user_past_visits(
            db,
            current_user.id,
            cursor_payload=cursor_payload,
            limit=page.limit,
            with_total=page.include_total,
        )
        return build_cursor_page(
            await _visits_out(db, rows, current_user),
            limit=page.limit,
            next_payload=next_payload,
            total=total,
            filters=filters,
        )
    except Exception as exc:
        raise_read_service_unavailable(
            exc,
            endpoint="visits_past",
            detail="Past visits are temporarily unavailable. Please retry shortly.",
            extra={"user": current_user.id},
        )
        raise


@router.get("/all", response_model=CursorPage[Visit], summary="List all visits")
async def list_all_visits(
    page: CursorParams = Depends(),
    status: VisitStatus | None = Query(None),
    agent_id: int | None = Query(None, description="Admin only: filter by agent id"),
    property_id: int | None = Query(None),
    user_id: int | None = Query(None),
    q: str | None = Query(
        None, max_length=200, description="Search the property title, visitor name or agent name"
    ),
    current_user: AuthUserSnapshot = Depends(get_current_cached_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Global visits listing. Admins see all; agents see their managed users/properties."""
    viewer = Viewer.from_user(current_user)
    effective_agent_id = None
    if viewer.is_admin:
        effective_agent_id = agent_id
    elif viewer.is_agent:
        effective_agent_id = current_user.agent_id
    else:
        raise HTTPException(status_code=403, detail="Access denied")

    filters = {
        "status": status,
        "agent_id": agent_id,
        "property_id": property_id,
        "user_id": user_id,
        "q": q,
    }
    cursor_payload = page.decoded(filters)
    if viewer.is_agent and effective_agent_id is None:
        return build_cursor_page(
            [],
            limit=page.limit,
            next_payload=None,
            total=0 if page.include_total else None,
            filters=filters,
        )

    try:
        rows, next_payload, total = await get_all_visits(
            db,
            cursor_payload=cursor_payload,
            limit=page.limit,
            with_total=page.include_total,
            status=status,
            filter_agent_id=effective_agent_id,
            property_id=property_id,
            user_id=user_id,
            q=q,
        )
        return build_cursor_page(
            await _visits_out(db, rows, current_user),
            limit=page.limit,
            next_payload=next_payload,
            total=total,
            filters=filters,
        )
    except Exception as exc:
        raise_read_service_unavailable(
            exc,
            endpoint="visits_all",
            detail="Visits are temporarily unavailable. Please retry shortly.",
            extra={"user": current_user.id},
        )
        raise


@router.get("/{visit_id}", response_model=Visit, summary="Get visit details")
async def get_visit_details(
    visit_id: int,
    current_user: AuthUserSnapshot = Depends(get_current_cached_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Get visit details."""
    visit = await get_visit(db, visit_id)
    if not visit:
        raise HTTPException(status_code=404, detail="Visit not found")

    if not await can_access_visit(
        db,
        actor=current_user,
        visit_user_id=visit.user_id,
        visit_property_id=visit.property_id,
        visit_counterparty_user_id=visit.counterparty_user_id,
        visit_agent_id=visit.agent_id,
    ):
        raise HTTPException(status_code=403, detail="Access denied")

    return await _visit_out(db, visit, current_user)


@router.put("/{visit_id}", response_model=Visit, summary="Update visit")
async def update_visit_details(
    visit_id: int,
    visit_update: VisitUpdate,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Update visit notes, feedback, follow-up or confirm the visit.

    Cancel, reschedule and complete use their own routes.
    """
    visit = await get_visit(db, visit_id)
    if not visit:
        raise HTTPException(status_code=404, detail="Visit not found")

    if not await can_access_visit(
        db,
        actor=current_user,
        visit_user_id=visit.user_id,
        visit_property_id=visit.property_id,
        visit_counterparty_user_id=visit.counterparty_user_id,
        visit_agent_id=visit.agent_id,
    ):
        raise HTTPException(status_code=403, detail="Access denied")

    updated = await update_visit(db, visit_id, visit_update)
    if updated is None:
        raise HTTPException(status_code=404, detail="Visit not found")
    return await _visit_out(db, updated, current_user)


@router.post("/{visit_id}/reschedule", response_model=Visit, summary="Reschedule visit")
async def reschedule_visit_date(
    visit_id: int,
    reschedule_data: VisitReschedule,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Reschedule visit. The optional reason is stored in cancellation_reason (no separate column)."""
    visit = await get_visit(db, visit_id)
    if not visit:
        raise HTTPException(status_code=404, detail="Visit not found")

    if not await can_access_visit(
        db,
        actor=current_user,
        visit_user_id=visit.user_id,
        visit_property_id=visit.property_id,
        visit_counterparty_user_id=visit.counterparty_user_id,
        visit_agent_id=visit.agent_id,
    ):
        raise HTTPException(status_code=403, detail="Access denied")

    updated = await reschedule_visit(db, visit_id, reschedule_data.new_date, reschedule_data.reason)
    if updated is None:
        raise BadRequestException(
            detail="Visit cannot be rescheduled to this time", error_code="VISIT_NOT_RESCHEDULABLE"
        )
    return await _visit_out(db, updated, current_user)


@router.post("/{visit_id}/cancel", response_model=Visit, summary="Cancel visit")
async def cancel_visit_request(
    visit_id: int,
    cancel_data: VisitCancel,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Cancel visit. The reason is required and is stored on the visit."""
    visit = await get_visit(db, visit_id)
    if not visit:
        raise HTTPException(status_code=404, detail="Visit not found")

    if not await can_access_visit(
        db,
        actor=current_user,
        visit_user_id=visit.user_id,
        visit_property_id=visit.property_id,
        visit_counterparty_user_id=visit.counterparty_user_id,
        visit_agent_id=visit.agent_id,
    ):
        raise HTTPException(status_code=403, detail="Access denied")

    updated = await cancel_visit(db, visit_id, cancel_data.reason)
    if updated is None:
        raise BadRequestException(
            detail="Visit cannot be cancelled", error_code="VISIT_NOT_CANCELLABLE"
        )
    return await _visit_out(db, updated, current_user)


@router.post("/{visit_id}/complete", response_model=Visit, summary="Complete visit")
async def complete_visit(
    visit_id: int,
    payload: VisitComplete | None = None,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Mark a visit as completed. Anyone who can access the visit may complete it: the visitor, the counterparty, an admin, or an agent who manages the visit."""
    visit = await get_visit(db, visit_id)
    if not visit:
        raise HTTPException(status_code=404, detail="Visit not found")

    if not await can_access_visit(
        db,
        actor=current_user,
        visit_user_id=visit.user_id,
        visit_property_id=visit.property_id,
        visit_counterparty_user_id=visit.counterparty_user_id,
        visit_agent_id=visit.agent_id,
    ):
        raise HTTPException(status_code=403, detail="Access denied")

    notes = payload.notes if payload else None
    feedback = payload.feedback if payload else None
    ok = await mark_visit_completed(db, visit_id, notes, feedback)
    if not ok:
        raise BadRequestException(
            detail="Visit cannot be completed", error_code="VISIT_NOT_COMPLETABLE"
        )

    updated = await get_visit(db, visit_id)
    if updated is None:
        raise NotFoundException(detail="Visit not found")
    return await _visit_out(db, updated, current_user)
