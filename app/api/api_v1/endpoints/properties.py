from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import Optional, List
from app.core.database import get_db
from app.api.api_v1.endpoints.auth import get_current_active_user
from app.models.user import User
from app.schemas.property import (
    PropertyCreate, PropertyUpdate, Property, PropertyFilter,
    PropertyInterest, UnifiedPropertyFilter, UnifiedPropertyResponse
)
from app.schemas.common import PaginationParams, PaginatedResponse, MessageResponse
from app.services.property import (
    create_property, get_property, get_properties, update_property,
    delete_property, get_properties_for_discovery, get_properties_nearby,
    record_property_interest, get_property_recommendations, get_unified_properties
)

router = APIRouter()

@router.post("/", response_model=Property)
def create_new_property(
    property_data: PropertyCreate,
    db: Session = Depends(get_db)
):
    return create_property(db, property_data)

@router.post("/search", response_model=UnifiedPropertyResponse)
def search_properties(
    filters: UnifiedPropertyFilter,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
    pagination: PaginationParams = Depends()
):
    return get_unified_properties(db, filters, current_user.id, pagination.page, pagination.limit)

@router.get("/recommendations")
def get_recommendations(
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
    limit: int = Query(10, ge=1, le=50)
):
    return get_property_recommendations(db, current_user.id, limit)

@router.get("/{property_id}", response_model=Property)
def get_property_details(
    property_id: int,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    property_obj = get_property(db, property_id)
    if not property_obj:
        raise HTTPException(status_code=404, detail="Property not found")
    
    # Record property view for analytics
    from app.services.analytics import record_property_view
    record_property_view(db, current_user.id, property_id)
    
    return property_obj

@router.put("/{property_id}", response_model=Property)
def update_property_details(
    property_id: int,
    property_update: PropertyUpdate,
    db: Session = Depends(get_db)
):
    property_obj = update_property(db, property_id, property_update)
    if not property_obj:
        raise HTTPException(status_code=404, detail="Property not found")
    return property_obj

@router.delete("/{property_id}", response_model=MessageResponse)
def delete_property_by_id(
    property_id: int,
    db: Session = Depends(get_db)
):
    success = delete_property(db, property_id)
    if not success:
        raise HTTPException(status_code=404, detail="Property not found")
    return MessageResponse(message="Property deleted successfully")

@router.post("/interest", response_model=MessageResponse)
def show_interest_in_property(
    interest: PropertyInterest,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    record_property_interest(db, current_user.id, interest)
    return MessageResponse(message="Interest recorded successfully")

@router.get("/{property_id}/share")
def get_property_share_data(
    property_id: int,
    db: Session = Depends(get_db)
):
    property_obj = get_property(db, property_id)
    if not property_obj:
        raise HTTPException(status_code=404, detail="Property not found")
    
    share_data = {
        "title": property_obj.title,
        "description": property_obj.description[:200] + "..." if len(property_obj.description) > 200 else property_obj.description,
        "image": property_obj.main_image_url,
        "url": f"https://360ghar.com/property/{property_id}",
        "price": property_obj.base_price,
        "location": property_obj.location.name if property_obj.location else "Unknown"
    }
    
    return share_data

@router.get("/{property_id}/availability")
def check_property_availability(
    property_id: int,
    check_in_date: str = Query(..., description="Check-in date (YYYY-MM-DD)"),
    check_out_date: str = Query(..., description="Check-out date (YYYY-MM-DD)"),
    guests: int = Query(1, ge=1, description="Number of guests"),
    db: Session = Depends(get_db)
):
    from app.services.booking import check_availability
    return check_availability(db, property_id, check_in_date, check_out_date, guests)