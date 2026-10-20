"""
Repository for property data access.

Listing filters and sorts are built in ``PropertyQueryBuilder`` (property_query_builder.py).
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.properties import Property, PropertyAmenity
from app.repositories.base import BaseRepository


class PropertyRepository(BaseRepository[Property]):
    """Property repository with query helpers"""

    def __init__(self, session: AsyncSession):
        super().__init__(Property, session)

    async def get_property_with_owner(self, property_id: int) -> Property | None:
        stmt = (
            select(Property)
            .options(
                selectinload(Property.images),
                selectinload(Property.owner),
                selectinload(Property.property_amenities).selectinload(PropertyAmenity.amenity),
            )
            .where(Property.id == property_id)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()
