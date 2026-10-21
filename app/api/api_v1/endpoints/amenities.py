from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.cache import cached
from app.core.database import get_db
from app.schemas.amenity import Amenity
from app.schemas.pagination import (
    CursorPage,
    CursorParams,
    build_cursor_page,
    keyset_sort_value,
    read_keyset,
    trim_keyset_lookahead,
    validate_keyset_payload,
)
from app.services.property import get_all_amenities

router = APIRouter()


@cached("amenities:all", ttl=settings.CACHE_TTL_AMENITIES)
async def get_amenities_cached(db: AsyncSession) -> list[Amenity]:
    """Cached version of get_all_amenities."""
    raw = await get_all_amenities(db)
    return [Amenity.model_validate(item) if isinstance(item, dict) else item for item in raw]


@router.get("", response_model=CursorPage[Amenity], summary="List amenities")
async def list_amenities(page: CursorParams = Depends(), db: AsyncSession = Depends(get_db)):
    """List all active amenities, ordered by title, one page at a time (cached for 24 hours).

    The amenity list has no filters, so the cursor is bound to an empty filter set.
    """
    binding: dict[str, Any] = {}
    cursor_payload = page.decoded(binding)
    # A cache hit can return the stored dicts, so validate every row before sorting.
    rows = [
        Amenity.model_validate(item) if isinstance(item, dict) else item
        for item in await get_amenities_cached(db)
    ]
    amenities = sorted(rows, key=lambda a: (a.title, a.id))
    total = len(amenities) if page.include_total else None
    validate_keyset_payload(cursor_payload, "text", id_kind="int4")
    keyset = read_keyset(cursor_payload)
    if keyset is not None:
        last_title, last_id = keyset
        amenities = [a for a in amenities if (a.title, a.id) > (last_title, last_id)]
    items, next_payload = trim_keyset_lookahead(
        amenities,
        limit=page.limit,
        sort_value=lambda a: keyset_sort_value(a.title),
        item_id=lambda a: a.id,
    )
    return build_cursor_page(
        items, limit=page.limit, next_payload=next_payload, total=total, filters=binding
    )
