"""Registry lookup endpoints — Jamabandi, zoning, colony approvals, gazette."""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.api_v1.dependencies.auth import get_current_active_user
from app.core.database import get_db
from app.core.logging import get_logger
from app.models.data_hub import (
    ColonyApproval,
    GazetteNotification,
    ZoningData,
)
from app.schemas.data_hub import (
    ColonyApprovalResponse,
    GazetteNotificationResponse,
    JamabandiLookupRequest,
    JamabandiLookupResponse,
    ZoningDataResponse,
)
from app.schemas.pagination import (
    CursorPage,
    CursorParams,
    build_cursor_page,
    offset_payload,
    read_offset,
)
from app.schemas.user import User as UserSchema

from .helpers import _safe_list_query

router = APIRouter()
logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Jamabandi
# ---------------------------------------------------------------------------


@router.get("/jamabandi/captcha", summary="Get jamabandi captcha")
async def jamabandi_captcha(
    current_user: UserSchema = Depends(get_current_active_user),
):
    """Proxy the Jamabandi CAPTCHA image."""
    from app.services.data_hub.jamabandi import JamabandiScraper
    scraper = JamabandiScraper()
    try:
        img_bytes = await scraper.get_captcha_bytes()
    except Exception as exc:
        logger.error("Failed to fetch Jamabandi captcha: %s", exc)
        raise HTTPException(status_code=502, detail="Could not fetch captcha from Jamabandi") from None
    return Response(content=img_bytes, media_type="image/png")


@router.post("/jamabandi/lookup", response_model=JamabandiLookupResponse, summary="Lookup jamabandi record")
async def jamabandi_lookup(
    req: JamabandiLookupRequest,
    db: AsyncSession = Depends(get_db),
    current_user: UserSchema = Depends(get_current_active_user),
):
    """Look up a land record (Nakal) via Jamabandi."""
    from app.services.data_hub.jamabandi import JamabandiScraper
    scraper = JamabandiScraper()
    result = await scraper.lookup(
        db,
        tehsil=req.tehsil,
        village=req.village,
        khasra_number=req.khasra_number,
        captcha_token=req.captcha_token,
    )
    if result is None:
        raise HTTPException(status_code=502, detail="Jamabandi lookup failed — check captcha or try again")

    return JamabandiLookupResponse(
        tehsil=result["tehsil"],
        village=result["village"],
        khasra_number=result["khasra_number"],
        owner_names=result.get("owner_names") or [],
        area_acres=result.get("area_kanal"),
        mutation_status=result.get("mutation_status"),
        encumbrance=result.get("encumbrance_details"),
        raw_data=None,
        fetched_at=result.get("fetched_at") or datetime.utcnow(),
        is_cached=result.get("is_cached", False),
    )


# ---------------------------------------------------------------------------
# Zoning
# ---------------------------------------------------------------------------


@router.get("/zoning/sectors", response_model=list[str], summary="List zoning sectors")
async def list_zoning_sectors(db: AsyncSession = Depends(get_db)):
    """List distinct sectors from zoning data."""
    from sqlalchemy import distinct

    result = await db.execute(
        select(distinct(ZoningData.sector)).order_by(ZoningData.sector)
    )
    return [r for r in result.scalars().all() if r]


@router.get("/zoning/{slug}", response_model=ZoningDataResponse, summary="Get zoning data")
async def get_zoning(slug: str, db: AsyncSession = Depends(get_db)):
    """Get zoning data for a specific sector by slug."""
    result = await db.execute(
        select(ZoningData).where(ZoningData.slug == slug)
    )
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Zoning data not found")
    return row


@router.get("/zoning", response_model=CursorPage[ZoningDataResponse], summary="List zoning data")
async def list_zoning(
    sector: str | None = Query(None),
    page: CursorParams = Depends(),
    db: AsyncSession = Depends(get_db),
):
    """List zoning data with optional sector filter."""
    filters = []
    if sector:
        filters.append(ZoningData.sector.ilike(f"%{sector}%"))

    count_q = select(func.count()).select_from(ZoningData)
    data_q = select(ZoningData)
    if filters:
        count_q = count_q.where(and_(*filters))
        data_q = data_q.where(and_(*filters))

    cursor_payload = page.decoded()
    offset = read_offset(cursor_payload)
    rows, total = await _safe_list_query(
        db, ZoningData, count_q, data_q, offset, page.limit, with_total=page.include_total
    )
    has_more = len(rows) > page.limit
    items = rows[: page.limit]
    next_payload = offset_payload(offset + page.limit) if has_more else None
    return build_cursor_page(items, limit=page.limit, next_payload=next_payload, total=total)


# ---------------------------------------------------------------------------
# Colony Approvals
# ---------------------------------------------------------------------------


@router.get("/colony-approvals", response_model=CursorPage[ColonyApprovalResponse], summary="List colony approvals")
async def list_colony_approvals(
    page: CursorParams = Depends(),
    db: AsyncSession = Depends(get_db),
):
    """List colony approvals."""
    count_q = select(func.count()).select_from(ColonyApproval)
    data_q = select(ColonyApproval)
    cursor_payload = page.decoded()
    offset = read_offset(cursor_payload)
    rows, total = await _safe_list_query(
        db, ColonyApproval, count_q, data_q, offset, page.limit, with_total=page.include_total
    )
    has_more = len(rows) > page.limit
    items = rows[: page.limit]
    next_payload = offset_payload(offset + page.limit) if has_more else None
    return build_cursor_page(items, limit=page.limit, next_payload=next_payload, total=total)


# ---------------------------------------------------------------------------
# Gazette
# ---------------------------------------------------------------------------


@router.get("/gazette", response_model=CursorPage[GazetteNotificationResponse], summary="List gazette notifications")
async def list_gazette(
    type: str | None = Query(None, description="Notification type filter"),
    q: str | None = Query(None, description="Search title or summary"),
    page: CursorParams = Depends(),
    db: AsyncSession = Depends(get_db),
):
    """List gazette notifications with optional type and text search filters."""
    filters = []
    if type:
        filters.append(GazetteNotification.notification_type == type)
    if q:
        filters.append(
            GazetteNotification.title.ilike(f"%{q}%")
            | GazetteNotification.summary.ilike(f"%{q}%")
        )

    count_q = select(func.count()).select_from(GazetteNotification)
    data_q = select(GazetteNotification).order_by(GazetteNotification.notification_date.desc())
    if filters:
        count_q = count_q.where(and_(*filters))
        data_q = data_q.where(and_(*filters))

    cursor_payload = page.decoded()
    offset = read_offset(cursor_payload)
    rows, total = await _safe_list_query(
        db, GazetteNotification, count_q, data_q, offset, page.limit, with_total=page.include_total
    )
    has_more = len(rows) > page.limit
    items = rows[: page.limit]
    next_payload = offset_payload(offset + page.limit) if has_more else None
    return build_cursor_page(items, limit=page.limit, next_payload=next_payload, total=total)


@router.get("/gazette/{gazette_id}", response_model=GazetteNotificationResponse, summary="Get gazette notification")
async def get_gazette(gazette_id: int, db: AsyncSession = Depends(get_db)):
    """Get a single gazette notification by ID."""
    result = await db.execute(
        select(GazetteNotification).where(GazetteNotification.id == gazette_id)
    )
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Gazette notification not found")
    return row
