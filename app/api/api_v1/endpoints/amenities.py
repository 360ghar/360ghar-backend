
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.cache import cached
from app.core.database import get_db
from app.schemas.amenity import Amenity
from app.services.property import get_all_amenities

router = APIRouter()


@cached("amenities:all", ttl=settings.CACHE_TTL_AMENITIES)
async def get_amenities_cached(db: AsyncSession) -> list[Amenity]:
    """Cached version of get_all_amenities."""
    raw = await get_all_amenities(db)
    return [Amenity.model_validate(item) if isinstance(item, dict) else item for item in raw]


@router.get("", response_model=list[Amenity], summary="List amenities")
async def list_amenities(db: AsyncSession = Depends(get_db)):
    """List all available amenities (cached for 24 hours)."""
    return await get_amenities_cached(db)

