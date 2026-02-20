from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional, List
from app.core.database import get_db
from app.core.logging import get_logger
from app.api.api_v1.dependencies.auth import get_current_active_user, get_current_user_optional
from app.schemas.user import User as UserSchema
from app.models.enums import PropertyType, PropertyPurpose, UserRole
from app.schemas.property import (
    PropertyCreate, PropertyUpdate, Property, PropertyFilter,
    PropertyInterest, UnifiedPropertyFilter, UnifiedPropertyResponse, SortBy
)
from app.schemas.common import PaginationParams, PaginatedResponse, MessageResponse
from app.services.property import (
    create_property, get_property, update_property,
    delete_property, get_property_recommendations,
    get_unified_properties_optimized, increment_property_view_count,
    list_user_properties,
)
from app.services.visit import get_user_property_visit_stats
from app.services.swipe import get_user_like_for_property

router = APIRouter()
logger = get_logger(__name__)


def build_property_filters(
    # Query parameters for filtering
    lat: Optional[float] = Query(None, description="Latitude for location-based search"),
    lng: Optional[float] = Query(None, description="Longitude for location-based search"),
    radius: int = Query(5, ge=1, le=100, description="Search radius in km"),
    
    # Search query
    q: Optional[str] = Query(None, description="Search query for text or semantic search"),
    semantic_search: bool = Query(False, description="Enable semantic vector similarity search"),
    
    # Property filters
    ids: Optional[List[int]] = Query(None, description="Filter by property IDs"),
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
    
    # Sorting
    sort_by: SortBy = Query(SortBy.newest, description="Sort by: distance, price_low, price_high, newest, popular, relevance"),
    
    # Auth-aware filters
    exclude_swiped: bool = Query(False, description="Exclude properties already swiped by the authenticated user"),
):
    """Common dependency to build UnifiedPropertyFilter from query params."""
    return UnifiedPropertyFilter(
        latitude=lat,
        longitude=lng,
        radius_km=radius,
        search_query=q,
        property_ids=ids,
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
        sort_by=sort_by,
        exclude_swiped=exclude_swiped,
        semantic_search=semantic_search
    )


def _build_response_payload(result: dict, filters: UnifiedPropertyFilter, page: int, limit: int):
    return {
        "properties": result.get("items", []),
        "total": result.get("total", 0),
        "page": page,
        "limit": limit,
        "total_pages": result.get("total_pages", 0),
        "filters_applied": filters.model_dump(exclude_none=True),
        "search_center": ({"latitude": filters.latitude, "longitude": filters.longitude} if filters.latitude is not None and filters.longitude is not None else None)
    }

@router.post("", response_model=Property)
async def create_new_property(
    property_data: PropertyCreate,
    owner_id: Optional[int] = Query(None, description="Owner id (admin/agent only)"),
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """Create a new property (requires authentication)"""
    logger.info(f"User {current_user.id} creating property of type {property_data.property_type}")
    try:
        # Determine owner
        target_owner_id = current_user.id
        if owner_id is not None:
            # Only admins/agents may specify owner_id
            if current_user.role in (UserRole.admin.value, UserRole.agent.value):
                target_owner_id = owner_id
            else:
                raise HTTPException(status_code=403, detail="Only admins or agents can set owner_id")
        result = await create_property(db, property_data, target_owner_id, current_user)
        logger.info(f"Property created successfully with ID {result.id}")
        return result
    except Exception as e:
        logger.error(f"Failed to create property for user {current_user.id}: {str(e)}")
        raise


@router.get("/me", response_model=List[Property])
async def get_my_properties(
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """List properties owned by the current user (requires authentication)."""
    return await list_user_properties(db, owner_id=current_user.id)

@router.get("", response_model=UnifiedPropertyResponse)
async def get_properties_list(
    filters: UnifiedPropertyFilter = Depends(build_property_filters),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    current_user: Optional[UserSchema] = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db)
):
    """
    Get properties with comprehensive filtering and optional authentication.
    
    This endpoint supports:
    - Location-based search (lat/lng + radius)
    - Text search (q parameter) and optional semantic search (`semantic_search=true`)
    - Comprehensive property filtering
    - Multiple sorting options
    - Optional user authentication
    - Auth-aware filter: exclude swiped properties when `exclude_swiped=true`
    """
    if filters.semantic_search and not filters.search_query:
        raise HTTPException(status_code=400, detail="semantic_search requires a search query (q)")
    
    # Use user_id if authenticated, otherwise use None
    user_id = current_user.id if current_user else None
    
    # Log search request
    logger.info(
        "Property search request",
        extra={
            "user": user_id or "anonymous",
            "has_semantic": filters.semantic_search,
            "query": filters.search_query,
            "page": page,
            "radius": filters.radius_km,
        },
    )
    
    try:
        result = await get_unified_properties_optimized(db, filters, user_id, page, limit)
        
        logger.info(f"Property search completed - found {result.get('total', 0)} properties, returning page {page}")
        
        return _build_response_payload(result, filters, page, limit)
    except Exception as e:
        logger.error(f"Property search failed for user {user_id or 'anonymous'}: {str(e)}")
        raise


@router.get("/semantic-search", response_model=UnifiedPropertyResponse)
async def semantic_property_search(
    filters: UnifiedPropertyFilter = Depends(build_property_filters),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    current_user: Optional[UserSchema] = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db)
):
    """
    Perform semantic (vector-powered) property search.
    Combines vector similarity with traditional filters and returns relevance scores.
    """
    if not filters.search_query:
        raise HTTPException(status_code=400, detail="A search query (q) is required for semantic search")

    filters.semantic_search = True
    filters.sort_by = SortBy.relevance
    user_id = current_user.id if current_user else None
    
    logger.info(
        "Semantic property search request",
        extra={"user": user_id or "anonymous", "query": filters.search_query, "page": page},
    )

    result = await get_unified_properties_optimized(db, filters, user_id, page, limit)
    return _build_response_payload(result, filters, page, limit)

@router.get("/recommendations")
async def get_recommendations(
    current_user: Optional[UserSchema] = Depends(get_current_user_optional),
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
    current_user: Optional[UserSchema] = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db)
):
    """Get property details"""
    property_data = await get_property(db, property_id)
    
    # Increment view count
    await increment_property_view_count(db, property_id)

    # If user is authenticated, enrich with user-specific context
    if current_user:
        try:
            # Liked status (True/False/None)
            liked = await get_user_like_for_property(db, current_user.id, property_id)
            # Upcoming visit stats
            visit_stats = await get_user_property_visit_stats(db, current_user.id, property_id)
            property_data = property_data.model_copy(update={
                "liked": bool(liked) if liked is not None else None,
                "user_has_scheduled_visit": visit_stats["count"] > 0,
                "user_scheduled_visit_count": visit_stats["count"],
                "user_next_visit_date": visit_stats["next_date"],
            })
        except Exception as e:
            # Log and continue without blocking property details
            logger.error(f"Failed to enrich property {property_id} with user context: {str(e)}")

    return property_data

@router.put("/{property_id}", response_model=Property)
async def update_property_details(
    property_id: int,
    property_update: PropertyUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: UserSchema = Depends(get_current_active_user)
):
    """Update property details"""
    return await update_property(db, property_id, property_update, current_user)

@router.delete("/{property_id}")
async def delete_property_endpoint(
    property_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: UserSchema = Depends(get_current_active_user)
):
    """Delete a property"""
    await delete_property(db, property_id, current_user)
    return {"message": "Property deleted successfully"}
