from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional, List
from app.core.database import get_db
from app.api.api_v1.endpoints.auth import get_current_active_user
from app.models.user import User
from app.schemas.property import PropertySwipe, UnifiedPropertyFilter, UnifiedPropertyResponse, SortBy
from app.models.property import PropertyType, PropertyPurpose
from app.schemas.common import MessageResponse
from app.services.swipe import record_swipe, get_swipe_history_properties

router = APIRouter()

@router.post("/", response_model=MessageResponse)
async def swipe_property(
    swipe: PropertySwipe,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    await record_swipe(db, current_user.id, swipe)
    
    action = "liked" if swipe.is_liked else "passed"
    return MessageResponse(message=f"Property {action} successfully")

@router.get("/history", response_model=UnifiedPropertyResponse)
async def get_user_swipe_history(
    # Location-based
    lat: Optional[float] = Query(None, description="Latitude for location-based search"),
    lng: Optional[float] = Query(None, description="Longitude for location-based search"),
    radius: int = Query(5, ge=1, le=100, description="Search radius in km"),

    # Text search
    q: Optional[str] = Query(None, description="Search query for text search"),

    # Property filters
    property_type: Optional[List[PropertyType]] = Query(None),
    purpose: Optional[PropertyPurpose] = Query(None),

    # Price filters
    price_min: Optional[float] = Query(None, ge=0),
    price_max: Optional[float] = Query(None, le=1e9),

    # Room filters
    bedrooms_min: Optional[int] = Query(None, ge=0),
    bedrooms_max: Optional[int] = Query(None, le=20),
    bathrooms_min: Optional[int] = Query(None, ge=0),
    bathrooms_max: Optional[int] = Query(None, le=10),

    # Area filters
    area_min: Optional[float] = Query(None, ge=0),
    area_max: Optional[float] = Query(None, le=100000),

    # Location filters
    city: Optional[str] = Query(None),
    locality: Optional[str] = Query(None),
    pincode: Optional[str] = Query(None),

    # Additional filters
    amenities: Optional[List[str]] = Query(None),
    parking_spaces_min: Optional[int] = Query(None, ge=0),
    floor_number_min: Optional[int] = Query(None, ge=0),
    floor_number_max: Optional[int] = Query(None, le=100),
    age_max: Optional[int] = Query(None, ge=0),

    # Short stay filters
    check_in: Optional[str] = Query(None, description="Check-in date (YYYY-MM-DD)"),
    check_out: Optional[str] = Query(None, description="Check-out date (YYYY-MM-DD)"),
    guests: Optional[int] = Query(None, ge=1, le=20),

    # Sorting and pagination
    sort_by: SortBy = Query(SortBy.distance, description="Sort by: distance, price_low, price_high, newest, popular, relevance"),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),

    # Swipe-specific
    is_liked: Optional[bool] = Query(None, description="Filter by liked (true) or passed (false)"),

    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    filters = UnifiedPropertyFilter(
        latitude=lat,
        longitude=lng,
        radius_km=radius,
        search_query=q,
        property_type=property_type,
        purpose=purpose,
        price_min=price_min,
        price_max=price_max,
        bedrooms_min=bedrooms_min,
        bedrooms_max=bedrooms_max,
        bathrooms_min=bathrooms_min,
        bathrooms_max=bathrooms_max,
        area_min=area_min,
        area_max=area_max,
        city=city,
        locality=locality,
        pincode=pincode,
        amenities=amenities,
        parking_spaces_min=parking_spaces_min,
        floor_number_min=floor_number_min,
        floor_number_max=floor_number_max,
        age_max=age_max,
        check_in_date=check_in,
        check_out_date=check_out,
        guests=guests,
        sort_by=sort_by,
    )
    return await get_swipe_history_properties(
        db=db,
        user_id=current_user.id,
        filters=filters,
        page=page,
        limit=limit,
        is_liked=is_liked,
    )

@router.get("/stats")
async def get_swipe_stats(
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    from app.services.analytics import get_user_swipe_stats
    return await get_user_swipe_stats(db, current_user.id)

@router.post("/undo", response_model=MessageResponse)
async def undo_last_swipe(
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    from app.services.swipe import undo_last_swipe
    success = await undo_last_swipe(db, current_user.id)
    
    if not success:
        raise HTTPException(status_code=400, detail="No recent swipe to undo")
    
    return MessageResponse(message="Last swipe undone successfully")