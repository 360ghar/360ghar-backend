from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List
from app.core.database import get_db
from app.core.config import settings
from app.core.cache import cached
from app.schemas.amenity import Amenity
from app.services.property import get_all_amenities

router = APIRouter()


@cached("amenities:all", ttl=settings.CACHE_TTL_AMENITIES)
async def get_amenities_cached(db: AsyncSession) -> List[Amenity]:
    """Cached version of get_all_amenities."""
    return await get_all_amenities(db)


@router.get("", response_model=List[Amenity])
async def list_amenities(db: AsyncSession = Depends(get_db)):
    """List all available amenities (cached for 24 hours)."""
    return await get_amenities_cached(db)

