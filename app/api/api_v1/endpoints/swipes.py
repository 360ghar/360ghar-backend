from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional, List
from app.core.database import get_db
from app.api.api_v1.dependencies.auth import get_current_active_user
from app.schemas.property import PropertySwipe, UnifiedPropertyFilter, UnifiedPropertyResponse, SortBy, SwipeHistoryResponse
from app.schemas.user import User as UserSchema
from app.models.enums import PropertyType, PropertyPurpose
from app.schemas.common import MessageResponse
from app.services.swipe import record_swipe, get_swipe_history, undo_last_swipe, get_swipe_stats, toggle_swipe
from app.core.logging import get_logger

logger = get_logger(__name__)

router = APIRouter()

@router.post("", response_model=MessageResponse)
async def swipe_property(
    swipe: PropertySwipe,
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """Record a property swipe (like/dislike)"""
    success = await record_swipe(db, current_user.id, swipe)
    
    action = "liked" if swipe.is_liked else "passed"
    
    if not success:
        # Property doesn't exist, but we return success to avoid client errors
        logger.warning(f"Attempted to swipe non-existent property {swipe.property_id} by user {current_user.id}")
        return MessageResponse(message=f"Property {action} successfully")
    
    logger.debug("Property swipe recorded", extra={"user_id": current_user.id, "property_id": swipe.property_id, "action": action})
    return MessageResponse(message=f"Property {action} successfully")

@router.get("", response_model=SwipeHistoryResponse)
async def get_user_swipe_history(
    # Location-based search
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
    features: Optional[List[str]] = Query(None),
    parking_spaces_min: Optional[int] = Query(None, ge=0),
    floor_number_min: Optional[int] = Query(None, ge=0),
    floor_number_max: Optional[int] = Query(None, le=100),
    age_max: Optional[int] = Query(None, ge=0),

    # Short stay filters
    check_in: Optional[str] = Query(None, description="Check-in date (YYYY-MM-DD)"),
    check_out: Optional[str] = Query(None, description="Check-out date (YYYY-MM-DD)"),
    guests: Optional[int] = Query(None, ge=1, le=20),

    # Swipe-specific filters
    is_liked: Optional[bool] = Query(None, description="Filter by liked (true) or disliked (false)"),

    # Sorting and pagination
    sort_by: SortBy = Query(SortBy.newest, description="Sort by: distance, price_low, price_high, newest, popular, relevance"),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),

    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Get user's swipe history with comprehensive filtering and property details.

    This endpoint supports:
    - Location-based search (lat/lng + radius)
    - Text search (q parameter)
    - Comprehensive property filtering
    - Multiple sorting options
    - Swipe-specific filters (liked/disliked)
    - Pagination
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
        features=features,
        parking_spaces_min=parking_spaces_min,
        floor_number_min=floor_number_min,
        floor_number_max=floor_number_max,
        age_max=age_max,
        check_in_date=check_in,
        check_out_date=check_out,
        guests=guests,
        sort_by=sort_by
    )

    # Log search request
    logger.info(f"Swipe history search request - user: {current_user.id}, filters: {len([f for f in [q, lat, lng, property_type, city] if f])}, page: {page}")

    try:
        result = await get_swipe_history(db, current_user.id, filters, page, limit, is_liked)

        logger.info(f"Swipe history search completed - found {result.get('total', 0)} properties, returning page {page}")

        # Extract properties from swipe objects and ensure they have the liked attribute
        swipes = result.get("items", [])
        properties = []
        for swipe in swipes:
            if swipe.property:
                # Ensure the liked attribute is set
                swipe.property.liked = swipe.is_liked
                properties.append(swipe.property)

        # Adapt repository response to SwipeHistoryResponse shape
        return {
            "properties": properties,
            "total": result.get("total", 0),
            "page": page,
            "limit": limit,
            "total_pages": result.get("total_pages", 0),
            "filters_applied": filters.model_dump(exclude_none=True),
            "search_center": ({"latitude": lat, "longitude": lng} if lat is not None and lng is not None else None)
        }
    except Exception as e:
        logger.error(f"Swipe history search failed for user {current_user.id}: {str(e)}")
        raise

@router.delete("/undo", response_model=MessageResponse)
async def undo_last_swipe_endpoint(
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """Undo the last swipe for the user"""
    undone_swipe = await undo_last_swipe(db, current_user.id)
    
    if not undone_swipe:
        raise HTTPException(status_code=404, detail="No swipes to undo")
    
    return MessageResponse(message="Last swipe undone successfully")

@router.put("/{swipe_id}/toggle", response_model=MessageResponse)
async def toggle_swipe_like(
    swipe_id: int,
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """Toggle the like status of an existing swipe"""
    result = await toggle_swipe(db, swipe_id, current_user.id)
    
    if not result:
        raise HTTPException(status_code=404, detail="Swipe not found or does not belong to user")
    
    action = "liked" if result["new_status"] else "unliked"
    return MessageResponse(message=f"Property {action} successfully")

@router.get("/stats")
async def get_user_swipe_statistics(
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """Get user's swipe statistics"""
    stats = await get_swipe_stats(db, current_user.id)
    return stats
