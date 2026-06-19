"""Bank and court auction endpoints."""

from datetime import date as date_type
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, func, select, union_all
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.cache import cached
from app.core.database import get_db
from app.core.logging import get_logger
from app.models.data_hub import BankAuction, CourtAuction
from app.schemas.data_hub import (
    BankAuctionResponse,
    CourtAuctionResponse,
)
from app.schemas.pagination import (
    CursorPage,
    CursorParams,
    build_cursor_page,
    offset_payload,
    read_offset,
)

from .helpers import _safe_list_query

router = APIRouter()
logger = get_logger(__name__)


@cached("datahub:auction-banks", ttl=settings.CACHE_TTL_AMENITIES)
async def list_auction_banks_cached(db: AsyncSession) -> list[str]:
    """Cached version of list_auction_banks."""
    from sqlalchemy import distinct

    result = await db.execute(
        select(distinct(BankAuction.bank_name)).order_by(BankAuction.bank_name)
    )
    return [r for r in result.scalars().all() if r]


@router.get("/auctions/banks", response_model=list[str], summary="List auction banks")
async def list_auction_banks(db: AsyncSession = Depends(get_db)):
    """List distinct bank names from bank auctions (cached for 24 hours)."""
    return await list_auction_banks_cached(db)


@cached("datahub:auction-cities", ttl=settings.CACHE_TTL_AMENITIES)
async def get_auction_cities_cached(db: AsyncSession) -> list[str]:
    """Cached version of get_auction_cities."""
    bank_cities = select(BankAuction.city).where(BankAuction.is_active)
    court_cities = select(CourtAuction.city).where(CourtAuction.is_active)

    combined = union_all(bank_cities, court_cities).subquery()
    stmt = select(func.distinct(combined.c.city)).order_by(combined.c.city)
    result = await db.execute(stmt)
    return [row[0] for row in result.all() if row[0]]


@router.get("/auctions/cities", response_model=list[str], summary="List auction cities")
async def get_auction_cities(db: AsyncSession = Depends(get_db)):
    """Return distinct city values from bank_auctions + court_auctions (cached for 24 hours)."""
    return await get_auction_cities_cached(db)


@router.get("/auctions/source-categories", summary="List auction source categories")
async def get_auction_source_categories(db: AsyncSession = Depends(get_db)):
    """Return grouped source metadata with counts."""
    # Count auctions per source
    stmt = select(
        BankAuction.source,
        func.count(BankAuction.id).label("count")
    ).where(BankAuction.is_active).group_by(BankAuction.source)
    result = await db.execute(stmt)
    source_counts = {str(row[0]): row[1] for row in result.all()}

    # Categorize sources
    categories = {
        "central": [
            {"source": "ibapi", "label": "IBAPI", "url": "https://ibapi.in"},
            {"source": "ibbi", "label": "IBBI", "url": "https://ibbi.gov.in/liquidation-auction-notices"},
            {"source": "baanknet", "label": "BaankNet/eBKray", "url": "https://baanknet.com"},
            {"source": "mstc", "label": "MSTC", "url": "https://mstcecommerce.com"},
        ],
        "delhi": [
            {"source": "dda", "label": "DDA e-Services", "url": "https://eservices.dda.org.in"},
            {"source": "dfc_delhi", "label": "Delhi Financial Corp", "url": "https://dfc.delhi.gov.in/dfc/public-auction"},
            {"source": "drt", "label": "DRT Delhi", "url": "https://drt.gov.in"},
            {"source": "ecourts", "label": "eCourts", "url": "https://ecourts.gov.in"},
        ],
        "gurgaon": [
            {"source": "hsvp", "label": "HSVP e-Auction", "url": "https://eauction.hsvphry.org.in"},
            {"source": "hsvp_procure247", "label": "HSVP Procure247", "url": "https://hsvp.procure247.com"},
            {"source": "dtcp", "label": "DTCP Haryana", "url": "https://tcpharyana.gov.in"},
        ],
        "meerut": [
            {"source": "mda", "label": "MDA Meerut", "url": "https://mdameerut.in/auctions.php"},
            {"source": "yeida", "label": "YEIDA", "url": "https://yamunaexpresswayauthority.com"},
        ],
        "aggregators": [
            {"source": "bank_eauctions", "label": "BankEAuctions", "url": "https://bankeauctions.com"},
            {"source": "eauctions_india", "label": "eAuctionsIndia", "url": "https://eauctionsindia.com"},
            {"source": "auction_bazaar", "label": "AuctionBazaar", "url": "https://auctionbazaar.com"},
            {"source": "eauction_dekho", "label": "eAuctionDekho", "url": "https://eauctiondekho.com"},
            {"source": "findauction", "label": "FindAuction.in", "url": "https://findauction.in"},
            {"source": "findauction_prop", "label": "FindAuctionProperty", "url": "https://findauctionproperty.com"},
            {"source": "auction_tiger", "label": "AuctionTiger", "url": "https://auctiontiger.net"},
        ],
        "banks": [
            {"source": "sarfaesi", "label": "SBI SARFAESI", "url": "https://www.sbi.co.in"},
            {"source": "sbi", "label": "SBI", "url": "https://www.sbi.co.in"},
            {"source": "pnb", "label": "PNB", "url": "https://www.pnbindia.in"},
            {"source": "bob", "label": "Bank of Baroda", "url": "https://www.bankofbaroda.in"},
            {"source": "canara", "label": "Canara Bank", "url": "https://www.canarabank.com"},
            {"source": "hdfc", "label": "HDFC Bank", "url": "https://www.hdfcbank.com"},
            {"source": "icici", "label": "ICICI Bank", "url": "https://www.icicibank.com"},
            {"source": "union", "label": "Union Bank", "url": "https://www.unionbankofindia.co.in"},
            {"source": "yes_bank", "label": "Yes Bank", "url": "https://www.yesbank.in"},
        ],
    }

    # Enrich with counts
    for _category, sources in categories.items():
        for source_info in sources:
            source_info["count"] = source_counts.get(source_info["source"], 0)

    return categories


