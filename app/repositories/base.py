"""
Base repository pattern for data access layer
"""
from typing import Any, Generic, TypeVar

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.logging import get_logger

logger = get_logger(__name__)

T = TypeVar("T")

class BaseRepository(Generic[T]):
    """
    Base repository providing common CRUD operations.
    Separates data access logic from business logic.

    Args:
        model: SQLAlchemy model class
        session: Async database session
    """

    def __init__(self, model: type[T], session: AsyncSession):
        self.model = model
        self.session = session

    async def get(self, id: int) -> T | None:
        """Get entity by ID"""
        return await self.session.get(self.model, id)

    async def get_with_relations(self, id: int, relations: list[str] | None = None) -> T | None:
        """
        Get entity by ID with eager-loaded relationships

        Args:
            id: Entity ID
            relations: List of relationship attribute names to load
        """
        stmt = select(self.model).where(self.model.id == id)  # type: ignore[attr-defined]

        if relations:
            for relation in relations:
                stmt = stmt.options(selectinload(getattr(self.model, relation)))

        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list(
        self,
        filters: dict[str, Any] | None = None,
        skip: int = 0,
        limit: int = 100,
        order_by: str | None = None
    ) -> list[T]:
        """
        List entities with optional filtering and pagination

        Args:
            filters: Dictionary of field:value filters
            skip: Number of records to skip
            limit: Maximum number of records to return
            order_by: Field to order by (prefix with - for descending)
        """
        stmt = select(self.model)

        # Apply filters
        if filters:
            for field, value in filters.items():
                if hasattr(self.model, field):
                    stmt = stmt.where(getattr(self.model, field) == value)

        # Apply ordering
        if order_by:
            if order_by.startswith('-'):
                stmt = stmt.order_by(getattr(self.model, order_by[1:]).desc())
            else:
                stmt = stmt.order_by(getattr(self.model, order_by))

        # Apply pagination
        stmt = stmt.offset(skip).limit(limit)

        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def count(self, filters: dict[str, Any] | None = None) -> int:
        """Count entities with optional filtering"""
        stmt = select(func.count()).select_from(self.model)

        if filters:
            for field, value in filters.items():
                if hasattr(self.model, field):
                    stmt = stmt.where(getattr(self.model, field) == value)

        result = await self.session.execute(stmt)
        return result.scalar_one()

    async def create(self, entity: T) -> T:
        """Create new entity"""
        self.session.add(entity)
        await self.session.flush()
        await self.session.refresh(entity)
        return entity

    async def update(self, id: int, data: dict[str, Any]) -> T | None:
        """Update entity by ID"""
        stmt = (
            update(self.model)
            .where(self.model.id == id)  # type: ignore[attr-defined]
            .values(**data)
            .returning(self.model)
        )

        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def delete(self, id: int) -> bool:
        """Delete entity by ID"""
        entity = await self.get(id)
        if entity:
            await self.session.delete(entity)
            await self.session.flush()
            return True
        return False

    async def exists(self, id: int) -> bool:
        """Check if entity exists"""
        stmt = select(func.count()).select_from(self.model).where(self.model.id == id)  # type: ignore[attr-defined]
        result = await self.session.execute(stmt)
        return result.scalar_one() > 0
