"""Neighbourhood score endpoints."""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.api_v1.dependencies.auth import get_current_admin
from app.core.database import get_db
from app.models.data_hub import NeighbourhoodScore
from app.models.users import User
from app.schemas.data_hub import NeighbourhoodScoreResponse, ScraperTriggerResult

router = APIRouter()


def _place_list(value: object) -> list[dict[str, Any]]:
    """Stored place lists are JSON lists of objects. Anything else is an empty list."""
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


@router.get(
    "/neighbourhood/{listing_id}",
    response_model=NeighbourhoodScoreResponse,
    summary="Get neighbourhood score",
)
async def get_neighbourhood_score(listing_id: int, db: AsyncSession = Depends(get_db)):
    """Get neighbourhood score for a property listing."""
    result = await db.execute(
        select(NeighbourhoodScore).where(NeighbourhoodScore.listing_id == listing_id)
    )
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Neighbourhood score not found")

    # Populate individual category scores from the JSON dict
    category_scores = row.category_scores or {}
    return NeighbourhoodScoreResponse(
        id=row.id,
        listing_id=row.listing_id,
        overall_score=row.overall_score,
        transit_score=category_scores.get("transit"),
        education_score=category_scores.get("education"),
        health_score=category_scores.get("health"),
        retail_score=category_scores.get("retail"),
        nearby_places=_place_list(row.nearby_places),
        metro_stations=_place_list(row.metro_stations),
        schools=_place_list(row.schools),
        hospitals=_place_list(row.hospitals),
        stale_after=row.stale_after,
        last_fetched_at=row.last_fetched_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


@router.post(
    "/neighbourhood/{listing_id}/refresh",
    response_model=ScraperTriggerResult,
    summary="Refresh neighbourhood score",
)
async def refresh_neighbourhood_score(
    listing_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin),
):
    """Trigger a neighbourhood score refresh for a listing (admin only)."""
    from app.services.data_hub.neighbourhood import NeighbourhoodScraper

    scraper = NeighbourhoodScraper(listing_ids=[listing_id])
    result = await scraper.run(run_type="manual", triggered_by=current_user.id)
    return ScraperTriggerResult(message="Neighbourhood refresh triggered", result=result)
