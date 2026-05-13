"""Neighbourhood score scraper — Google Places API scoring for property listings."""
import asyncio
import logging
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.data_hub import NeighbourhoodScore
from app.services.data_hub.base_scraper import BaseScraper

logger = logging.getLogger(__name__)

_PLACES_URL = "https://maps.googleapis.com/maps/api/place/nearbysearch/json"

# Place types to search for each category
_CATEGORY_TYPES = {
    "transit": ["subway_station", "bus_station", "train_station"],
    "education": ["school", "university", "library"],
    "health": ["hospital", "pharmacy", "doctor"],
    "retail": ["shopping_mall", "supermarket", "grocery_or_supermarket"],
}

_STALE_DAYS = 30  # days before score expires


class NeighbourhoodScraper(BaseScraper):
    name = "neighbourhood"

    def __init__(self, listing_ids: list[int] | None = None):
        """
        listing_ids: specific listings to score.
        If None, the scheduler will score all stale/unscored listings.
        """
        self._listing_ids = listing_ids

    async def _scrape(self) -> list[dict]:
        """Fetch property coordinates, then score via Google Places."""
        api_key = getattr(settings, "GOOGLE_PLACES_API_KEY", None)
        if not api_key:
            logger.warning(
                "GOOGLE_PLACES_API_KEY not configured — neighbourhood scoring skipped"
            )
            return []

        from app.core.database import get_bg_session_factory
        session_factory = get_bg_session_factory()
        async with session_factory() as db:
            listings_to_score = await self._get_listings_to_score(db)

        results = []
        daily_cap = getattr(settings, "GOOGLE_PLACES_MAX_DAILY_CALLS", 1000)
        calls_made = 0

        for listing_id, lat, lng in listings_to_score:
            if lat is None or lng is None:
                continue
            if calls_made >= daily_cap:
                logger.info("Daily Google Places API cap reached (%d)", daily_cap)
                break
            try:
                score_data = await self._score_location(float(lat), float(lng), api_key)
                score_data["listing_id"] = listing_id
                results.append(score_data)
                calls_made += score_data.get("api_calls_made", 0)
                await asyncio.sleep(0.5)
            except Exception as e:
                logger.warning("Failed to score listing %s: %s", listing_id, e)

        return results

    async def _get_listings_to_score(self, db: AsyncSession) -> list[tuple]:
        """Return (listing_id, lat, lng) for stale or unscored listings."""
        from app.models.properties import Property

        now = datetime.now(timezone.utc)

        if self._listing_ids:
            result = await db.execute(
                select(Property.id, Property.latitude, Property.longitude).where(
                    Property.id.in_(self._listing_ids)
                )
            )
            return [(row.id, row.latitude, row.longitude) for row in result]

        # IDs with a stale score
        stale_result = await db.execute(
            select(NeighbourhoodScore.listing_id).where(
                NeighbourhoodScore.stale_after < now
            )
        )
        stale_ids = {row.listing_id for row in stale_result}

        # All currently scored IDs
        scored_result = await db.execute(select(NeighbourhoodScore.listing_id))
        all_scored_ids = {row.listing_id for row in scored_result}

        # Fresh (non-stale) scored IDs — skip these
        fresh_scored_ids = all_scored_ids - stale_ids

        # Fetch properties that are either unscored or stale
        unscored_result = await db.execute(
            select(Property.id, Property.latitude, Property.longitude)
            .where(Property.id.notin_(fresh_scored_ids))
            .limit(100)
        )
        return [(row.id, row.latitude, row.longitude) for row in unscored_result]

    async def _score_location(self, lat: float, lng: float, api_key: str) -> dict:
        """Call Google Places API for each category and compute scores."""
        location_str = f"{lat},{lng}"
        radius = getattr(settings, "NEIGHBOURHOOD_SCORE_RADIUS_M", 1500)
        category_scores: dict[str, int] = {}
        nearby_places: list[dict] = []
        metro_stations: list[dict] = []
        schools: list[dict] = []
        hospitals: list[dict] = []
        malls: list[dict] = []
        api_calls = 0

        async with httpx.AsyncClient(timeout=15.0) as client:
            for category, place_types in _CATEGORY_TYPES.items():
                category_count = 0
                for ptype in place_types:
                    params = {
                        "location": location_str,
                        "radius": radius,
                        "type": ptype,
                        "key": api_key,
                    }
                    try:
                        resp = await client.get(_PLACES_URL, params=params)
                        resp.raise_for_status()
                        data = resp.json()
                        api_calls += 1
                        places = data.get("results", [])
                        category_count += len(places)
                        for p in places[:3]:  # top 3 per type
                            place_info = {
                                "name": p.get("name"),
                                "type": ptype,
                                "distance_m": None,  # would need Distance Matrix API
                                "rating": p.get("rating"),
                            }
                            nearby_places.append(place_info)
                            if ptype == "subway_station":
                                metro_stations.append(place_info)
                            elif ptype in ("school", "university"):
                                schools.append(place_info)
                            elif ptype == "hospital":
                                hospitals.append(place_info)
                            elif ptype == "shopping_mall":
                                malls.append(place_info)
                        await asyncio.sleep(0.2)
                    except Exception as e:
                        logger.warning("Places API error for %s: %s", ptype, e)
                # Score: min(count * 15, 100) — 7 places = full score
                category_scores[category] = min(category_count * 15, 100)

        overall = int(sum(category_scores.values()) / max(len(category_scores), 1))
        stale_after = datetime.now(timezone.utc) + timedelta(days=_STALE_DAYS)

        return {
            "overall_score": overall,
            "category_scores": category_scores,
            "nearby_places": nearby_places[:20],
            "metro_stations": metro_stations[:5],
            "schools": schools[:5],
            "hospitals": hospitals[:5],
            "malls": malls[:5],
            "api_calls_made": api_calls,
            "last_fetched_at": datetime.now(timezone.utc),
            "stale_after": stale_after,
            "latitude": lat,
            "longitude": lng,
        }

    async def _upsert(self, db: AsyncSession, records: list[dict]) -> dict:
        found = len(records)
        upserted = 0
        failed = 0
        for rec in records:
            try:
                values = {
                    k: v
                    for k, v in rec.items()
                    if hasattr(NeighbourhoodScore, k)
                    and k not in ("id", "created_at", "updated_at")
                }
                stmt = pg_insert(NeighbourhoodScore).values(**values)
                stmt = stmt.on_conflict_do_update(
                    index_elements=["listing_id"],
                    set_={
                        "overall_score": stmt.excluded.overall_score,
                        "category_scores": stmt.excluded.category_scores,
                        "nearby_places": stmt.excluded.nearby_places,
                        "metro_stations": stmt.excluded.metro_stations,
                        "schools": stmt.excluded.schools,
                        "hospitals": stmt.excluded.hospitals,
                        "malls": stmt.excluded.malls,
                        "api_calls_made": stmt.excluded.api_calls_made,
                        "last_fetched_at": stmt.excluded.last_fetched_at,
                        "stale_after": stmt.excluded.stale_after,
                        "latitude": stmt.excluded.latitude,
                        "longitude": stmt.excluded.longitude,
                    },
                )
                await db.execute(stmt)
                upserted += 1
            except Exception as e:
                logger.warning("Failed to upsert neighbourhood score: %s", e)
                await db.rollback()
                failed += 1
        await db.commit()
        return {"found": found, "upserted": upserted, "failed": failed}