@router.get("/auctions/{auction_id}", summary="Get auction details")
async def get_auction(auction_id: int, db: AsyncSession = Depends(get_db)):
    """Get a single auction by ID — checks bank auctions first, then court auctions."""
    bank_result = await db.execute(
        select(BankAuction).where(BankAuction.id == auction_id)
    )
    bank_row = bank_result.scalar_one_or_none()
    if bank_row is not None:
        return BankAuctionResponse.model_validate(bank_row)

    court_result = await db.execute(
        select(CourtAuction).where(CourtAuction.id == auction_id)
    )
    court_row = court_result.scalar_one_or_none()
    if court_row is not None:
        return CourtAuctionResponse.model_validate(court_row)

    raise HTTPException(status_code=404, detail="Auction not found")


@router.get("/auctions", response_model=CursorPage[BankAuctionResponse], summary="List bank auctions")
async def list_auctions(
    type: str | None = Query(None, description="'bank' or 'court'"),
    bank: str | None = Query(None),
    city: str | None = Query(None, description="Filter by city (case-insensitive partial match)"),
    source: str | None = Query(None, description="Filter by auction source enum value"),
    property_type: str | None = Query(None),
    min_price: float | None = Query(None),
    max_price: float | None = Query(None),
    date_from: date_type | None = Query(None),
    date_to: date_type | None = Query(None),
    page: CursorParams = Depends(),
    db: AsyncSession = Depends(get_db),
):
    """
    Paginated list of auctions. Defaults to bank auctions; set type='court' for court auctions.
    """
    cursor_payload = page.decoded()
    offset = read_offset(cursor_payload)

    if type == "court":
        filters: list[Any] = []
        if city:
            filters.append(CourtAuction.city.ilike(f"%{city}%"))
        if property_type:
            filters.append(CourtAuction.property_type.ilike(f"%{property_type}%"))
        if min_price:
            filters.append(CourtAuction.reserve_price >= min_price)
        if max_price:
            filters.append(CourtAuction.reserve_price <= max_price)
        if date_from:
            filters.append(CourtAuction.auction_date >= date_from)
        if date_to:
            filters.append(CourtAuction.auction_date <= date_to)

        count_q = select(func.count()).select_from(CourtAuction)
        data_q = select(CourtAuction)
        if filters:
            count_q = count_q.where(and_(*filters))
            data_q = data_q.where(and_(*filters))

        try:
            total: int | None = None
            if page.include_total:
                total = (await db.execute(count_q)).scalar_one()
            rows = (
                await db.execute(data_q.offset(offset).limit(page.limit + 1))
            ).scalars().all()
        except Exception as exc:
            logger.warning("Court auctions query failed: %s", exc)
            total = 0 if page.include_total else None
            rows = []

        items = []
        for r in rows:
            items.append(
                BankAuctionResponse(
                    id=r.id,
                    bank_name=r.court_name or "Court",
                    property_description=r.property_description or "",
                    full_address=r.locality,
                    reserve_price=float(r.reserve_price) if r.reserve_price else None,
                    emd_amount=None,
                    auction_date=r.auction_date,
                    auction_end_date=None,
                    contact_info=r.contact_details,
                    source=r.source,
                    source_url=r.source_url,
                    property_type=r.property_type,
                    lat=None,
                    lng=None,
                    slug=getattr(r, "slug", None),
                    last_scraped_at=None,
                    created_at=r.created_at,
                    updated_at=r.updated_at,
                )
            )
        has_more = len(items) > page.limit
        items = items[: page.limit]
        next_payload = offset_payload(offset + page.limit) if has_more else None
        return build_cursor_page(items, limit=page.limit, next_payload=next_payload, total=total)
    else:
        # Default: bank auctions
        bank_filters: list[Any] = []
        if bank:
            bank_filters.append(BankAuction.bank_name.ilike(f"%{bank}%"))
        if city:
            bank_filters.append(BankAuction.city.ilike(f"%{city}%"))
        if source:
            bank_filters.append(BankAuction.source == source)
        if property_type:
            bank_filters.append(BankAuction.property_type.ilike(f"%{property_type}%"))
        if min_price:
            bank_filters.append(BankAuction.reserve_price >= min_price)
        if max_price:
            bank_filters.append(BankAuction.reserve_price <= max_price)
        if date_from:
            bank_filters.append(BankAuction.auction_date >= date_from)
        if date_to:
            bank_filters.append(BankAuction.auction_date <= date_to)

        count_q = select(func.count()).select_from(BankAuction)
        data_q = select(BankAuction)
        if bank_filters:
            count_q = count_q.where(and_(*bank_filters))
            data_q = data_q.where(and_(*bank_filters))

        rows, total = await _safe_list_query(
            db, BankAuction, count_q, data_q, offset, page.limit, with_total=page.include_total
        )
        has_more = len(rows) > page.limit
        items = rows[: page.limit]
        next_payload = offset_payload(offset + page.limit) if has_more else None
        return build_cursor_page(items, limit=page.limit, next_payload=next_payload, total=total)
