"""
Centralized property filter and sort query builder.

Every Property-targeted query (search and list, semantic search, recommendations,
swipe history, MCP discovery) builds its filters here. Prefer this builder over
reimplementing filters inline.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, time, timedelta, timezone, tzinfo
from typing import Any

from sqlalchemy import Float, cast, false, func, or_, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.core.db_resilience import execute_with_transient_retry
from app.core.exceptions import ValidationException
from app.core.logging import get_logger
from app.models.enums import (
    PG_FLATMATE_TYPES,
    BookingStatus,
    KitchenType,
    MoveInTimeline,
)
from app.models.properties import Amenity, Property, PropertyAmenity
from app.schemas.property import SortBy, UnifiedPropertyFilter
from app.utils.geo import city_match_names, escape_like_pattern

logger = get_logger(__name__)

# All users are in India. Day boundaries for move-in windows use IST (UTC+5:30), so the
# server matches the client's local-day semantics (00:30 IST is still "today" locally).
IST_TZ = timezone(timedelta(hours=5, minutes=30), name="Asia/Kolkata")

# Lift-equipped listings carry either amenity row. The seed ships both with the same icon.
_LIFT_AMENITY_TITLES = ["lift", "elevator"]


def property_ts_vector_column() -> ColumnElement[Any]:
    """Return the trigger-maintained indexed FTS column for property search."""
    return Property.__table__.c["__ts_vector__"]


def _day_start(value: datetime, tz: tzinfo = IST_TZ) -> datetime:
    """Midnight in [tz] for the instant [value]."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    value = value.astimezone(tz)
    return datetime(value.year, value.month, value.day, tzinfo=tz)


def _next_month_start(value: datetime) -> datetime:
    month = value.month + 1
    year = value.year
    if month == 13:
        month = 1
        year += 1
    return datetime(year, month, 1, tzinfo=value.tzinfo or UTC)


def move_in_window(
    move_in: MoveInTimeline | str | None,
    *,
    now: datetime | None = None,
) -> tuple[datetime | None, datetime] | None:
    """(start, end) availability window for a move-in timeline, or None for no filter.

    A listing matches when its available_from falls in [start, end). Rolling windows
    ("within N weeks or months") count N * 7 or N * 30 days from today.
    """
    if move_in is None:
        return None
    value = MoveInTimeline(move_in)
    if value == MoveInTimeline.flexible:
        return None

    today = _day_start(now or datetime.now(UTC))
    if value in (MoveInTimeline.immediate, MoveInTimeline.within_1_week):
        return None, today + timedelta(days=8)
    if value == MoveInTimeline.within_2_weeks:
        return None, today + timedelta(days=15)
    if value == MoveInTimeline.this_month:
        return None, _next_month_start(today)
    if value == MoveInTimeline.next_month:
        start = _next_month_start(today)
        return start, _next_month_start(start)
    if value == MoveInTimeline.within_1_month:
        return None, today + timedelta(days=30)
    if value == MoveInTimeline.within_2_months:
        return None, today + timedelta(days=60)
    return None, today + timedelta(days=90)  # within_3_months


def available_from_minimum(available_from: date | None) -> datetime | None:
    """Start of the given day in IST. Listings available from that day or later match."""
    if available_from is None:
        return None
    return _day_start(datetime.combine(available_from, time.min))


def _parse_stay_date(value: str, field: str) -> datetime:
    try:
        return datetime.combine(date.fromisoformat(value), time.min)
    except ValueError as exc:
        raise ValidationException(detail=f"{field} must be a date in YYYY-MM-DD format") from exc


