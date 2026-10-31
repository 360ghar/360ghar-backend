"""Shared orchestration for property search entrypoints."""

from __future__ import annotations

from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db_resilience import (
    extract_db_error_code,
    is_pool_exhaustion_error,
    is_statement_timeout,
    is_transient_db_error,
    read_db_retry_after,
)
from app.core.exceptions import BadRequestException, ServiceUnavailableException
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
    VentilationType,
)
from app.schemas.property import Property as PropertySchema
from app.schemas.property import SortBy, UnifiedPropertyFilter
from app.services.property.search import get_unified_properties_optimized

logger = get_logger(__name__)


def build_property_search_filters(
    *,
    latitude: float | None = None,
    longitude: float | None = None,
    radius_km: int = 5,
    search_query: str | None = None,
    semantic_search: bool = False,
    property_ids: list[int] | None = None,
    property_type: list[PropertyType] | None = None,
    purpose: PropertyPurpose | None = None,
    status: PropertyStatus | None = None,
    price_min: float | None = None,
    price_max: float | None = None,
    bedrooms_min: int | None = None,
    bedrooms_max: int | None = None,
    bathrooms_min: int | None = None,
    bathrooms_max: int | None = None,
    area_min: float | None = None,
    area_max: float | None = None,
    city: str | None = None,
    locality: str | None = None,
    sub_locality: str | None = None,
    pincode: str | None = None,
    society_type: str | None = None,
    society_vibe_tags: list[str] | None = None,
    amenities: list[str] | None = None,
    features: list[str] | None = None,
    furnishing: list[FurnishingLevel] | None = None,
    kitchen_type: list[KitchenType] | None = None,
    ventilation_type: list[VentilationType] | None = None,
    windows_min: int | None = None,
    has_lift: bool | None = None,
    gender_preference: ListingGenderPreference | None = None,
    sharing_type: ListingSharingType | None = None,
    available_from: date | None = None,
    move_in: MoveInTimeline | None = None,
    parking_spaces_min: int | None = None,
    floor_number_min: int | None = None,
    floor_number_max: int | None = None,
    age_max: int | None = None,
    check_in_date: str | None = None,
    check_out_date: str | None = None,
    guests: int | None = None,
    sort_by: SortBy = SortBy.newest,
    exclude_swiped: bool = False,
) -> UnifiedPropertyFilter:
    """Build a UnifiedPropertyFilter from shared property-search inputs."""
    return UnifiedPropertyFilter(
        latitude=latitude,
        longitude=longitude,
        radius_km=radius_km,
        search_query=search_query,
        property_ids=property_ids,
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
        check_in_date=check_in_date,
        check_out_date=check_out_date,
        guests=guests,
        sort_by=sort_by,
        exclude_swiped=exclude_swiped,
        semantic_search=semantic_search,
    )


async def run_property_search(
    db: AsyncSession,
    filters: UnifiedPropertyFilter,
    user_id: int | None,
    cursor_payload: dict,
    limit: int,
    *,
    with_total: bool = False,
    semantic_required: bool = False,
    force_semantic_relevance: bool = False,
    endpoint_name: str = "property_search",
    unavailable_detail: str = "Property search is temporarily unavailable. Please retry shortly.",
) -> tuple[list[PropertySchema], dict | None, int | None]:
    """Run shared property search request orchestration.

    Query construction and SQL execution stay in ``property.search``. This
    wrapper owns cross-surface concerns: semantic guards and retryable DB
    error mapping.

    Deliberately does **not** write to the database. The stale-listing pause
    used to run here on every browse/search/recommendation request, opening a
    transaction (and a Supavisor client) before the cache check; it now runs
    from the nightly cron endpoint ``POST /flatmates/maintenance/pause-stale-listings``.
    """
    if semantic_required and not filters.search_query:
        raise BadRequestException(detail="A search query (q) is required for semantic search")
    if filters.semantic_search and not filters.search_query:
        raise BadRequestException(detail="semantic_search requires a search query (q)")

    if force_semantic_relevance:
        filters = filters.model_copy(
            update={
                "semantic_search": True,
                "sort_by": SortBy.relevance,
            }
        )

    try:
        rows, next_payload, total = await get_unified_properties_optimized(
            db,
            filters,
            user_id,
            cursor_payload,
            limit,
            with_total=with_total,
        )
        return rows, next_payload, total
    except Exception as exc:
        if is_transient_db_error(exc) or is_statement_timeout(exc):
            error_code = extract_db_error_code(exc) or (
                "STATEMENT_TIMEOUT" if is_statement_timeout(exc) else "TRANSIENT_DB_ERROR"
            )
            logger.error(
                "Property search transient DB failure",
                extra={
                    "endpoint": endpoint_name,
                    "user": user_id or "anonymous",
                    "error_code": error_code,
                    "event": "db_pool_exhausted" if is_pool_exhaustion_error(exc) else "db_transient_error",
                },
                exc_info=True,
            )
            raise ServiceUnavailableException(
                detail=unavailable_detail,
                headers={"Retry-After": str(read_db_retry_after(exc))},
                details={"error_code": error_code, "endpoint": endpoint_name},
            ) from exc
        raise
