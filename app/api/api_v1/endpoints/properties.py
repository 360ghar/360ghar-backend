from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.api_v1.dependencies.auth import (
    get_current_active_user,
    get_current_cached_active_user,
    get_current_user_optional,
)
from app.config import settings
from app.core.database import get_db
from app.core.db_resilience import (
    apply_statement_timeout,
    extract_db_error_code,
    is_statement_timeout,
    is_transient_db_error,
)
from app.core.exceptions import ServiceUnavailableException
from app.core.logging import get_logger
from app.models.enums import (
    FurnishingLevel,
    KitchenType,
    ListingGenderPreference,
    ListingSharingType,
    MoveInTimeline,
    PropertyPurpose,
    PropertyStatus,
    PropertyType,
    UserRole,
    VentilationType,
)
from app.models.users import User as UserModel
from app.schemas.pagination import CursorPage, CursorParams, build_cursor_page
from app.schemas.property import (
    BASE_PRICE_MAX,
    Property,
    PropertyCreate,
    PropertyDetail,
    PropertyUpdate,
    SortBy,
    UnifiedPropertyFilter,
)
from app.schemas.user import User as UserSchema
from app.services.auth_user_cache import AuthUserSnapshot
from app.services.content.property_summary import generate_property_content
from app.services.flatmates import pause_stale_flatmate_listings
from app.services.flatmates.compatibility import calculate_property_compatibility_score
from app.services.property import (
    attach_owner_agents,
    create_property,
    delete_property,
    get_property,
    get_property_recommendations,
    increment_property_view_count,
    list_user_properties,
    update_property,
)
from app.services.property.search_orchestration import (
    build_property_search_filters,
    run_property_search,
)
from app.services.swipe import get_user_like_for_property
from app.services.visibility import mask_owner_contact, mask_owner_contacts
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


def _filter_binding(filters: UnifiedPropertyFilter) -> dict[str, Any]:
    """The request filters a cursor is bound to. The same dict goes to decoded() and build_cursor_page()."""
    return filters.model_dump(mode="json", exclude_none=True)


def _query_filter_errors(exc: ValidationError) -> list[dict[str, Any]]:
    """Filter-model errors name their query parameter (query.<name>). A range pair
    (min above max) has no single parameter, so its error is named "query"."""
    errors: list[dict[str, Any]] = []
    for err in exc.errors(include_url=False, include_context=False, include_input=False):
        loc = err.get("loc") or ()
        errors.append({**err, "loc": ("query", *loc)})
    return errors


