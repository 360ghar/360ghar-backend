from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.api.api_v1.endpoints.auth import get_current_active_user
from app.models.user import User
from app.schemas.visit import (
    VisitCreate, VisitUpdate, Visit, VisitList, VisitReschedule, VisitCancel,
    RelationshipManager
)
from app.schemas.common import MessageResponse
from app.services.visit import (
    create_visit, get_visit, get_user_visits, update_visit,
    cancel_visit, reschedule_visit, get_user_relationship_manager
)

router = APIRouter()

@router.post("/", response_model=Visit)
async def schedule_visit(
    visit: VisitCreate,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    return await create_visit(db, current_user.id, visit)

@router.get("/", response_model=VisitList)
async def get_my_visits(
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    return await get_user_visits(db, current_user.id)

@router.get("/upcoming")
async def get_upcoming_visits(
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    from app.services.visit import get_user_upcoming_visits
    return await get_user_upcoming_visits(db, current_user.id)

@router.get("/past")
async def get_past_visits(
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    from app.services.visit import get_user_past_visits
    return await get_user_past_visits(db, current_user.id)

@router.get("/relationship-manager", response_model=RelationshipManager)
async def get_my_relationship_manager(
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    rm = await get_user_relationship_manager(db, current_user.id)
    if not rm:
        raise HTTPException(status_code=404, detail="Relationship manager not assigned")
    return rm

@router.get("/{visit_id}", response_model=Visit)
async def get_visit_details(
    visit_id: int,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    visit = await get_visit(db, visit_id)
    if not visit:
        raise HTTPException(status_code=404, detail="Visit not found")
    
    # Check if visit belongs to current user
    if visit.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Access denied")
    
    return visit

@router.put("/{visit_id}", response_model=Visit)
async def update_visit_details(
    visit_id: int,
    visit_update: VisitUpdate,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    visit = await get_visit(db, visit_id)
    if not visit:
        raise HTTPException(status_code=404, detail="Visit not found")
    
    # Check if visit belongs to current user
    if visit.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Access denied")
    
    return await update_visit(db, visit_id, visit_update)

@router.post("/reschedule", response_model=MessageResponse)
async def reschedule_visit_date(
    reschedule_data: VisitReschedule,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    visit = await get_visit(db, reschedule_data.visit_id)
    if not visit:
        raise HTTPException(status_code=404, detail="Visit not found")
    
    # Check if visit belongs to current user
    if visit.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Access denied")
    
    success = await reschedule_visit(db, reschedule_data.visit_id, reschedule_data.new_date, reschedule_data.reason)
    if not success:
        raise HTTPException(status_code=400, detail="Failed to reschedule visit")
    
    return MessageResponse(message="Visit rescheduled successfully")

@router.post("/cancel", response_model=MessageResponse)
async def cancel_visit_request(
    cancel_data: VisitCancel,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    visit = await get_visit(db, cancel_data.visit_id)
    if not visit:
        raise HTTPException(status_code=404, detail="Visit not found")
    
    # Check if visit belongs to current user
    if visit.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Access denied")
    
    success = await cancel_visit(db, cancel_data.visit_id, cancel_data.reason)
    if not success:
        raise HTTPException(status_code=400, detail="Failed to cancel visit")
    
    return MessageResponse(message="Visit cancelled successfully")