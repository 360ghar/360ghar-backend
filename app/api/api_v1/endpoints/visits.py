from fastapi import APIRouter, Depends, HTTPException, Query
from supabase import Client
from app.core.supabase_client import get_supabase_dependency
from app.api.api_v1.endpoints.auth import get_current_active_user
from app.schemas.user import User as UserSchema
from app.schemas.visit import VisitCreate, VisitUpdate, Visit
from app.services.visit import create_visit, get_user_visits, reschedule_visit, cancel_visit
from app.core.logging import get_logger
from typing import Optional

logger = get_logger(__name__)

router = APIRouter()

@router.get("/", response_model=list[Visit])
async def get_visits(
    visit_type: Optional[str] = Query(None, description="Filter by 'upcoming', 'past', or None for all"),
    current_user: UserSchema = Depends(get_current_active_user),
    supabase: Client = Depends(get_supabase_dependency)
):
    """Get user's visits with optional filter for upcoming or past visits"""
    return await get_user_visits(supabase, current_user.id, visit_type=visit_type)

@router.post("/", response_model=Visit)
async def create_new_visit(
    visit: VisitCreate,
    current_user: UserSchema = Depends(get_current_active_user),
    supabase: Client = Depends(get_supabase_dependency)
):
    """Create a new property visit - requires property_id and scheduled_date"""
    # Add user_id from current user
    visit_data = visit.model_dump()
    visit_data['user_id'] = current_user.id
    
    # Create visit object
    visit_with_user = VisitCreate(**visit_data)
    result = await create_visit(supabase, visit_with_user)
    logger.info("Visit created successfully", extra={"user_id": current_user.id, "property_id": visit.property_id, "visit_id": result.id})
    return result

@router.patch("/{visit_id}")
async def update_visit(
    visit_id: int,
    visit_update: VisitUpdate,
    supabase: Client = Depends(get_supabase_dependency),
    current_user: UserSchema = Depends(get_current_active_user)
):
    """Reschedule or cancel a visit"""
    if visit_update.scheduled_date:
        # Reschedule visit
        result = await reschedule_visit(supabase, visit_id, visit_update.scheduled_date.isoformat())
        if not result:
            raise HTTPException(status_code=404, detail="Visit not found or failed to reschedule")
        return result
    elif visit_update.cancellation_reason:
        # Cancel visit
        result = await cancel_visit(supabase, visit_id, visit_update.cancellation_reason)
        if not result:
            raise HTTPException(status_code=404, detail="Visit not found or failed to cancel")
        return result
    else:
        raise HTTPException(status_code=400, detail="Either scheduled_date for reschedule or cancellation_reason for cancel must be provided")