from typing import Generic, Type, TypeVar, Optional, List, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, delete, func, and_, or_
from sqlalchemy.orm import selectinload, joinedload
from app.models.base import Base
from app.core.exceptions import NotFoundException

ModelType = TypeVar("ModelType", bound=Base)

class BaseRepository(Generic[ModelType]):
    """Base repository providing common CRUD operations"""
    
    def __init__(self, model: Type[ModelType], session: AsyncSession):
        self.model = model
        self.session = session
    
    async def create(self, **kwargs) -> ModelType:
        """Create a new record"""
        instance = self.model(**kwargs)
        self.session.add(instance)
        await self.session.flush()
        await self.session.refresh(instance)
        return instance
    
    async def get(self, id: int, load_options: List = None) -> Optional[ModelType]:
        """Get a single record by ID"""
        query = select(self.model).where(self.model.id == id)
        
        if load_options:
            for option in load_options:
                query = query.options(option)
        
        result = await self.session.execute(query)
        instance = result.scalar_one_or_none()
        
        if not instance:
            raise NotFoundException(f"{self.model.__name__} with id {id} not found")
        
        return instance
    
    async def get_multi(
        self,
        *,
        skip: int = 0,
        limit: int = 100,
        filters: Dict[str, Any] = None,
        order_by: Any = None,
        load_options: List = None
    ) -> List[ModelType]:
        """Get multiple records with filtering and pagination"""
        query = select(self.model)
        
        if filters:
            for key, value in filters.items():
                if hasattr(self.model, key):
                    if isinstance(value, list):
                        query = query.where(getattr(self.model, key).in_(value))
                    else:
                        query = query.where(getattr(self.model, key) == value)
        
        if order_by is not None:
            query = query.order_by(order_by)
        
        if load_options:
            for option in load_options:
                query = query.options(option)
        
        query = query.offset(skip).limit(limit)
        
        result = await self.session.execute(query)
        return result.scalars().all()
    
    async def update(self, id: int, **kwargs) -> Optional[ModelType]:
        """Update a record"""
        instance = await self.get(id)
        
        for key, value in kwargs.items():
            if hasattr(instance, key):
                setattr(instance, key, value)
        
        await self.session.flush()
        await self.session.refresh(instance)
        return instance
    
    async def delete(self, id: int) -> bool:
        """Delete a record"""
        instance = await self.get(id)
        await self.session.delete(instance)
        await self.session.flush()
        return True
    
    async def count(self, filters: Dict[str, Any] = None) -> int:
        """Count records with optional filtering"""
        query = select(func.count()).select_from(self.model)
        
        if filters:
            for key, value in filters.items():
                if hasattr(self.model, key):
                    query = query.where(getattr(self.model, key) == value)
        
        result = await self.session.execute(query)
        return result.scalar()
    
    async def exists(self, **kwargs) -> bool:
        """Check if a record exists"""
        query = select(self.model)
        
        for key, value in kwargs.items():
            if hasattr(self.model, key):
                query = query.where(getattr(self.model, key) == value)
        
        result = await self.session.execute(query.limit(1))
        return result.scalar() is not None
