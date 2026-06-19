from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.api_v1.dependencies.auth import get_current_active_user, get_current_user_optional
from app.core.database import get_db
from app.core.db_resilience import extract_db_error_code, is_transient_db_error
from app.core.exceptions import ServiceUnavailableException
from app.core.logging import get_logger
from app.models.enums import (
    ListingGenderPreference,
    ListingSharingType,
    PropertyPurpose,
    PropertyType,
    UserRole,
)
from app.schemas.pagination import CursorPage, CursorParams, build_cursor_page
from app.schemas.property import (
    Property,
    PropertyCreate,
    PropertyUpdate,
    SortBy,
    UnifiedPropertyFilter,
)
from app.schemas.user import User as UserSchema
from app.services.flatmates import pause_expired_flatmate_listings
from app.services.property import (
    create_property,
    delete_property,
    get_property,
    get_property_recommendations,
    get_unified_properties_optimized,
    increment_property_view_count,
    list_user_properties,
    update_property,
)
from app.services.swipe import get_user_like_for_property
from app.services.visit import get_user_property_visit_stats

router = APIRouter()
logger = get_logger(__name__)

# User-agent tokens for known crawlers. Detail-page views by these bots should
# not count toward view totals, and skipping the per-view write keeps the
# detail GET side-effect free (so it can be cached cleanly at the edge).
_BOT_USER_AGENT_TOKENS = (
    "bot",
    "crawler",
    "spider",
    "slurp",
    "bingpreview",
    "preview",
    "facebookexternalhit",
    "twitterbot",
    "linkedinbot",
    "whatsapp",
    "telegram",
    "applebot",
    "yandex",
    "baidu",
    "bytespider",
    "gptbot",
    "claudebot",
    "ccbot",
    "perplexitybot",
    "google-structured-data",
    "googlebot",
)


def _is_bot_user_agent(user_agent: str | None) -> bool:
    """Heuristic: True if the User-Agent looks like a crawler."""
    if not user_agent:
        return False
    lowered = user_agent.lower()
    return any(token in lowered for token in _BOT_USER_AGENT_TOKENS)


def build_property_filters(
    # Query parameters for filtering
    lat: float | None = Query(None, description="Latitude for location-based search"),
    lng: float | None = Query(None, description="Longitude for location-based search"),
    radius: int = Query(5, ge=1, le=100, description="Search radius in km"),
    # Search query
    q: str | None = Query(None, description="Search query for text or semantic search"),
    semantic_search: bool = Query(False, description="Enable semantic vector similarity search"),
    # Property filters
    ids: list[int] | None = Query(None, description="Filter by property IDs"),
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
    gender_preference: ListingGenderPreference | None = Query(None),
    sharing_type: ListingSharingType | None = Query(None),
    available_from: str | None = Query(None, description="Minimum availability date (YYYY-MM-DD)"),
    move_in: str | None = Query(
        None,
        description="Move-in timeline: immediate, this_month, next_month, flexible",
    ),
    parking_spaces_min: int | None = Query(None, ge=0),
    floor_number_min: int | None = Query(None, ge=0),
    floor_number_max: int | None = Query(None, le=100),
    age_max: int | None = Query(None, ge=0),
    # Short stay filters
    check_in: str | None = Query(None, description="Check-in date (YYYY-MM-DD)"),
    check_out: str | None = Query(None, description="Check-out date (YYYY-MM-DD)"),
    guests: int | None = Query(None, ge=1, le=20),
    # Sorting
    sort_by: SortBy = Query(
        SortBy.newest,
        description="Sort by: distance, price_low, price_high, newest, popular, relevance",
    ),
    # Auth-aware filters
    exclude_swiped: bool = Query(
        False, description="Exclude properties already swiped by the authenticated user"
    ),
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
        gender_preference=gender_preference,
        sharing_type=sharing_type,
        available_from=available_from,
        move_in=move_in,
        parking_spaces_min=parking_spaces_min,
        floor_number_min=floor_number_min,
        floor_number_max=floor_number_max,
        age_max=age_max,
        check_in_date=check_in,
        check_out_date=check_out,
        guests=guests,
        sort_by=sort_by,
        exclude_swiped=exclude_swiped,
        semantic_search=semantic_search,
    )


