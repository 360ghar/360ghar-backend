"""
Repository for property data access
"""

from typing import Any, Dict, List, Optional

from sqlalchemy import and_, desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.logging import get_logger
from app.models.properties import Property, PropertyAmenity
from app.models.users import User
from app.repositories.base import BaseRepository
from app.schemas.property import SortBy

logger = get_logger(__name__)


class PropertyRepository(BaseRepository[Property]):
    """Property repository with query helpers"""

    def __init__(self, session: AsyncSession):
        super().__init__(Property, session)

    async def get_property_with_owner(self, property_id: int) -> Optional[Property]:
        stmt = (
            select(Property)
            .options(selectinload(Property.images), selectinload(Property.owner))
            .where(Property.id == property_id)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_properties_filtered(
        self,
        filters: Dict[str, Any],
        skip: int,
        limit: int,
        sort_by: SortBy,
        sort_order: str,
        include_owner: bool = False,
        include_images: bool = False,
    ) -> List[Property]:
        stmt = select(Property)

        filters = dict(filters or {})
        latitude = filters.pop("latitude", None)
        if latitude is None:
            latitude = filters.pop("lat", None)
        longitude = filters.pop("longitude", None)
        if longitude is None:
            longitude = filters.pop("lng", None)
        radius_km = filters.pop("radius_km", None)
        if radius_km is None:
            radius_km = filters.pop("max_distance_km", None)

        distance_expr = None
        if latitude is not None and longitude is not None:
            center_point = func.ST_SetSRID(func.ST_MakePoint(longitude, latitude), 4326)
            distance_expr = func.ST_Distance(Property.location, center_point)
            if radius_km is not None:
                stmt = stmt.where(
                    func.ST_DWithin(
                        Property.location,
                        center_point,
                        radius_km * 1000,  # Convert km to meters
                    )
                )

        if include_owner:
            stmt = stmt.options(selectinload(Property.owner))
        if include_images:
            stmt = stmt.options(selectinload(Property.images))

        # Apply filters
        stmt = self._apply_filters(stmt, filters)

        # Sorting
        stmt = self._apply_sorting(
            stmt,
            sort_by,
            sort_order,
            distance_expr=distance_expr,
        )

        # Pagination
        stmt = stmt.offset(skip).limit(limit)

        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def get_properties_within_radius(
        self,
        latitude: float,
        longitude: float,
        radius_km: int,
        filters: Dict[str, Any],
        skip: int,
        limit: int,
    ) -> List[Property]:
        center_point = func.ST_SetSRID(func.ST_MakePoint(longitude, latitude), 4326)
        stmt = select(Property)
        stmt = stmt.where(
            func.ST_DWithin(
                Property.location,
                center_point,
                radius_km * 1000,  # Convert km to meters
            )
        )

        stmt = self._apply_filters(stmt, filters)
        stmt = stmt.order_by(func.ST_Distance(Property.location, center_point))
        stmt = stmt.offset(skip).limit(limit)

        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def count_filtered(self, filters: Dict[str, Any]) -> int:
        stmt = select(func.count(Property.id))
        stmt = self._apply_filters(stmt, filters)
        result = await self.session.execute(stmt)
        return result.scalar_one()

    def _apply_filters(self, stmt, filters: Dict[str, Any]):
        """Apply dynamic filters to a SQLAlchemy statement"""
        if not filters:
            return stmt

        for field, value in filters.items():
            if value is None:
                continue

            if field == "price_range":
                min_price, max_price = value
                if min_price is not None:
                    stmt = stmt.where(Property.base_price >= min_price)
                if max_price is not None:
                    stmt = stmt.where(Property.base_price <= max_price)
            elif field == "bedrooms":
                stmt = stmt.where(Property.bedrooms >= value)
            elif field == "bathrooms":
                stmt = stmt.where(Property.bathrooms >= value)
            elif hasattr(Property, field):
                stmt = stmt.where(getattr(Property, field) == value)
        return stmt

    def _apply_sorting(
        self,
        stmt,
        sort_by: SortBy,
        sort_order: str,
        distance_expr=None,
        relevance_expr=None,
    ):
        """Apply sorting to statement."""
        if sort_by is None:
            logger.error("Sort option is required for property sorting")
            raise ValueError("Sort option is required for property sorting")

        normalized_order = (sort_order or "").lower()
        if normalized_order not in ("asc", "desc"):
            logger.warning("Unsupported sort_order '%s', defaulting to asc", sort_order)
            normalized_order = "asc"

        def _apply_direction(expr):
            return expr.desc() if normalized_order == "desc" else expr.asc()

        if sort_by == SortBy.price_low:
            order_expressions = [Property.base_price.asc()]
        elif sort_by == SortBy.price_high:
            order_expressions = [Property.base_price.desc()]
        elif sort_by == SortBy.newest:
            order_expressions = [_apply_direction(Property.created_at)]
        elif sort_by == SortBy.popular:
            order_expressions = [
                _apply_direction(Property.like_count),
                _apply_direction(Property.view_count),
            ]
        elif sort_by == SortBy.distance:
            if distance_expr is None:
                logger.error("Distance sorting requested without a distance expression")
                raise ValueError("Distance sorting requires a distance expression")
            order_expressions = [_apply_direction(distance_expr)]
        elif sort_by == SortBy.relevance:
            if relevance_expr is None:
                logger.warning(
                    "Relevance sorting requested without a relevance expression; "
                    "falling back to created_at"
                )
                relevance_expr = Property.created_at
            order_expressions = [_apply_direction(relevance_expr)]
        else:
            logger.error("Unsupported sort option: %s", sort_by)
            raise ValueError(f"Unsupported sort option: {sort_by}")

        return stmt.order_by(*order_expressions)