class PropertyQueryBuilder:
    """Builds SQLAlchemy where-clauses and order-by expressions from a UnifiedPropertyFilter.

    Usage::

        builder = PropertyQueryBuilder(filters)
        conditions, distance_expr, search_meta = await builder.build(db)

        # conditions can be applied to any query that targets Property
        query = query.where(and_(*conditions))
        query = builder.apply_sort(
            query,
            sort_by=filters.sort_by or SortBy.newest,
            distance_expr=distance_expr,
            text_rank_expr=search_meta.get("text_rank_expr"),
        )
    """

    def __init__(self, filters: UnifiedPropertyFilter) -> None:
        self.filters = filters

    async def build(
        self,
        db: AsyncSession,
        *,
        include_unavailable: bool = False,
        hard_filter_text: bool = True,
        viewer_id: int | None = None,
        viewer_is_admin: bool = False,
    ) -> tuple[
        list[Any],  # conditions
        Any | None,  # distance_expr (SQLAlchemy column)
        dict[str, Any],  # search_meta: {search_query_obj, search_vector, text_rank_expr}
    ]:
        """Build and return all filter components.

        ``viewer_id`` enables ``exclude_swiped``. Callers that show the viewer's own swipes
        (swipe history) leave it unset, so those swipes stay in the result.

        Returns (conditions, distance_expr, search_meta).
        """
        f = self.filters
        conditions: list[Any] = []

        # --- availability (parity with main property search / swipe history) ---
        if not include_unavailable:
            # Only an admin with an explicit status lists unavailable listings (admin
            # counts of sold and rented depend on this). Every other caller sees available
            # listings, whatever status it asks for.
            if f.status is None or not viewer_is_admin:
                conditions.append(Property.is_available)
            conditions.append(
                or_(
                    Property.property_type.notin_(PG_FLATMATE_TYPES),
                    func.coalesce(
                        Property.listing_preferences["moderation_status"].as_string(),
                        "live",
                    )
                    == "live",
                )
            )

        # --- location / geo ---
        distance_expr = self._build_geo_conditions(f, conditions)

        # --- full-text search ---
        search_meta = self._build_fts_conditions(f, conditions, hard_filter_text=hard_filter_text)

        # --- property IDs / type / purpose / status ---
        if f.property_ids:
            conditions.append(Property.id.in_(f.property_ids))
        if f.property_type:
            conditions.append(Property.property_type.in_(f.property_type))
        if f.purpose:
            conditions.append(Property.purpose == f.purpose)
        if f.status is not None:
            conditions.append(Property.status == f.status)

        # --- price range ---
        if f.price_min is not None:
            conditions.append(Property.base_price >= f.price_min)
        if f.price_max is not None:
            conditions.append(Property.base_price <= f.price_max)

        # --- bedrooms / bathrooms / area ---
        if f.bedrooms_min is not None:
            conditions.append(Property.bedrooms >= f.bedrooms_min)
        if f.bedrooms_max is not None:
            conditions.append(Property.bedrooms <= f.bedrooms_max)
        if f.bathrooms_min is not None:
            conditions.append(Property.bathrooms >= f.bathrooms_min)
        if f.bathrooms_max is not None:
            conditions.append(Property.bathrooms <= f.bathrooms_max)
        if f.area_min is not None:
            conditions.append(Property.area_sqft >= f.area_min)
        if f.area_max is not None:
            conditions.append(Property.area_sqft <= f.area_max)

        # --- city / locality / pincode / society ---
        # Match canonical city + all aliases (e.g. Gurgaon/Gurugram). LIKE so
        # "New Delhi" still matches "Delhi"; alias sets keep Gurugram out of Delhi.
        if f.city:
            match_names = city_match_names(f.city)
            city_clauses = [
                func.lower(Property.city).like(
                    f"%{escape_like_pattern(name.lower())}%",
                    escape="\\",
                )
                for name in match_names
            ]
            if len(city_clauses) == 1:
                conditions.append(city_clauses[0])
            elif city_clauses:
                conditions.append(or_(*city_clauses))
        if f.locality:
            # Exact match, case-insensitive: "Sector 8" must not match "Sector 81".
            conditions.append(func.lower(Property.locality) == f.locality.strip().lower())
        if f.sub_locality:
            conditions.append(func.lower(Property.sub_locality) == f.sub_locality.strip().lower())
        if f.pincode:
            conditions.append(Property.pincode == f.pincode)
        listing_preferences_json = cast(Property.listing_preferences, JSONB)
        if f.society_type:
            conditions.append(
                func.lower(listing_preferences_json["society_type"].astext)
                == f.society_type.strip().lower()
            )
        for tag in f.society_vibe_tags or []:
            conditions.append(
                listing_preferences_json["society_vibe_tags"].op("@>")(
                    cast(json.dumps([tag]), JSONB)
                )
            )

        # --- parking / floor / age ---
        if f.parking_spaces_min is not None:
            conditions.append(Property.parking_spaces >= f.parking_spaces_min)
        if f.floor_number_min is not None:
            conditions.append(Property.floor_number >= f.floor_number_min)
        if f.floor_number_max is not None:
            conditions.append(Property.floor_number <= f.floor_number_max)
        if f.age_max is not None:
            conditions.append(Property.age_of_property <= f.age_max)

        # --- amenities and lift ---
        await self._build_amenity_condition(f, db, conditions)
        if f.has_lift:
            lift_subquery = (
                select(PropertyAmenity.property_id)
                .join(Amenity, Amenity.id == PropertyAmenity.amenity_id)
                .where(func.lower(Amenity.title).in_(_LIFT_AMENITY_TITLES))
            )
            conditions.append(Property.id.in_(lift_subquery))

        # --- listing preferences (PG / flatmate) — stored in JSON, not columns ---
        if f.gender_preference is not None:
            conditions.append(
                listing_preferences_json["gender_preference"].astext == f.gender_preference.value
            )
        if f.sharing_type is not None:
            conditions.append(
                listing_preferences_json["sharing_type"].astext == f.sharing_type.value
            )

        # --- flatmates listing enhancements ---
        if f.furnishing:
            conditions.append(Property.furnishing_level.in_([v.value for v in f.furnishing]))
        if f.kitchen_type:
            # 'any' is the client's "no kitchen constraint" sentinel. No listing stores it.
            kitchen_values = [v for v in f.kitchen_type if v != KitchenType.any]
            if kitchen_values:
                conditions.append(Property.kitchen_type.in_(kitchen_values))
        if f.ventilation_type:
            conditions.append(Property.ventilation_type.in_(list(f.ventilation_type)))
        if f.windows_min is not None:
            conditions.append(Property.windows_count >= f.windows_min)

        # --- availability dates ---
        available_from_min = available_from_minimum(f.available_from)
        if available_from_min is not None:
            conditions.append(Property.available_from.is_not(None))
            conditions.append(Property.available_from >= available_from_min)

        move_in_range = move_in_window(f.move_in)
        if move_in_range is not None:
            start, end = move_in_range
            conditions.append(Property.available_from.is_not(None))
            if start is not None:
                conditions.append(Property.available_from >= start)
            conditions.append(Property.available_from < end)

        # --- features (object or string-array JSON shapes) ---
        for feature in f.features or []:
            conditions.append(
                or_(
                    Property.features.op("@>")(cast(json.dumps({feature: True}), JSONB)),
                    Property.features.op("@>")(cast(json.dumps([feature]), JSONB)),
                )
            )

        # --- short stay: guests and booking overlap ---
        if f.guests is not None:
            conditions.append(Property.max_occupancy >= f.guests)
        self._build_booking_overlap(f, conditions)

        # --- exclude swiped (only for a signed-in viewer that asks for it) ---
        if viewer_id is not None and f.exclude_swiped:
            from app.models.users import UserSwipe

            swiped_subquery = select(UserSwipe.property_id).where(
                UserSwipe.user_id == viewer_id,
                UserSwipe.target_type == "property",
                UserSwipe.property_id.is_not(None),
            )
            conditions.append(~Property.id.in_(swiped_subquery))

        return conditions, distance_expr, search_meta

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _build_booking_overlap(self, f: UnifiedPropertyFilter, conditions: list[Any]) -> None:
        """Exclude listings with a confirmed or checked-in booking that overlaps the stay.

        Both dates are needed. A lone check-in or check-out is a client error (422).
        """
        if not f.check_in_date and not f.check_out_date:
            return
        if not (f.check_in_date and f.check_out_date):
            raise ValidationException(detail="check_in and check_out must be sent together")
        check_in = _parse_stay_date(f.check_in_date, "check_in")
        check_out = _parse_stay_date(f.check_out_date, "check_out")
        if check_out <= check_in:
            raise ValidationException(detail="check_out must be after check_in")

        from app.models.bookings import Booking

        # Overlap: existing.check_in < requested.check_out AND existing.check_out > requested.check_in
        booked_properties = (
            select(Booking.property_id)
            .where(
                Booking.booking_status.in_([BookingStatus.confirmed, BookingStatus.checked_in]),
                Booking.check_in_date < check_out,
                Booking.check_out_date > check_in,
            )
            .distinct()
        )
        conditions.append(~Property.id.in_(booked_properties))

    def _build_geo_conditions(
        self,
        f: UnifiedPropertyFilter,
        conditions: list[Any],
    ) -> Any | None:
        """Add geo filter conditions. Returns distance expression in km, or None."""
        if f.latitude is None or f.longitude is None or not f.radius_km:
            return None

        user_location = func.ST_SetSRID(func.ST_MakePoint(f.longitude, f.latitude), 4326)
        radius_m = f.radius_km * 1000
        conditions.append(func.ST_DWithin(Property.location, user_location, radius_m))

        # ST_DWithin uses meters. The distance column is returned in km.
        return func.ST_Distance(Property.location, user_location, type_=Float) / 1000

    def _build_fts_conditions(
        self,
        f: UnifiedPropertyFilter,
        conditions: list[Any],
        *,
        hard_filter_text: bool = True,
    ) -> dict[str, Any]:
        """Build full-text search expressions using the indexed __ts_vector__ column."""
        search_meta: dict[str, Any] = {
            "search_query_obj": None,
            "search_vector": None,
            "text_rank_expr": None,
        }

        if not f.search_query:
            return search_meta

        search_query_obj = func.plainto_tsquery("english", f.search_query)
        search_vector = property_ts_vector_column()

        if hard_filter_text:
            conditions.append(search_vector.op("@@")(search_query_obj))

        search_meta["search_query_obj"] = search_query_obj
        search_meta["search_vector"] = search_vector
        search_meta["text_rank_expr"] = func.ts_rank(search_vector, search_query_obj)
        return search_meta

    async def _build_amenity_condition(
        self,
        f: UnifiedPropertyFilter,
        db: AsyncSession,
        conditions: list[Any],
    ) -> None:
        """Add amenity subquery filter if amenities specified."""
        if not f.amenities:
            return

        amenity_ids: list[int] = []
        amenity_names: list[str] = []

        for amenity in f.amenities:
            if isinstance(amenity, int) or (isinstance(amenity, str) and amenity.isdigit()):
                amenity_ids.append(int(amenity))
            else:
                amenity_names.append(amenity)

        if amenity_names:
            # Case-insensitive name match (parity with property search).
            amenity_stmt = select(Amenity.id).where(
                func.lower(Amenity.title).in_([n.lower() for n in amenity_names])
            )
            result = await execute_with_transient_retry(
                db,
                lambda: db.execute(amenity_stmt),
                operation_name="property_query_builder_amenities",
            )
            amenity_ids.extend(row[0] for row in result.fetchall())

        if amenity_ids:
            subquery = (
                select(PropertyAmenity.property_id)
                .where(PropertyAmenity.amenity_id.in_(amenity_ids))
                .group_by(PropertyAmenity.property_id)
                .having(func.count(PropertyAmenity.amenity_id) >= len(amenity_ids))
            )
            conditions.append(Property.id.in_(subquery))
        elif amenity_names:
            # Unresolvable amenity names should match nothing, not drop the filter.
            conditions.append(false())

    def apply_sort(
        self,
        query: Any,
        sort_by: SortBy | None,
        distance_expr: Any = None,
        text_rank_expr: Any = None,
        combined_relevance_expr: Any = None,
        *,
        newest_column: Any = None,
    ) -> Any:
        """Apply sorting to a query. Returns the modified query.

        ``newest_column`` overrides the default Property.created_at for newest
        sort (e.g. UserSwipe.created_at for swipe history).
        """
        if sort_by is None:
            sort_by = SortBy.newest

        newest_expr = newest_column if newest_column is not None else Property.created_at

        if sort_by == SortBy.distance:
            if distance_expr is not None:
                return query.order_by(distance_expr)
            # No geo context: fall back to newest without warning noise.
            return query.order_by(newest_expr.desc())
        if sort_by == SortBy.price_low:
            return query.order_by(Property.base_price.asc())
        if sort_by == SortBy.price_high:
            return query.order_by(Property.base_price.desc())
        if sort_by == SortBy.newest:
            return query.order_by(newest_expr.desc())
        if sort_by == SortBy.popular:
            return query.order_by(Property.like_count.desc(), Property.view_count.desc())
        if sort_by == SortBy.relevance:
            if combined_relevance_expr is not None:
                return query.order_by(combined_relevance_expr.desc())
            if text_rank_expr is not None:
                return query.order_by(text_rank_expr.desc())
            return query.order_by(newest_expr.desc())

        logger.warning("Unsupported sort option: %s, defaulting to newest", sort_by)
        return query.order_by(newest_expr.desc())
