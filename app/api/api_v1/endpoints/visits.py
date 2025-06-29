from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
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
def schedule_visit(
    visit: VisitCreate,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    return create_visit(db, current_user.id, visit)

@router.get("/", response_model=VisitList)
def get_my_visits(
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    return get_user_visits(db, current_user.id)

@router.get("/upcoming")
def get_upcoming_visits(
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    from app.services.visit import get_user_upcoming_visits
    return get_user_upcoming_visits(db, current_user.id)

@router.get("/past")
def get_past_visits(
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    from app.services.visit import get_user_past_visits
    return get_user_past_visits(db, current_user.id)

@router.get("/relationship-manager", response_model=RelationshipManager)
def get_my_relationship_manager(
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    rm = get_user_relationship_manager(db, current_user.id)
    if not rm:
        raise HTTPException(status_code=404, detail="Relationship manager not assigned")
    return rm

@router.get("/{visit_id}", response_model=Visit)
def get_visit_details(
    visit_id: int,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    visit = get_visit(db, visit_id)
    if not visit:
        raise HTTPException(status_code=404, detail="Visit not found")
    
    # Check if visit belongs to current user
    if visit.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Access denied")
    
    return visit

@router.put("/{visit_id}", response_model=Visit)
def update_visit_details(
    visit_id: int,
    visit_update: VisitUpdate,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    visit = get_visit(db, visit_id)
    if not visit:
        raise HTTPException(status_code=404, detail="Visit not found")
    
    # Check if visit belongs to current user
    if visit.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Access denied")
    
    return update_visit(db, visit_id, visit_update)

@router.post("/reschedule", response_model=MessageResponse)
def reschedule_visit_date(
    reschedule_data: VisitReschedule,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    visit = get_visit(db, reschedule_data.visit_id)
    if not visit:
        raise HTTPException(status_code=404, detail="Visit not found")
    
    # Check if visit belongs to current user
    if visit.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Access denied")
    
    success = reschedule_visit(db, reschedule_data.visit_id, reschedule_data.new_date, reschedule_data.reason)
    if not success:
        raise HTTPException(status_code=400, detail="Failed to reschedule visit")
    
    return MessageResponse(message="Visit rescheduled successfully")

@router.post("/cancel", response_model=MessageResponse)
def cancel_visit_request(
    cancel_data: VisitCancel,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    visit = get_visit(db, cancel_data.visit_id)
    if not visit:
        raise HTTPException(status_code=404, detail="Visit not found")
    
    # Check if visit belongs to current user
    if visit.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Access denied")
    
    success = cancel_visit(db, cancel_data.visit_id, cancel_data.reason)
    if not success:
        raise HTTPException(status_code=400, detail="Failed to cancel visit")
    
    return MessageResponse(message="Visit cancelled successfully")