@router.post(
    "",
    response_model=Property,
    summary="Create property",
    openapi_extra={
        "requestBody": {
            "content": {
                "application/json": {
                    "examples": {
                        "rent": {
                            "value": {
                                "title": "2BHK Apartment in Koramangala",
                                "property_type": "apartment",
                                "purpose": "rent",
                                "base_price": 50000,
                                "monthly_rent": 25000,
                                "city": "Bengaluru",
                                "locality": "Koramangala",
                                "bedrooms": 2,
                                "bathrooms": 2,
                                "area_sqft": 1200,
                            }
                        },
                        "sale": {
                            "value": {
                                "title": "3BHK Villa in Whitefield",
                                "property_type": "villa",
                                "purpose": "sale",
                                "base_price": 12500000,
                                "city": "Bengaluru",
                                "locality": "Whitefield",
                                "bedrooms": 3,
                                "bathrooms": 3,
                                "area_sqft": 1800,
                            }
                        },
                    }
                }
            }
        }
    },
)
async def create_new_property(
    property_data: PropertyCreate,
    owner_id: int | None = Query(None, description="Owner id (admin/agent only)"),
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new property (requires authentication)"""
    logger.info(
        "User %s creating property of type %s", current_user.id, property_data.property_type
    )
    try:
        # Determine owner
        target_owner_id = current_user.id
        if owner_id is not None:
            # Only admins/agents may specify owner_id
            if current_user.role in (UserRole.admin.value, UserRole.agent.value):
                target_owner_id = owner_id
            else:
                raise HTTPException(
                    status_code=403, detail="Only admins or agents can set owner_id"
                )
        result = await create_property(db, property_data, target_owner_id, current_user)
        logger.info("Property created successfully with ID %s", result.id)
        return result
    except Exception as e:
        logger.error("Failed to create property for user %s: %s", current_user.id, e)
        raise


@router.get("/me", response_model=CursorPage[Property], summary="List my properties")
async def get_my_properties(
    page: CursorParams = Depends(),
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """List properties owned by the current user (requires authentication)."""
    cursor_payload = page.decoded()
    rows, next_payload, total = await list_user_properties(
        db,
        owner_id=current_user.id,
        cursor_payload=cursor_payload,
        limit=page.limit,
        with_total=page.include_total,
    )
    return build_cursor_page(rows, limit=page.limit, next_payload=next_payload, total=total)


@router.get("", response_model=CursorPage[Property], summary="List properties")
async def get_properties_list(
    filters: UnifiedPropertyFilter = Depends(build_property_filters),
    page: CursorParams = Depends(),
    current_user: UserSchema | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
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

    user_id = current_user.id if current_user else None

    cursor_payload = page.decoded()
    logger.info(
        "Property search request",
        extra={
            "user": user_id or "anonymous",
            "has_semantic": filters.semantic_search,
            "query": filters.search_query,
            "offset": cursor_payload.get("o", 0),
            "radius": filters.radius_km,
        },
    )

    try:
        await pause_expired_flatmate_listings(db)
        rows, next_payload, total = await get_unified_properties_optimized(
            db, filters, user_id, cursor_payload, page.limit,
            with_total=page.include_total,
        )

        logger.info(
            "Property search completed — found %s properties",
            len(rows),
        )

        return build_cursor_page(rows, limit=page.limit, next_payload=next_payload, total=total)
    except Exception as e:
        if is_transient_db_error(e):
            error_code = extract_db_error_code(e) or "TRANSIENT_DB_ERROR"
            logger.error(
                "Property search transient DB failure",
                extra={
                    "endpoint": "get_properties_list",
                    "user": user_id or "anonymous",
                    "error_code": error_code,
                },
                exc_info=True,
            )
            raise ServiceUnavailableException(
                detail="Property search is temporarily unavailable. Please retry shortly.",
                details={"error_code": error_code, "endpoint": "get_properties_list"},
            ) from e
        logger.error("Property search failed for user %s: %s", user_id or "anonymous", e)
        raise


@router.get("/semantic-search", response_model=CursorPage[Property], summary="Semantic property search")
async def semantic_property_search(
    filters: UnifiedPropertyFilter = Depends(build_property_filters),
    page: CursorParams = Depends(),
    current_user: UserSchema | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    """
    Perform semantic (vector-powered) property search.
    Combines vector similarity with traditional filters and returns relevance scores.
    """
    if not filters.search_query:
        raise HTTPException(
            status_code=400, detail="A search query (q) is required for semantic search"
        )

    filters.semantic_search = True
    filters.sort_by = SortBy.relevance
    user_id = current_user.id if current_user else None

    logger.info(
        "Semantic property search request",
        extra={"user": user_id or "anonymous", "query": filters.search_query},
    )

    try:
        cursor_payload = page.decoded()
        await pause_expired_flatmate_listings(db)
        rows, next_payload, total = await get_unified_properties_optimized(
            db, filters, user_id, cursor_payload, page.limit,
            with_total=page.include_total,
        )
        return build_cursor_page(rows, limit=page.limit, next_payload=next_payload, total=total)
    except Exception as e:
        if is_transient_db_error(e):
            error_code = extract_db_error_code(e) or "TRANSIENT_DB_ERROR"
            logger.error(
                "Semantic property search transient DB failure",
                extra={"endpoint": "semantic_property_search", "error_code": error_code},
                exc_info=True,
            )
            raise ServiceUnavailableException(
                detail="Semantic search is temporarily unavailable. Please retry shortly.",
                details={"error_code": error_code, "endpoint": "semantic_property_search"},
            ) from e
        raise


@router.get("/recommendations", response_model=CursorPage[Property], summary="List recommended properties")
async def get_recommendations(
    page: CursorParams = Depends(),
    current_user: UserSchema | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    """
    Get property recommendations with optional authentication.

    - With authentication: Personalized recommendations based on user preferences and swipes
    - Without authentication: Popular properties based on likes and recency

    Note: `total` is always null for recommendations (no cheap COUNT query).
    Pass `include_total=true` to request it, but the service does not compute it
    and will return `null`.
    """
    user_id = current_user.id if current_user else None
    try:
        cursor_payload = page.decoded()
        await pause_expired_flatmate_listings(db)
        rows, next_payload, total = await get_property_recommendations(
            db, user_id, cursor_payload, page.limit,
            with_total=page.include_total,
        )
        return build_cursor_page(rows, limit=page.limit, next_payload=next_payload, total=total)
    except Exception as e:
        if is_transient_db_error(e):
            error_code = extract_db_error_code(e) or "TRANSIENT_DB_ERROR"
            logger.error(
                "Property recommendations transient DB failure",
                extra={
                    "endpoint": "get_recommendations",
                    "user": user_id or "anonymous",
                    "error_code": error_code,
                },
                exc_info=True,
            )
            raise ServiceUnavailableException(
                detail="Recommendations are temporarily unavailable. Please retry shortly.",
                details={"error_code": error_code, "endpoint": "get_recommendations"},
            ) from e
        raise


@router.get("/{property_id}", response_model=Property, summary="Get property details")
async def get_property_details(
    property_id: int,
    request: Request,
    current_user: UserSchema | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    """Get property details"""
    property_data = await get_property(db, property_id)
    if property_data.property_type in {PropertyType.flatmate, PropertyType.pg}:
        prefs = (
            property_data.listing_preferences.model_dump()
            if property_data.listing_preferences
            else {}
        )
        moderation_status = prefs.get("moderation_status") or "live"
        is_owner = current_user is not None and current_user.id == property_data.owner_id
        is_admin = current_user is not None and current_user.role == UserRole.admin.value
        if moderation_status != "live" and not (is_owner or is_admin):
            raise HTTPException(status_code=404, detail="Property not found")

    # Increment view count (best-effort, skipped for crawlers so the GET stays
    # read-only and cacheable). A failure here must never break the response.
    if not _is_bot_user_agent(request.headers.get("user-agent")):
        try:
            await increment_property_view_count(db, property_id)
        except Exception as view_exc:  # noqa: BLE001
            logger.warning("View count increment failed for %s: %s", property_id, view_exc)

    # If user is authenticated, enrich with user-specific context
    if current_user:
        try:
            # Liked status (True/False/None)
            liked = await get_user_like_for_property(db, current_user.id, property_id)
            # Upcoming visit stats
            visit_stats = await get_user_property_visit_stats(db, current_user.id, property_id)
            property_data = property_data.model_copy(
                update={
                    "liked": bool(liked) if liked is not None else None,
                    "user_has_scheduled_visit": visit_stats["count"] > 0,
                    "user_scheduled_visit_count": visit_stats["count"],
                    "user_next_visit_date": visit_stats["next_date"],
                }
            )
        except Exception as e:
            # Log and continue without blocking property details
            logger.error("Failed to enrich property %s with user context: %s", property_id, e)

    return property_data


@router.put(
    "/{property_id}",
    response_model=Property,
    summary="Update property",
    openapi_extra={
        "requestBody": {
            "content": {
                "application/json": {
                    "examples": {
                        "update": {
                            "value": {
                                "title": "Updated 2BHK Apartment in Koramangala",
                                "monthly_rent": 28000,
                                "status": "active",
                            }
                        },
                    }
                }
            }
        }
    },
)
async def update_property_details(
    property_id: int,
    property_update: PropertyUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: UserSchema = Depends(get_current_active_user),
):
    """Update property details"""
    return await update_property(db, property_id, property_update, current_user)


@router.delete("/{property_id}", summary="Delete property")
async def delete_property_endpoint(
    property_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: UserSchema = Depends(get_current_active_user),
):
    """Delete a property"""
    await delete_property(db, property_id, current_user)
    return {"message": "Property deleted successfully"}