def build_property_filters(
    # Query parameters for filtering
    lat: float | None = Query(
        None, ge=-90, le=90, description="Latitude for location-based search"
    ),
    lng: float | None = Query(
        None, ge=-180, le=180, description="Longitude for location-based search"
    ),
    radius: int = Query(5, ge=1, le=100, description="Search radius in km"),
    # Search query
    q: str | None = Query(None, description="Search query for text or semantic search"),
    semantic_search: bool = Query(False, description="Enable semantic vector similarity search"),
    # Property filters
    ids: list[int] | None = Query(None, description="Filter by property IDs"),
    property_type: list[PropertyType] | None = Query(None),
    purpose: PropertyPurpose | None = Query(None),
    # Price filters
    price_min: float | None = Query(None, ge=0, le=BASE_PRICE_MAX),
    price_max: float | None = Query(None, ge=0, le=BASE_PRICE_MAX),
    # Room filters
    bedrooms_min: int | None = Query(None, ge=0, le=50),
    bedrooms_max: int | None = Query(None, ge=0, le=50),
    bathrooms_min: int | None = Query(None, ge=0, le=50),
    bathrooms_max: int | None = Query(None, ge=0, le=50),
    # Area filters
    area_min: float | None = Query(None, ge=0, le=1_000_000),
    area_max: float | None = Query(None, ge=0, le=1_000_000),
    # Listing status (admin lists; public lists show available listings)
    status: PropertyStatus | None = Query(None, description="Listing status"),
    # Location filters
    city: str | None = Query(None),
    locality: str | None = Query(None, description="Exact locality name (case-insensitive)"),
    sub_locality: str | None = Query(
        None, description="Exact sub-locality name (case-insensitive)"
    ),
    pincode: str | None = Query(None),
    society_type: str | None = Query(None, description="Exact society type (case-insensitive)"),
    society_vibe_tags: list[str] | None = Query(
        None, description="Listings that carry every given society vibe tag"
    ),
    # Additional filters
    amenities: list[str] | None = Query(None),
    features: list[str] | None = Query(None),
    furnishing: list[FurnishingLevel] | None = Query(
        None, description="Furnishing levels: furnished, semi_furnished, unfurnished"
    ),
    kitchen_type: list[KitchenType] | None = Query(
        None, description="Kitchen types: vegetarian, non_vegetarian, eggetarian, any"
    ),
    ventilation_type: list[VentilationType] | None = Query(
        None, description="Ventilation: good, average, poor"
    ),
    windows_min: int | None = Query(None, ge=0, le=100, description="Minimum window count"),
    has_lift: bool | None = Query(None, description="Require a lift amenity"),
    gender_preference: ListingGenderPreference | None = Query(None),
    sharing_type: ListingSharingType | None = Query(None),
    available_from: date | None = Query(None, description="Minimum availability date (YYYY-MM-DD)"),
    move_in: MoveInTimeline | None = Query(
        None,
        description="Move-in timeline. flexible applies no filter.",
    ),
    parking_spaces_min: int | None = Query(None, ge=0, le=100),
    floor_number_min: int | None = Query(None, ge=-5, le=200),
    floor_number_max: int | None = Query(None, ge=-5, le=200),
    age_max: int | None = Query(None, ge=0, le=500),
    # Short stay filters
    check_in: date | None = Query(None, description="Check-in date (YYYY-MM-DD)"),
    check_out: date | None = Query(None, description="Check-out date (YYYY-MM-DD)"),
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
    try:
        return build_property_search_filters(
            latitude=lat,
            longitude=lng,
            radius_km=radius,
            search_query=q,
            semantic_search=semantic_search,
            property_ids=ids,
            property_type=property_type,
            purpose=purpose,
            status=status,
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
            sub_locality=sub_locality,
            pincode=pincode,
            society_type=society_type,
            society_vibe_tags=society_vibe_tags,
            amenities=amenities,
            features=features,
            furnishing=furnishing,
            kitchen_type=kitchen_type,
            ventilation_type=ventilation_type,
            windows_min=windows_min,
            has_lift=has_lift,
            gender_preference=gender_preference,
            sharing_type=sharing_type,
            available_from=available_from,
            move_in=move_in,
            parking_spaces_min=parking_spaces_min,
            floor_number_min=floor_number_min,
            floor_number_max=floor_number_max,
            age_max=age_max,
            check_in_date=check_in.isoformat() if check_in else None,
            check_out_date=check_out.isoformat() if check_out else None,
            guests=guests,
            sort_by=sort_by,
            exclude_swiped=exclude_swiped,
        )
    except ValidationError as exc:
        raise RequestValidationError(_query_filter_errors(exc)) from exc


@router.post(
    "",
    response_model=Property,
    status_code=201,
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
                        "buy": {
                            "value": {
                                "title": "3BHK Villa in Whitefield",
                                "property_type": "villa",
                                "purpose": "buy",
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
    background_tasks: BackgroundTasks,
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
        background_tasks.add_task(generate_property_content, result.id)
        await attach_owner_agents(db, [result])
        return mask_owner_contact(result, current_user)
    except Exception as e:
        logger.error("Failed to create property for user %s: %s", current_user.id, e)
        raise


@router.get("/me", response_model=CursorPage[Property], summary="List my properties")
async def get_my_properties(
    page: CursorParams = Depends(),
    current_user: AuthUserSnapshot = Depends(get_current_cached_active_user),
    db: AsyncSession = Depends(get_db),
):
    """List properties owned by the current user (requires authentication)."""
    binding: dict[str, Any] = {"scope": "owner"}
    cursor_payload = page.decoded(binding)
    rows, next_payload, total = await list_user_properties(
        db,
        owner_id=current_user.id,
        cursor_payload=cursor_payload,
        limit=page.limit,
        with_total=page.include_total,
    )
    await attach_owner_agents(db, rows)
    return build_cursor_page(
        mask_owner_contacts(rows, current_user),
        limit=page.limit,
        next_payload=next_payload,
        total=total,
        filters=binding,
    )


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
    user_id = current_user.id if current_user else None

    binding = _filter_binding(filters)
    cursor_payload = page.decoded(binding)
    logger.info(
        "Property search request",
        extra={
            "user": user_id or "anonymous",
            "has_semantic": filters.semantic_search,
            "query": filters.search_query,
            "radius": filters.radius_km,
        },
    )

    rows, next_payload, total = await run_property_search(
        db,
        filters,
        user_id,
        cursor_payload,
        page.limit,
        with_total=page.include_total,
        endpoint_name="get_properties_list",
        stale_listing_context="property browse",
        unavailable_detail="Property search is temporarily unavailable. Please retry shortly.",
    )

    logger.info(
        "Property search completed — found %s properties",
        len(rows),
    )

    return build_cursor_page(
        mask_owner_contacts(rows, current_user),
        limit=page.limit,
        next_payload=next_payload,
        total=total,
        filters=binding,
    )


@router.get(
    "/semantic-search", response_model=CursorPage[Property], summary="Semantic property search"
)
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
    user_id = current_user.id if current_user else None

    logger.info(
        "Semantic property search request",
        extra={"user": user_id or "anonymous", "query": filters.search_query},
    )

    binding = _filter_binding(filters)
    cursor_payload = page.decoded(binding)
    rows, next_payload, total = await run_property_search(
        db,
        filters,
        user_id,
        cursor_payload,
        page.limit,
        with_total=page.include_total,
        semantic_required=True,
        force_semantic_relevance=True,
        endpoint_name="semantic_property_search",
        stale_listing_context="semantic search",
        unavailable_detail="Semantic search is temporarily unavailable. Please retry shortly.",
    )
    return build_cursor_page(
        mask_owner_contacts(rows, current_user),
        limit=page.limit,
        next_payload=next_payload,
        total=total,
        filters=binding,
    )


@router.get(
    "/recommendations", response_model=CursorPage[Property], summary="List recommended properties"
)
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
    # Personalised ranking differs per viewer, so the cursor is bound to the viewer.
    binding: dict[str, Any] = (
        {"scope": "user", "viewer": user_id} if user_id else {"scope": "anonymous"}
    )
    try:
        await apply_statement_timeout(db, settings.DB_READ_STATEMENT_TIMEOUT_MS)
        cursor_payload = page.decoded(binding)
        try:
            await pause_stale_flatmate_listings(db)
        except Exception as cleanup_exc:
            logger.warning("Skipping stale-listing pause during recommendations: %s", cleanup_exc)
            await db.rollback()
            await apply_statement_timeout(db, settings.DB_READ_STATEMENT_TIMEOUT_MS)

        rows, next_payload, total = await get_property_recommendations(
            db,
            user_id,
            cursor_payload,
            page.limit,
            with_total=page.include_total,
        )
        return build_cursor_page(
            mask_owner_contacts(rows, current_user),
            limit=page.limit,
            next_payload=next_payload,
            total=total,
            filters=binding,
        )
    except Exception as e:
        if is_transient_db_error(e) or is_statement_timeout(e):
            error_code = extract_db_error_code(e) or (
                "STATEMENT_TIMEOUT" if is_statement_timeout(e) else "TRANSIENT_DB_ERROR"
            )
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


@router.get("/{property_id}", response_model=PropertyDetail, summary="Get property details")
async def get_property_details(
    property_id: int,
    request: Request,
    current_user: UserModel | None = Depends(get_current_user_optional),
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
            async with db.begin_nested():
                await increment_property_view_count(db, property_id)
        except Exception as view_exc:  # noqa: BLE001
            logger.warning("View count increment failed for %s: %s", property_id, view_exc)

    # The detail response carries the viewer's own visit fields. Other responses do not.
    detail = property_data

    # If user is authenticated, enrich with user-specific context
    if current_user:
        try:
            async with db.begin_nested():
                # Liked status (True/False/None)
                liked = await get_user_like_for_property(db, current_user.id, property_id)
                # Upcoming visit stats
                visit_stats = await get_user_property_visit_stats(db, current_user.id, property_id)

            compatibility_score = None
            if property_data.owner_id is not None and property_data.owner_id != current_user.id:
                owner = await db.get(UserModel, property_data.owner_id)
                if owner is not None:
                    compatibility_score = calculate_property_compatibility_score(
                        current_user, owner
                    )

            detail = detail.model_copy(
                update={
                    "liked": bool(liked) if liked is not None else None,
                    "user_has_scheduled_visit": visit_stats["count"] > 0,
                    "user_scheduled_visit_count": visit_stats["count"],
                    "user_next_visit_date": visit_stats["next_date"],
                    "compatibility_score": compatibility_score,
                }
            )
        except Exception as e:
            # Log and continue without blocking property details
            logger.error("Failed to enrich property %s with user context: %s", property_id, e)

    return mask_owner_contact(detail, current_user)


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
                                "status": "available",
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
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: UserSchema = Depends(get_current_active_user),
):
    """Update property details (PATCH semantics: send only the keys to change)."""
    result = await update_property(db, property_id, property_update, current_user)
    background_tasks.add_task(generate_property_content, property_id)
    await attach_owner_agents(db, [result])
    return mask_owner_contact(result, current_user)


@router.delete(
    "/{property_id}", status_code=204, response_class=Response, summary="Delete property"
)
async def delete_property_endpoint(
    property_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: UserSchema = Depends(get_current_active_user),
) -> Response:
    """Delete a property. Returns 204 with no body."""
    await delete_property(db, property_id, current_user)
    return Response(status_code=204)
