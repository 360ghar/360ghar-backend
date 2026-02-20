from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.api.api_v1.dependencies.auth import get_current_active_user
from app.models.enums import UserRole
from app.schemas.user import User as UserSchema
from app.schemas.visit import (
    VisitCreate, VisitUpdate, Visit, VisitList, VisitReschedule, VisitCancel, VisitSlice
)
from app.schemas.common import PaginatedResponse
from app.services.visit import (
    create_visit, get_visit, get_user_visits, update_visit,
    cancel_visit, reschedule_visit, get_all_visits, mark_visit_completed
)

router = APIRouter()


async def _agent_can_access_visit(
    current_user: UserSchema,
    visit: Visit,
    db: AsyncSession,
) -> bool:
    if current_user.role != UserRole.agent.value or current_user.agent_id is None:
        return False

    from app.models.properties import Property
    from app.models.users import User as UserModel

    visit_user = await db.get(UserModel, visit.user_id)
    property_obj = await db.get(Property, visit.property_id)
    owner = await db.get(UserModel, property_obj.owner_id) if property_obj else None

    return bool(
        (visit_user and visit_user.agent_id == current_user.agent_id)
        or (owner and owner.agent_id == current_user.agent_id)
    )


async def _can_access_visit(
    current_user: UserSchema,
    visit: Visit,
    db: AsyncSession,
) -> bool:
    if visit.user_id == current_user.id:
        return True
    if current_user.role == UserRole.admin.value:
        return True
    return await _agent_can_access_visit(current_user, visit, db)


@router.post("", response_model=Visit)
async def schedule_visit(
    visit: VisitCreate,
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    return await create_visit(db, current_user.id, visit)

@router.get("", response_model=VisitList)
async def get_my_visits(
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    return await get_user_visits(db, current_user.id)

@router.get("/upcoming", response_model=VisitSlice)
async def get_upcoming_visits(
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    from app.services.visit import get_user_upcoming_visits
    return await get_user_upcoming_visits(db, current_user.id)

@router.get("/past", response_model=VisitSlice)
async def get_past_visits(
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    from app.services.visit import get_user_past_visits
    return await get_user_past_visits(db, current_user.id)

@router.get("/{visit_id}", response_model=Visit)
async def get_visit_details(
    visit_id: int,
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    visit = await get_visit(db, visit_id)
    if not visit:
        raise HTTPException(status_code=404, detail="Visit not found")

    if not await _can_access_visit(current_user, visit, db):
        raise HTTPException(status_code=403, detail="Access denied")

    return visit

@router.put("/{visit_id}", response_model=Visit)
async def update_visit_details(
    visit_id: int,
    visit_update: VisitUpdate,
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    visit = await get_visit(db, visit_id)
    if not visit:
        raise HTTPException(status_code=404, detail="Visit not found")
    
    # Check if visit belongs to current user
    if visit.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Access denied")
    
    return await update_visit(db, visit_id, visit_update)

@router.post("/{visit_id}/reschedule", response_model=Visit)
async def reschedule_visit_date(
    visit_id: int,
    reschedule_data: VisitReschedule,
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    visit = await get_visit(db, visit_id)
    if not visit:
        raise HTTPException(status_code=404, detail="Visit not found")
    
    # Check if visit belongs to current user
    if visit.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Access denied")
    
    updated = await reschedule_visit(db, visit_id, reschedule_data.new_date, reschedule_data.reason)
    if not updated:
        raise HTTPException(status_code=400, detail="Failed to reschedule visit")
    return updated

@router.post("/{visit_id}/cancel", response_model=Visit)
async def cancel_visit_request(
    visit_id: int,
    cancel_data: VisitCancel,
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    visit = await get_visit(db, visit_id)
    if not visit:
        raise HTTPException(status_code=404, detail="Visit not found")
    
    # Check if visit belongs to current user
    if visit.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Access denied")
    
    updated = await cancel_visit(db, visit_id, cancel_data.reason)
    if not updated:
        raise HTTPException(status_code=400, detail="Failed to cancel visit")
    return updated


@router.get("/all", response_model=PaginatedResponse)
async def list_all_visits(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    status: str | None = Query(None),
    agent_id: int | None = Query(None, description="Admin only: filter by agent id"),
    property_id: int | None = Query(None),
    user_id: int | None = Query(None),
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """Global visits listing. Admins see all; agents see their managed users/properties."""
    effective_agent_id = None
    if current_user.role == UserRole.admin.value:
        effective_agent_id = agent_id
    elif current_user.role == UserRole.agent.value:
        effective_agent_id = current_user.agent_id
        if effective_agent_id is None:
            return {"items": [], "total": 0, "page": page, "limit": limit, "total_pages": 0, "has_next": False, "has_prev": page > 1}
    else:
        raise HTTPException(status_code=403, detail="Access denied")

    return await get_all_visits(
        db,
        page=page,
        limit=limit,
        status=status,
        filter_agent_id=effective_agent_id,
        property_id=property_id,
        user_id=user_id,
    )


@router.post("/{visit_id}/complete", response_model=Visit)
async def complete_visit(
    visit_id: int,
    payload: dict | None = None,
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """Mark a visit as completed. Admins or responsible Agents only."""
    visit = await get_visit(db, visit_id)
    if not visit:
        raise HTTPException(status_code=404, detail="Visit not found")

    if not await _can_access_visit(current_user, visit, db):
        raise HTTPException(status_code=403, detail="Access denied")

    notes = (payload or {}).get("notes") if payload else None
    feedback = (payload or {}).get("feedback") if payload else None
    ok = await mark_visit_completed(db, visit_id, notes, feedback)
    if not ok:
        raise HTTPException(status_code=400, detail="Failed to complete visit")

    # Return updated visit
    updated = await get_visit(db, visit_id)
    return updated
