from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.api_v1.dependencies.auth import get_current_active_user
from app.core.database import get_db
from app.core.logging import get_logger
from app.models.enums import PropertyPurpose, PropertyType
from app.schemas.common import MessageResponse
from app.schemas.pagination import CursorPage, CursorParams, build_cursor_page
from app.schemas.property import (
    Property,
    PropertySwipe,
    SortBy,
    UnifiedPropertyFilter,
)
from app.schemas.user import User as UserSchema
from app.services.swipe import (
    batch_unswipe,
    get_swipe_history,
    get_swipe_stats,
    record_swipe,
    toggle_swipe,
    undo_last_swipe,
)

logger = get_logger(__name__)

router = APIRouter()

@router.post("", response_model=MessageResponse, summary="Swipe property")
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
        logger.warning("Attempted to swipe non-existent property %s by user %s", swipe.property_id, current_user.id)
        return MessageResponse(message=f"Property {action} successfully")

    logger.debug("Property swipe recorded", extra={"user_id": current_user.id, "property_id": swipe.property_id, "action": action})
    return MessageResponse(message=f"Property {action} successfully")

@router.get("", response_model=CursorPage[Property], summary="List swipe history")
async def get_user_swipe_history(
    # Location-based search
    lat: float | None = Query(None, description="Latitude for location-based search"),
    lng: float | None = Query(None, description="Longitude for location-based search"),
    radius: int = Query(5, ge=1, le=100, description="Search radius in km"),

    # Search query
    q: str | None = Query(None, description="Search query for text search"),

    # Property filters
    property_type: list[PropertyType] | None = Query(None),
    purpose: PropertyPurpose | None = Query(None),

    # Price filters
    price_min: float | None = Query(None, ge=0),
    price_max: float | None = Query(None, le=1e9),

    # Room filters
    bedrooms_min: int | None = Query(None, ge=0),
    bedrooms_max: int | None = Query(None, le=20),
    bathrooms_min: int | None = Query(None, ge=0),
    bathrooms_max: int | None = Query(None, le=10),

    # Area filters
    area_min: float | None = Query(None, ge=0),
    area_max: float | None = Query(None, le=100000),

    # Location filters
    city: str | None = Query(None),
    locality: str | None = Query(None),
    pincode: str | None = Query(None),

    # Additional filters
    amenities: list[str] | None = Query(None),
    features: list[str] | None = Query(None),
    parking_spaces_min: int | None = Query(None, ge=0),
    floor_number_min: int | None = Query(None, ge=0),
    floor_number_max: int | None = Query(None, le=100),
    age_max: int | None = Query(None, ge=0),

    # Short stay filters
    check_in: str | None = Query(None, description="Check-in date (YYYY-MM-DD)"),
    check_out: str | None = Query(None, description="Check-out date (YYYY-MM-DD)"),
    guests: int | None = Query(None, ge=1, le=20),

    # Swipe-specific filters
    is_liked: bool | None = Query(None, description="Filter by liked (true) or disliked (false)"),

    # Sorting
    sort_by: SortBy = Query(SortBy.newest, description="Sort by: distance, price_low, price_high, newest, popular, relevance"),

    # Cursor pagination
    page: CursorParams = Depends(),

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
    - Cursor-based pagination
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
    logger.info(
        "Swipe history search request - user: %s, filters: %s",
        current_user.id,
        len([f for f in [q, lat, lng, property_type, city] if f]),
    )

    try:
        swipes, next_payload, total = await get_swipe_history(
            db,
            current_user.id,
            filters,
            cursor_payload=page.decoded(),
            limit=page.limit,
            is_liked=is_liked,
            with_total=page.include_total,
        )

        logger.info("Swipe history search completed - returning %s properties", len(swipes))

        # Extract properties from swipe objects
        props = []
        for swipe in swipes:
            if swipe.property:
                swipe.property.liked = swipe.is_liked
                props.append(Property.model_validate(swipe.property))

        return build_cursor_page(props, limit=page.limit, next_payload=next_payload, total=total)
    except Exception as e:
        logger.error("Swipe history search failed for user %s: %s", current_user.id, e)
        raise

@router.delete("/undo", response_model=MessageResponse, summary="Undo last swipe")
async def undo_last_swipe_endpoint(
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """Undo the last swipe for the user"""
    undone_swipe = await undo_last_swipe(db, current_user.id)

    if not undone_swipe:
        raise HTTPException(status_code=404, detail="No swipes to undo")

    return MessageResponse(message="Last swipe undone successfully")

@router.put("/{swipe_id}/toggle", response_model=MessageResponse, summary="Toggle swipe like")
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

@router.get("/stats", summary="Get swipe statistics")
async def get_user_swipe_statistics(
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """Get user's swipe statistics"""
    stats = await get_swipe_stats(db, current_user.id)
    return stats


class BatchRemoveRequest(BaseModel):
    property_ids: list[int]


@router.post("/batch-remove", response_model=MessageResponse, summary="Batch remove swipes")
async def batch_remove_swipes(
    payload: BatchRemoveRequest,
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Remove many liked swipes for the current user in a single request."""
    deleted = await batch_unswipe(db, current_user.id, payload.property_ids)
    return MessageResponse(message=f"Removed {deleted} swipes")
