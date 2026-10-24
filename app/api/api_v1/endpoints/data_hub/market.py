"""Micro-market, market pulse, and map endpoints.

Micro-markets and market pulse are derived from RERA filings, so they sit behind
the same ``settings.HRERA_DATA_ENABLED`` gate as the rest of the HRERA surface.

A micro-market's statistics are scoped by ``rera_projects.micro_market_id``, the
link ``MicroMarketScraper`` writes from each project's own filed address. Scoping
by district instead would give every micro-market in one district the same
project count and the same average rate under a different name.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.data_hub import (
    MarketPulseSnapshot,
    MicroMarket,
    ReraProject,
    ReraProjectProfile,
)
from app.models.enums import ProjectStage
from app.schemas.data_hub import (
    MarketPulseResponse,
    MicroMarketDetailResponse,
    MicroMarketResponse,
    ProjectMapPointResponse,
)

from .projects import execute_safe
from .rera import _require_hrera_enabled

router = APIRouter()

# Micro-markets, pulse rows, and map pins are bounded sets. The public contract
# types each as a plain list, so each carries a hard cap instead of a cursor.
MICRO_MARKET_LIMIT = 200
MARKET_PULSE_LIMIT = 100
MAP_POINT_LIMIT = 500


def _as_float(value: Any) -> float | None:
    return None if value is None else float(value)


def _empty_stage_breakdown() -> dict[str, int]:
    return {stage.value: 0 for stage in ProjectStage}


def _city_matches(city: str, column: Any = None):
    """Case- and separator-insensitive city match.

    The site redirects every path containing an uppercase letter to its lowercase
    form, so the public micro-market URL is always ``/micro-markets/gurugram/...``
    even though the filed district is ``Gurugram``. Matching exactly here would
    make every micro-market page 404 on a link the site itself emits.

    A canonical city keeps the spaces its register filed — Delhi's districts are
    ``New Delhi``, ``South West Delhi``, ``North West Delhi`` — and a path segment
    cannot carry a space without percent-encoding it. The public path therefore
    joins the words with hyphens, so both spellings are accepted here: the hyphen
    form is what the site links and the space form is what a reader may type. The
    exact branch comes first, which also keeps a city that genuinely contains a
    hyphen matching itself rather than being rewritten into a different place.

    ``column`` defaults to the micro-market city so the callers that read a market
    stay unchanged; the market-pulse filter passes its own column so both routes
    answer one city name the same way.
    """
    target = column if column is not None else MicroMarket.city
    normalized = city.strip().lower()
    return or_(
        func.lower(target) == normalized,
        func.lower(target) == normalized.replace("-", " "),
    )


@router.get(
    "/micro-markets",
    response_model=list[MicroMarketResponse],
    summary="List micro-markets",
    responses={503: {"description": "HRERA surface turned off by configuration"}},
)
async def list_micro_markets(
    city: str | None = Query(None, description="Filter to one city"),
    db: AsyncSession = Depends(get_db),
):
    """List micro-markets, optionally filtered to one city."""
    _require_hrera_enabled()
    stmt = select(MicroMarket)
    if city:
        stmt = stmt.where(_city_matches(city))
    stmt = (
        stmt.order_by(MicroMarket.city, MicroMarket.slug, MicroMarket.id)
        .limit(MICRO_MARKET_LIMIT)
    )
    rows = await execute_safe(db, stmt, mode="scalars")
    return [MicroMarketResponse.model_validate(market) for market in rows]


@router.get(
    "/micro-markets/{city}/{slug}",
    response_model=MicroMarketDetailResponse,
    summary="Get micro-market detail",
    responses={503: {"description": "HRERA surface turned off by configuration"}},
)
async def get_micro_market(city: str, slug: str, db: AsyncSession = Depends(get_db)):
    """Return one micro-market with the stats for the projects that filed in it."""
    _require_hrera_enabled()
    # ``_city_matches`` is case-insensitive while ``uq_micro_markets_city_slug``
    # is not, so two rows that differ only in the case of ``city`` can both match
    # this path — a duplicate the writer can produce from two filings that spell
    # one district differently. Reading without a bound made that a 500
    # (``scalar_one_or_none`` raises on two rows); the lowest id wins, which keeps
    # the page up and the choice stable across requests.
    market = await execute_safe(
        db,
        select(MicroMarket)
        .where(_city_matches(city), MicroMarket.slug == slug)
        .order_by(MicroMarket.id)
        .limit(1),
        mode="one_or_none",
    )
    if market is None:
        raise HTTPException(status_code=404, detail="Micro market not found")

    # Scoped by the project's own link, not by district. Scoping by district made
    # every micro-market in one district report the same project count and the
    # same average rate under a different name — /micro-markets/gurugram/
    # sector-76-77 and /micro-markets/gurugram/golf-course-road both claimed every
    # project in Gurugram. The link is written by MicroMarketScraper from the same
    # derivation that named this market, so these are the projects that actually
    # filed an address in it.
    stage_breakdown = _empty_stage_breakdown()
    project_count = await execute_safe(
        db,
        select(func.count())
        .select_from(ReraProject)
        .where(ReraProject.micro_market_id == market.id),
        mode="scalar",
    )
    avg_price_per_sqft = _as_float(
        await execute_safe(
            db,
            select(func.avg(ReraProjectProfile.current_price_per_sqft))
            .select_from(ReraProject)
            .join(
                ReraProjectProfile,
                ReraProjectProfile.rera_project_id == ReraProject.id,
            )
            .where(
                ReraProject.micro_market_id == market.id,
                ReraProjectProfile.current_price_per_sqft.isnot(None),
            ),
            mode="one_or_none",
        )
    )
    stage_rows = await execute_safe(
        db,
        select(ReraProjectProfile.stage, func.count())
        .select_from(ReraProject)
        .join(ReraProjectProfile, ReraProjectProfile.rera_project_id == ReraProject.id)
        .where(
            ReraProject.micro_market_id == market.id,
            ReraProjectProfile.stage.isnot(None),
        )
        .group_by(ReraProjectProfile.stage),
    )
    for stage, count in stage_rows:
        if stage is not None:
            stage_breakdown[stage.value if hasattr(stage, "value") else str(stage)] = count

    if avg_price_per_sqft is not None:
        avg_price_per_sqft = round(avg_price_per_sqft, 2)

    return MicroMarketDetailResponse(
        **MicroMarketResponse.model_validate(market).model_dump(),
        project_count=project_count,
        avg_price_per_sqft=avg_price_per_sqft,
        stage_breakdown=stage_breakdown,
    )


@router.get(
    "/market-pulse",
    response_model=list[MarketPulseResponse],
    summary="List market pulse snapshots",
    responses={503: {"description": "HRERA surface turned off by configuration"}},
)
async def list_market_pulse(
    city: str | None = Query(None, description="Filter to one city"),
    db: AsyncSession = Depends(get_db),
):
    """Return the latest snapshot per city, optionally limited to one city."""
    _require_hrera_enabled()
    stmt = select(MarketPulseSnapshot)
    if city:
        # Case-insensitive like the micro-market `{city}` segment, and for the
        # same reason: the site 301s any path containing an uppercase letter to
        # its lowercase form, so a client that reuses a city it read off a URL
        # would otherwise filter this list to nothing and show an empty page.
        stmt = stmt.where(_city_matches(city, MarketPulseSnapshot.city))
    # DISTINCT ON keeps one row per city: the newest captured_on, id breaking ties.
    stmt = (
        stmt.distinct(MarketPulseSnapshot.city)
        .order_by(
            MarketPulseSnapshot.city,
            MarketPulseSnapshot.captured_on.desc(),
            MarketPulseSnapshot.id.desc(),
        )
        .limit(MARKET_PULSE_LIMIT)
    )
    rows = await execute_safe(db, stmt, mode="scalars")
    return [MarketPulseResponse.model_validate(snapshot) for snapshot in rows]


@router.get(
    "/map/projects",
    response_model=list[ProjectMapPointResponse],
    summary="List project map points",
    responses={503: {"description": "HRERA surface turned off by configuration"}},
)
async def list_map_projects(
    min_lat: float = Query(..., ge=-90, le=90),
    max_lat: float = Query(..., ge=-90, le=90),
    min_lng: float = Query(..., ge=-180, le=180),
    max_lng: float = Query(..., ge=-180, le=180),
    db: AsyncSession = Depends(get_db),
):
    """Return the project pins inside a bounding box, capped at a constant."""
    _require_hrera_enabled()
    stmt = (
        select(ReraProject, ReraProjectProfile)
        .join(ReraProjectProfile, ReraProjectProfile.rera_project_id == ReraProject.id)
        .where(
            ReraProject.slug.isnot(None),
            ReraProjectProfile.latitude.isnot(None),
            ReraProjectProfile.longitude.isnot(None),
            ReraProjectProfile.latitude >= min_lat,
            ReraProjectProfile.latitude <= max_lat,
            ReraProjectProfile.longitude >= min_lng,
            ReraProjectProfile.longitude <= max_lng,
        )
        .order_by(ReraProject.id)
        .limit(MAP_POINT_LIMIT)
    )
    rows = await execute_safe(db, stmt)
    return [
        ProjectMapPointResponse(
            slug=project.slug,
            project_name=project.project_name,
            developer_name=project.developer_name,
            latitude=_as_float(profile.latitude),
            longitude=_as_float(profile.longitude),
            stage=profile.stage,
        )
        for project, profile in rows
    ]
