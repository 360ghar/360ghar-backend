"""
Centralized property filter and sort query builder.

Eliminates duplicated filter/sort logic across property.py, swipe.py, and property_repository.py.
All property query construction should go through this builder.
"""


from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.properties import Amenity, Property, PropertyAmenity
from app.schemas.property import SortBy, UnifiedPropertyFilter

logger = get_logger(__name__)


class PropertyQueryBuilder:
    """Builds SQLAlchemy where-clauses and order-by expressions from a UnifiedPropertyFilter.

    Usage::

        builder = PropertyQueryBuilder(filters)
        conditions, distance_expr, search_meta = await builder.build(db)

        # conditions can be applied to any query that targets Property
        query = query.where(and_(*conditions))
        query = builder.apply_sort(query, distance_expr, search_meta.get("text_rank"))
    """

    def __init__(self, filters: UnifiedPropertyFilter) -> None:
        self.filters = filters

    async def build(
        self,
        db: AsyncSession,
        *,
        include_unavailable: bool = False,
    ) -> tuple[
        list,  # conditions
        object | None,  # distance_expr (SQLAlchemy column)
        dict,  # search_meta: {search_query_obj, search_vector, text_rank_expr}
    ]:
        """Build and return all filter components.

        Returns (conditions, distance_expr, search_meta).

        conditions: list of SQLAlchemy where-expressions targeting Property columns.
        distance_expr: ST_Distance column (or None).
        search_meta: dict with keys search_query_obj, search_vector, text_rank_expr.
        """
        f = self.filters
        conditions: list[object] = []

        # --- availability ---
        if not include_unavailable:
            conditions.append(Property.is_available == True)  # noqa: E712

        # --- location / geo ---
        distance_expr = await self._build_geo_conditions(f, conditions)

        # --- full-text search ---
        search_meta = self._build_fts_conditions(f, conditions)

        # --- property IDs ---
        if f.property_ids:
            conditions.append(Property.id.in_(f.property_ids))

        # --- property type ---
        if f.property_type:
            if isinstance(f.property_type, list) and len(f.property_type) > 0:
                conditions.append(Property.property_type.in_(f.property_type))
            elif not isinstance(f.property_type, list):
                conditions.append(Property.property_type == f.property_type)

        # --- purpose ---
        if f.purpose:
            conditions.append(Property.purpose == f.purpose)

        # --- price range ---
        if f.price_min is not None:
            conditions.append(Property.base_price >= f.price_min)
        if f.price_max is not None:
            conditions.append(Property.base_price <= f.price_max)

        # --- bedrooms ---
        if f.bedrooms_min is not None:
            conditions.append(Property.bedrooms >= f.bedrooms_min)
        if f.bedrooms_max is not None:
            conditions.append(Property.bedrooms <= f.bedrooms_max)

        # --- bathrooms ---
        if f.bathrooms_min is not None:
            conditions.append(Property.bathrooms >= f.bathrooms_min)
        if f.bathrooms_max is not None:
            conditions.append(Property.bathrooms <= f.bathrooms_max)

        # --- area ---
        if f.area_min is not None:
            conditions.append(Property.area_sqft >= f.area_min)
        if f.area_max is not None:
            conditions.append(Property.area_sqft <= f.area_max)

        # --- city / locality / pincode ---
        if f.city:
            conditions.append(Property.city.ilike(f"%{f.city}%"))
        if f.locality:
            conditions.append(Property.locality.ilike(f"%{f.locality}%"))
        if f.pincode:
            conditions.append(Property.pincode == f.pincode)

        # --- parking / floor / age ---
        if f.parking_spaces_min is not None:
            conditions.append(Property.parking_spaces >= f.parking_spaces_min)
        if f.floor_number_min is not None:
            conditions.append(Property.floor_number >= f.floor_number_min)
        if f.floor_number_max is not None:
            conditions.append(Property.floor_number <= f.floor_number_max)
        if f.age_max is not None:
            conditions.append(Property.age_of_property <= f.age_max)

        # --- amenities ---
        await self._build_amenity_condition(f, db, conditions)

        # --- features ---
        if f.features:
            for feat in f.features:
                if hasattr(Property, feat):
                    conditions.append(getattr(Property, feat))

        # --- gender preference ---
        if f.gender_preference:
            conditions.append(Property.gender_preference == f.gender_preference)  # type: ignore[attr-defined]

        # --- sharing type ---
        if f.sharing_type:
            conditions.append(Property.sharing_type == f.sharing_type)  # type: ignore[attr-defined]

        # --- guests / max_occupancy ---
        if f.guests is not None:
            conditions.append(Property.max_occupancy >= f.guests)

        return conditions, distance_expr, search_meta

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _build_geo_conditions(
        self,
        f: UnifiedPropertyFilter,
        conditions: list[object],
    ) -> object | None:
        """Add geo filter conditions. Returns distance expression or None."""
        if f.latitude is None or f.longitude is None or not f.radius_km:
            return None

        user_location = func.ST_SetSRID(
            func.ST_MakePoint(f.longitude, f.latitude), 4326
        )
        radius_m = f.radius_km * 1000
        conditions.append(func.ST_DWithin(Property.location, user_location, radius_m))

        distance_expr = func.ST_Distance(Property.location, user_location) / 1000
        return distance_expr

    def _build_fts_conditions(
        self,
        f: UnifiedPropertyFilter,
        conditions: list[object],
    ) -> dict:
        """Build full-text search expressions. Returns search_meta dict."""
        search_meta: dict = {
            "search_query_obj": None,
            "search_vector": None,
            "text_rank_expr": None,
        }

        if not f.search_query:
            return search_meta

        search_query_obj = func.plainto_tsquery("english", f.search_query)
        search_vector = func.to_tsvector(
            "english",
            func.concat(
                Property.title, " ",
                Property.description, " ",
                Property.locality, " ",
                Property.city,
            ),
        )

        conditions.append(search_vector.op("@@")(search_query_obj))
        search_meta["search_query_obj"] = search_query_obj
        search_meta["search_vector"] = search_vector
        search_meta["text_rank_expr"] = func.ts_rank(search_vector, search_query_obj)
        return search_meta

    async def _build_amenity_condition(
        self,
        f: UnifiedPropertyFilter,
        db: AsyncSession,
        conditions: list[object],
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
            result = await db.execute(
                select(Amenity.id).where(Amenity.title.in_(amenity_names))
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

    def apply_sort(
        self,
        query,
        sort_by: SortBy,
        distance_expr=None,
        text_rank_expr=None,
        combined_relevance_expr=None,
    ):
        """Apply sorting to a query. Returns the modified query."""
        if sort_by is None:
            sort_by = SortBy.newest

        if sort_by == SortBy.distance and distance_expr is not None:
            return query.order_by(distance_expr)
        elif sort_by == SortBy.price_low:
            return query.order_by(Property.base_price.asc())
        elif sort_by == SortBy.price_high:
            return query.order_by(Property.base_price.desc())
        elif sort_by == SortBy.newest:
            return query.order_by(Property.created_at.desc())
        elif sort_by == SortBy.popular:
            return query.order_by(Property.like_count.desc(), Property.view_count.desc())
        elif sort_by == SortBy.relevance:
            if combined_relevance_expr is not None:
                return query.order_by(combined_relevance_expr.desc())
            if text_rank_expr is not None:
                return query.order_by(text_rank_expr.desc())
            # Fallback: relevance without expressions
            return query.order_by(Property.created_at.desc())
        else:
            logger.warning("Unsupported sort option: %s, defaulting to newest", sort_by)
            return query.order_by(Property.created_at.desc())
