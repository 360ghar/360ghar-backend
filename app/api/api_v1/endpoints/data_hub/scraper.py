"""Scraper run management endpoints (admin only)."""

import inspect
from importlib import import_module
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.api_v1.dependencies.auth import get_current_admin
from app.config import settings
from app.core.database import get_db
from app.core.logging import get_logger
from app.models.data_hub import ScraperRun
from app.schemas.data_hub import (
    ScraperRunResponse,
    ScraperTriggerRequest,
    ScraperTriggerResult,
)
from app.schemas.pagination import (
    CursorPage,
    CursorParams,
    build_cursor_page,
    offset_payload,
    read_offset,
)
from app.schemas.user import User as UserSchema

router = APIRouter()
logger = get_logger(__name__)

_HRERA_SCRAPER_URLS = {
    "rera_projects": "https://haryanarera.gov.in/view_project/search_project",
    "rera_complaints": "https://haryanarera.gov.in/assistancecontrol/searchcaseopen",
    "rera_portal_scan": "https://haryanarera.gov.in/view_project/project_preview_open",
    "rera_project_detail": "https://haryanarera.gov.in/view_project/project_preview_open",
    "uprera_projects": "https://up-rera.in/projects",
    "delhi_rera_projects": "https://erera.co.in/reradelhiindex/PublicView/RegisteredProjectDetail",
}

_SCRAPER_MAP: dict[str, str] = {
    "circle_rates": "app.services.data_hub.circle_rates.CircleRateScraper",
    "rera_projects": "app.services.data_hub.rera_projects.ReraProjectScraper",
    "rera_portal_scan": "app.services.data_hub.rera_portal_scan.ReraPortalIdScanner",
    "rera_project_detail": "app.services.data_hub.rera_project_detail.ReraProjectDetailScraper",
    "uprera_projects": "app.services.data_hub.uprera_projects.UpreraProjectScraper",
    "delhi_rera_projects": "app.services.data_hub.delhi_rera_projects.DelhiReraProjectScraper",
    "bank_auctions": "app.services.data_hub.bank_auctions.BankAuctionScraper",
    "hsvp_auctions": "app.services.data_hub.hsvp_auctions.HsvpAuctionScraper",
    "dda_auctions": "app.services.data_hub.dda_auctions.DdaAuctionScraper",
    "mda_auctions": "app.services.data_hub.mda_auctions.MdaAuctionScraper",
    "yeida_auctions": "app.services.data_hub.yeida_auctions.YeidaAuctionScraper",
    "aggregator_eauctions": "app.services.data_hub.aggregator_eauctions.AggregatorEauctionsScraper",
    "baanknet_auctions": "app.services.data_hub.baanknet_auctions.BaankNetAuctionScraper",
    "ibbi_auctions": "app.services.data_hub.ibbi_auctions.IBBIAuctionScraper",
    "dfc_delhi_auctions": "app.services.data_hub.dfc_delhi_auctions.DFCDelhiAuctionScraper",
    "drt_auctions": "app.services.data_hub.drt_auctions.DRTAuctionScraper",
    "hsvp_procure247_auctions": "app.services.data_hub.hsvp_procure247_auctions.HSVPProcure247AuctionScraper",
    "aggregator_misc_auctions": "app.services.data_hub.aggregator_misc.AggregatorMiscAuctionScraper",
    "bank_specific_auctions": "app.services.data_hub.bank_specific_auctions.BankSpecificAuctionScraper",
    "bank_rates": "app.services.data_hub.bank_rates.BankRateScraper",
    "court_auctions": "app.services.data_hub.court_auctions.CourtAuctionScraper",
    "rera_complaints": "app.services.data_hub.rera_complaints.ReraComplaintScraper",
    "zoning": "app.services.data_hub.zoning.ZoningScraper",
    "gazette": "app.services.data_hub.gazette.GazetteScraper",
    "neighbourhood": "app.services.data_hub.neighbourhood.NeighbourhoodScraper",
}


def _scraper_options(
    scraper_cls: type, body: ScraperTriggerRequest | None
) -> dict[str, Any]:
    """The operator options this scraper actually accepts.

    Passing the whole body on would raise ``TypeError`` for the many scrapers whose
    ``__init__`` takes no arguments, so the body is filtered against the scraper's
    own signature. A key the caller sent but the scraper does not take is dropped.
    """
    if body is None:
        return {}
    supplied = body.model_dump(exclude_none=True)
    if not supplied:
        return {}
    try:
        accepted = inspect.signature(scraper_cls).parameters
    except (TypeError, ValueError):
        # A class whose signature cannot be read takes no operator options.
        return {}
    return {key: value for key, value in supplied.items() if key in accepted}


@router.post(
    "/admin/scraper/{scraper_name}/trigger",
    response_model=ScraperTriggerResult,
    summary="Trigger scraper",
    responses={503: {"description": "HRERA surface turned off by configuration"}},
)
async def trigger_scraper(
    scraper_name: str,
    body: ScraperTriggerRequest | None = None,
    current_user: UserSchema = Depends(get_current_admin),
):
    """Trigger a named scraper manually (admin only).

    The optional body carries operator arguments, which only ``rera_portal_scan``
    reads: it walks a range of HRERA portal ids and fails without an ``end_id``
    rather than defaulting to an unbounded crawl. Options a scraper does not
    accept are dropped, so the body is safe to send to any scraper.
    """
    if scraper_name not in _SCRAPER_MAP:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown scraper '{scraper_name}'. Available: {list(_SCRAPER_MAP.keys())}",
        )
    if scraper_name in _HRERA_SCRAPER_URLS and not settings.HRERA_DATA_ENABLED:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "HRERA_DISABLED",
                "message": "HRERA scraping is turned off by configuration",
                "official_source_url": _HRERA_SCRAPER_URLS[scraper_name],
            },
        )
    try:
        module_path, class_name = _SCRAPER_MAP[scraper_name].rsplit(".", 1)
        module = import_module(module_path)
        scraper_cls = getattr(module, class_name)
        scraper = scraper_cls(**_scraper_options(scraper_cls, body))
        result = await scraper.run(run_type="manual", triggered_by=current_user.id)
        return ScraperTriggerResult(message=f"Scraper '{scraper_name}' triggered", result=result)
    except Exception as exc:
        logger.error("Failed to trigger scraper %s: %s", scraper_name, exc, exc_info=True)
        raise HTTPException(
            status_code=500, detail="Scraper trigger failed — see server logs"
        ) from None


@router.get(
    "/admin/scraper/runs",
    response_model=CursorPage[ScraperRunResponse],
    summary="List scraper runs",
)
async def list_scraper_runs(
    page: CursorParams = Depends(),
    db: AsyncSession = Depends(get_db),
    current_user: UserSchema = Depends(get_current_admin),
):
    """List recent scraper runs (admin only)."""
    cursor_payload = page.decoded()
    offset = read_offset(cursor_payload)

    total: int | None = None
    if page.include_total:
        total = (await db.execute(select(func.count()).select_from(ScraperRun))).scalar_one()

    result = await db.execute(
        select(ScraperRun)
        .order_by(ScraperRun.started_at.desc(), ScraperRun.id.desc())
        .offset(offset)
        .limit(page.limit + 1)
    )
    rows = list(result.scalars().all())

    has_more = len(rows) > page.limit
    rows = rows[: page.limit]
    next_payload = offset_payload(offset + page.limit) if has_more else None
    return build_cursor_page(rows, limit=page.limit, next_payload=next_payload, total=total)
