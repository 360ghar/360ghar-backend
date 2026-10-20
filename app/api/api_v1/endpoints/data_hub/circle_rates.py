"""Circle rate endpoints."""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.cache import cached
from app.core.database import get_db
from app.models.data_hub import CircleRate
from app.schemas.data_hub import (
    CircleRateResponse,
)
from app.schemas.pagination import (
    CursorPage,
    CursorParams,
    build_cursor_page,
    offset_payload,
    read_offset,
)

from .helpers import _safe_list_query, facet_execute, facet_page

router = APIRouter()


@router.get(
    "/circle-rates", response_model=CursorPage[CircleRateResponse], summary="List circle rates"
)
async def list_circle_rates(
    sector: str | None = Query(None),
    year: int | None = Query(None),
    property_type: str | None = Query(None),
    page: CursorParams = Depends(),
    db: AsyncSession = Depends(get_db),
):
    """List circle rates with optional filters."""
    filters_payload = {"sector": sector, "year": year, "property_type": property_type}
    filters: list[Any] = []
    if sector:
        filters.append(CircleRate.sector.ilike(f"%{sector}%"))
    if year:
        filters.append(CircleRate.revision_year == year)
    if property_type:
        filters.append(CircleRate.property_type.ilike(f"%{property_type}%"))

    count_q = select(func.count()).select_from(CircleRate)
    data_q = select(CircleRate)
    if filters:
        count_q = count_q.where(and_(*filters))
        data_q = data_q.where(and_(*filters))

    cursor_payload = page.decoded(filters_payload)
    offset = read_offset(cursor_payload)
    rows, total = await _safe_list_query(
        db, CircleRate, count_q, data_q, offset, page.limit, with_total=page.include_total
    )
    has_more = len(rows) > page.limit
    items = rows[: page.limit]
    next_payload = offset_payload(offset + page.limit) if has_more else None
    return build_cursor_page(
        items, limit=page.limit, next_payload=next_payload, total=total, filters=filters_payload
    )


@cached("datahub:circle-rate-sectors", ttl=settings.CACHE_TTL_AMENITIES)
async def list_circle_rate_sectors_cached(db: AsyncSession) -> list[str]:
    """Cached version of list_circle_rate_sectors."""
    from sqlalchemy import distinct

    result = await facet_execute(
        db, select(distinct(CircleRate.sector)).order_by(CircleRate.sector)
    )
    return [r for r in result.scalars().all() if r]


@router.get(
    "/circle-rates/sectors", response_model=CursorPage[str], summary="List circle rate sectors"
)
async def list_circle_rate_sectors(db: AsyncSession = Depends(get_db)):
    """List distinct sector names from circle rates (cached for 24 hours)."""
    return facet_page(await list_circle_rate_sectors_cached(db))


@router.get("/circle-rates/{slug}", response_model=CircleRateResponse, summary="Get circle rate")
async def get_circle_rate(slug: str, db: AsyncSession = Depends(get_db)):
    """Get a single circle rate entry by slug."""
    result = await db.execute(select(CircleRate).where(CircleRate.slug == slug))
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Circle rate not found")
    return row
