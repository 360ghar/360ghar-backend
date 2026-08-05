"""Shared orchestration for property search entrypoints."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.db_resilience import (
    apply_statement_timeout,
    extract_db_error_code,
    is_statement_timeout,
    is_transient_db_error,
)
from app.core.exceptions import BadRequestException, ServiceUnavailableException
from app.core.logging import get_logger
from app.models.enums import (
    ListingGenderPreference,
    ListingSharingType,
    PropertyPurpose,
    PropertyType,
)
from app.schemas.property import Property as PropertySchema
from app.schemas.property import SortBy, UnifiedPropertyFilter
from app.services.flatmates import pause_stale_flatmate_listings
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
    pincode: str | None = None,
    amenities: list[str] | None = None,
    features: list[str] | None = None,
    furnishing: list[str] | None = None,
    kitchen_type: list[str] | None = None,
    ventilation_type: list[str] | None = None,
    windows_min: int | None = None,
    has_lift: bool | None = None,
    gender_preference: ListingGenderPreference | None = None,
    sharing_type: ListingSharingType | None = None,
    available_from: str | None = None,
    move_in: str | None = None,
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
    stale_listing_context: str = "property browse",
    unavailable_detail: str = "Property search is temporarily unavailable. Please retry shortly.",
) -> tuple[list[PropertySchema], dict | None, int | None]:
    """Run shared property search request orchestration.

    Query construction and SQL execution stay in ``property.search``. This
    wrapper owns cross-surface concerns: semantic guards, request statement
    timeout, best-effort stale listing cleanup, and retryable DB error mapping.
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
        # Bound every statement in this read request so a stalled DB backend
        # fails fast instead of holding a pooler connection for the server
        # default timeout.
        await apply_statement_timeout(db, settings.DB_READ_STATEMENT_TIMEOUT_MS)

        # Stale-listing pause is a best-effort cleanup write; it must never
        # break browsing. If it stalls/fails, roll back the aborted transaction
        # and continue to the read-only search.
        try:
            await pause_stale_flatmate_listings(db)
        except Exception as cleanup_exc:
            logger.warning(
                "Skipping stale-listing pause during %s: %s",
                stale_listing_context,
                cleanup_exc,
            )
            await db.rollback()
            await apply_statement_timeout(db, settings.DB_READ_STATEMENT_TIMEOUT_MS)

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
                },
                exc_info=True,
            )
            raise ServiceUnavailableException(
                detail=unavailable_detail,
                details={"error_code": error_code, "endpoint": endpoint_name},
            ) from exc
        raise
