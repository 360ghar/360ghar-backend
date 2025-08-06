from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional, List
from app.core.database import get_db
from app.api.api_v1.endpoints.auth import get_current_active_user, get_current_user_optional
from app.models.user import User
from app.models.property import PropertyType, PropertyPurpose
from app.schemas.property import (
    PropertyCreate, PropertyUpdate, Property, PropertyFilter,
    PropertyInterest, UnifiedPropertyFilter, UnifiedPropertyResponse
)
from app.schemas.common import PaginationParams, PaginatedResponse, MessageResponse
from app.services.property import (
    create_property, get_property, get_properties, update_property,
    delete_property, get_properties_for_discovery, get_properties_nearby,
    record_property_interest, get_property_recommendations, get_unified_properties,
    get_unified_properties_optimized
)
from app.repositories.property import PropertyRepository
from app.core.cache import PropertyCacheManager

router = APIRouter()

@router.post("/", response_model=Property)
async def create_new_property(
    property_data: PropertyCreate,
    db: AsyncSession = Depends(get_db)
):
    return await create_property(db, property_data)

@router.get("/", response_model=UnifiedPropertyResponse)
async def get_properties_list(
    # Query parameters for filtering
    lat: Optional[float] = Query(None, description="Latitude for location-based search"),
    lng: Optional[float] = Query(None, description="Longitude for location-based search"),
    radius: int = Query(5, ge=1, le=100, description="Search radius in km"),
    
    # Search query
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
    sort_by: str = Query("distance", description="Sort by: distance, price_low, price_high, newest, popular, relevance"),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    
    # Optional authentication
    current_user: Optional[User] = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db)
):
    """
    Get properties with comprehensive filtering and optional authentication.
    
    This endpoint supports:
    - Location-based search (lat/lng + radius)
    - Text search (q parameter)
    - Comprehensive property filtering
    - Multiple sorting options
    - Optional user authentication (excludes swiped properties if authenticated)
    """
    # Build filters
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
        sort_by=sort_by
    )
    
    # Use user_id if authenticated, otherwise use -1 (no filtering)
    user_id = current_user.id if current_user else -1
    
    # Check cache first
    cached_result = await PropertyCacheManager.get_cached_properties(
        filters.model_dump(exclude_none=True), user_id, page, limit
    )
    if cached_result:
        return cached_result
    
    # Use optimized method
    result = await get_unified_properties_optimized(db, filters, user_id, page, limit)
    
    # Cache for 5 minutes
    await PropertyCacheManager.cache_properties(
        filters.model_dump(exclude_none=True), user_id, page, limit, result, ttl=300
    )
    
    return result

@router.get("/recommendations")
async def get_recommendations(
    current_user: Optional[User] = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
    limit: int = Query(10, ge=1, le=50)
):
    """
    Get property recommendations with optional authentication.
    
    - With authentication: Personalized recommendations based on user preferences and swipes
    - Without authentication: Popular properties based on likes and recency
    """
    user_id = current_user.id if current_user else None
    return await get_property_recommendations(db, user_id, limit)

@router.get("/{property_id}", response_model=Property)
async def get_property_details(
    property_id: int,
    current_user: Optional[User] = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db)
):
    """
    Get property details with optional authentication.
    
    - With authentication: Records analytics and returns property details
    - Without authentication: Returns property details only
    """
    property_obj = await get_property(db, property_id)
    if not property_obj:
        raise HTTPException(status_code=404, detail="Property not found")
    
    # Record property view for analytics only if user is authenticated
    if current_user:
        from app.services.analytics import record_property_view
        await record_property_view(db, current_user.id, property_id)
    
    return property_obj

@router.put("/{property_id}", response_model=Property)
async def update_property_details(
    property_id: int,
    property_update: PropertyUpdate,
    db: AsyncSession = Depends(get_db)
):
    property_obj = await update_property(db, property_id, property_update)
    if not property_obj:
        raise HTTPException(status_code=404, detail="Property not found")
    return property_obj

@router.delete("/{property_id}", response_model=MessageResponse)
async def delete_property_by_id(
    property_id: int,
    db: AsyncSession = Depends(get_db)
):
    success = await delete_property(db, property_id)
    if not success:
        raise HTTPException(status_code=404, detail="Property not found")
    return MessageResponse(message="Property deleted successfully")

@router.post("/interest", response_model=MessageResponse)
async def show_interest_in_property(
    interest: PropertyInterest,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    await record_property_interest(db, current_user.id, interest)
    return MessageResponse(message="Interest recorded successfully")

@router.get("/{property_id}/share")
async def get_property_share_data(
    property_id: int,
    db: AsyncSession = Depends(get_db)
):
    property_obj = await get_property(db, property_id)
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
async def check_property_availability(
    property_id: int,
    check_in_date: str = Query(..., description="Check-in date (YYYY-MM-DD)"),
    check_out_date: str = Query(..., description="Check-out date (YYYY-MM-DD)"),
    guests: int = Query(1, ge=1, description="Number of guests"),
    db: AsyncSession = Depends(get_db)
):
    from app.services.booking import check_availability
    return await check_availability(db, property_id, check_in_date, check_out_date, guests)

@router.post("/batch", response_model=List[Property])
async def get_properties_batch(
    property_ids: List[int],
    current_user: Optional[User] = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db)
):
    """Get multiple properties by IDs in a single request"""
    if len(property_ids) > 50:
        raise HTTPException(status_code=400, detail="Maximum 50 properties per batch")
    
    property_repo = PropertyRepository(db)
    properties = []
    
    for property_id in property_ids:
        property_obj = await property_repo.get_with_images(property_id)
        if property_obj:
            properties.append(property_obj)
    
    return properties