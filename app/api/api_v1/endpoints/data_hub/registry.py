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
    ColonyApprovalListResponse,
    GazetteNotificationListResponse,
    GazetteNotificationResponse,
    JamabandiLookupRequest,
    JamabandiLookupResponse,
    ZoningDataListResponse,
    ZoningDataResponse,
)
from app.schemas.user import User as UserSchema

from .helpers import _paginate, _safe_list_query

router = APIRouter()
logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Jamabandi
# ---------------------------------------------------------------------------


@router.get("/jamabandi/captcha")
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


@router.post("/jamabandi/lookup", response_model=JamabandiLookupResponse)
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


@router.get("/zoning/sectors", response_model=list[str])
async def list_zoning_sectors(db: AsyncSession = Depends(get_db)):
    """List distinct sectors from zoning data."""
    from sqlalchemy import distinct

    result = await db.execute(
        select(distinct(ZoningData.sector)).order_by(ZoningData.sector)
    )
    return [r for r in result.scalars().all() if r]


@router.get("/zoning/{slug}", response_model=ZoningDataResponse)
async def get_zoning(slug: str, db: AsyncSession = Depends(get_db)):
    """Get zoning data for a specific sector by slug."""
    result = await db.execute(
        select(ZoningData).where(ZoningData.slug == slug)
    )
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Zoning data not found")
    return row


@router.get("/zoning", response_model=ZoningDataListResponse)
async def list_zoning(
    sector: str | None = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
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

    offset = (page - 1) * limit
    rows, total, meta = await _safe_list_query(db, ZoningData, count_q, data_q, offset, limit, page)
    return {
        "items": rows,
        "meta": meta,
        **_paginate(total, page, limit),
    }


# ---------------------------------------------------------------------------
# Colony Approvals
# ---------------------------------------------------------------------------


@router.get("/colony-approvals", response_model=ColonyApprovalListResponse)
async def list_colony_approvals(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """List colony approvals."""
    count_q = select(func.count()).select_from(ColonyApproval)
    data_q = select(ColonyApproval)
    offset = (page - 1) * limit
    rows, total, meta = await _safe_list_query(db, ColonyApproval, count_q, data_q, offset, limit, page)
    return {
        "items": rows,
        "meta": meta,
        **_paginate(total, page, limit),
    }


# ---------------------------------------------------------------------------
# Gazette
# ---------------------------------------------------------------------------


@router.get("/gazette", response_model=GazetteNotificationListResponse)
async def list_gazette(
    type: str | None = Query(None, description="Notification type filter"),
    q: str | None = Query(None, description="Search title or summary"),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
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

    offset = (page - 1) * limit
    rows, total, meta = await _safe_list_query(db, GazetteNotification, count_q, data_q, offset, limit, page)
    return {
        "items": rows,
        "meta": meta,
        **_paginate(total, page, limit),
    }


@router.get("/gazette/{gazette_id}", response_model=GazetteNotificationResponse)
async def get_gazette(gazette_id: int, db: AsyncSession = Depends(get_db)):
    """Get a single gazette notification by ID."""
    result = await db.execute(
        select(GazetteNotification).where(GazetteNotification.id == gazette_id)
    )
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Gazette notification not found")
    return row
