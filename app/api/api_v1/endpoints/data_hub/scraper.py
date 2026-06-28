"""Scraper run management and bulk import endpoints (admin only)."""

from importlib import import_module

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.api_v1.dependencies.auth import get_current_admin
from app.core.database import get_db
from app.core.logging import get_logger
from app.models.data_hub import ScraperRun
from app.schemas.data_hub import ScraperRunResponse
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

_SCRAPER_MAP: dict[str, str] = {
    "circle_rates": "app.services.data_hub.circle_rates.CircleRateScraper",
    "rera_projects": "app.services.data_hub.rera_projects.ReraProjectScraper",
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


@router.post("/admin/scraper/{scraper_name}/trigger", summary="Trigger scraper")
async def trigger_scraper(
    scraper_name: str,
    current_user: UserSchema = Depends(get_current_admin),
):
    """Trigger a named scraper manually (admin only)."""
    if scraper_name not in _SCRAPER_MAP:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown scraper '{scraper_name}'. Available: {list(_SCRAPER_MAP.keys())}",
        )
    try:
        module_path, class_name = _SCRAPER_MAP[scraper_name].rsplit(".", 1)
        module = import_module(module_path)
        scraper_cls = getattr(module, class_name)
        scraper = scraper_cls()
        result = await scraper.run(run_type="manual", triggered_by=current_user.id)
        return {"message": f"Scraper '{scraper_name}' triggered", "result": result}
    except Exception as exc:
        logger.error("Failed to trigger scraper %s: %s", scraper_name, exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Scraper trigger failed — see server logs") from None


@router.get("/admin/scraper/runs", response_model=CursorPage[ScraperRunResponse], summary="List scraper runs")
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
        total = (
            await db.execute(select(func.count()).select_from(ScraperRun))
        ).scalar_one()

    result = await db.execute(
        select(ScraperRun)
        .order_by(ScraperRun.started_at.desc())
        .offset(offset)
        .limit(page.limit + 1)
    )
    rows = list(result.scalars().all())

    has_more = len(rows) > page.limit
    rows = rows[: page.limit]
    next_payload = offset_payload(offset + page.limit) if has_more else None
    return build_cursor_page(rows, limit=page.limit, next_payload=next_payload, total=total)


@router.post("/admin/import/{table_name}", summary="Bulk import data")
async def bulk_import(
    table_name: str,
    current_user: UserSchema = Depends(get_current_admin),
):
    """Placeholder for bulk data import (admin only)."""
    _SUPPORTED_TABLES = {
        "circle_rates", "rera_projects", "bank_auctions", "bank_rates",
        "court_auctions", "rera_complaints", "zoning_data", "colony_approvals",
        "gazette_notifications",
    }
    if table_name not in _SUPPORTED_TABLES:
        raise HTTPException(
            status_code=400,
            detail=f"Table '{table_name}' not supported. Supported: {sorted(_SUPPORTED_TABLES)}",
        )
    return {
        "message": f"Bulk import for '{table_name}' is not yet implemented.",
        "table": table_name,
    }
