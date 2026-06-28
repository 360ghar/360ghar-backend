"""Jamabandi cache service — user-initiated lookups with CAPTCHA proxy."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.data_hub import JamabandiCache
from app.services.data_hub.base_scraper import BaseScraper

logger = logging.getLogger(__name__)

_JAMABANDI_BASE = "https://jamabandi.nic.in"
_CAPTCHA_URL = f"{_JAMABANDI_BASE}/captcha/get"

# Cache TTL: 7 days (configurable via settings)
_CACHE_TTL_DAYS = 7


class JamabandiScraper(BaseScraper):
    """
    Jamabandi is user-initiated — CAPTCHA is solved by the user in the browser.
    This scraper is NOT called by the scheduler. It is called directly by the
    API endpoint when a user submits a lookup request with their CAPTCHA token.

    The base `run()` / scheduler methods are unused; direct methods are called by the API.
    """
    name = "jamabandi"

    async def _scrape(self) -> list[dict]:
        # Not used by scheduler — jamabandi is user-initiated
        return []

    async def _upsert(self, db: AsyncSession, records: list[dict]) -> dict:
        # Not used by scheduler
        return {"found": 0, "upserted": 0, "failed": 0}

    async def get_captcha_bytes(self) -> bytes:
        """Proxy CAPTCHA image from Jamabandi site."""
        from app.core.http import get_scraper_client

        client = get_scraper_client()
        resp = await client.get(_CAPTCHA_URL, timeout=15.0)
        resp.raise_for_status()
        return resp.content

    async def lookup(
        self,
        db: AsyncSession,
        tehsil: str,
        village: str,
        khasra_number: str,
        captcha_token: str,
    ) -> dict | None:
        """
        Lookup land record. Returns cached result if fresh, else fetches from Jamabandi.
        CAPTCHA token from the user's browser session.
        """
        cache_ttl = getattr(settings, "JAMABANDI_CACHE_TTL_DAYS", _CACHE_TTL_DAYS)
        cached = await self._get_cached(db, tehsil, village, khasra_number)
        if cached:
            return self._row_to_dict(cached, is_cached=True)

        # Fetch from Jamabandi
        try:
            result = await self._fetch_from_jamabandi(tehsil, village, khasra_number, captcha_token)
        except Exception as e:
            logger.error("Jamabandi lookup failed: %s", e)
            return None

        # Cache the result
        if result:
            await self._cache_result(db, tehsil, village, khasra_number, result, cache_ttl)
        return result

    async def _get_cached(
        self, db: AsyncSession, tehsil: str, village: str, khasra_number: str
    ) -> JamabandiCache | None:
        """Return a cache row if present and not expired."""
        now = datetime.now(timezone.utc)
        result = await db.execute(
            select(JamabandiCache)
            .where(
                JamabandiCache.tehsil == tehsil,
                JamabandiCache.village == village,
                JamabandiCache.khasra_number == khasra_number,
                JamabandiCache.expires_at > now,
            )
        )
        return result.scalar_one_or_none()

    async def _fetch_from_jamabandi(
        self, tehsil: str, village: str, khasra_number: str, captcha_token: str
    ) -> dict | None:
        """Submit the land records form and parse the result."""
        from app.core.http import get_scraper_client

        client = get_scraper_client()
        payload = {
            "tehsil": tehsil,
            "village": village,
            "khasra": khasra_number,
            "captcha": captcha_token,
        }
        resp = await client.post(
            f"{_JAMABANDI_BASE}/land records/NakalRecord", data=payload, timeout=60.0
        )
        resp.raise_for_status()
        return self._parse_nakal_html(resp.text, tehsil, village, khasra_number)

    def _parse_nakal_html(
        self, html: str, tehsil: str, village: str, khasra_number: str
    ) -> dict:
        """Parse ownership details from Jamabandi nakal HTML."""
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")
        owner_names = []
        area_kanal = None
        area_marla = None
        mutation_status = None
        encumbrance = None

        # Parse owner names (typically in a table)
        for row in soup.select("table tr"):
            cells = [td.get_text(strip=True) for td in row.find_all("td")]
            if len(cells) >= 2:
                label = cells[0].lower()
                val = cells[1].strip()
                if "khatedar" in label or "owner" in label or "malik" in label:
                    if val and val not in owner_names:
                        owner_names.append(val)
                elif "kanal" in label:
                    try:
                        area_kanal = float(val)
                    except ValueError:
                        pass
                elif "marla" in label:
                    try:
                        area_marla = float(val)
                    except ValueError:
                        pass
                elif "mutation" in label or "intkal" in label:
                    mutation_status = val
                elif "encumbrance" in label or "bojh" in label:
                    encumbrance = val

        return {
            "tehsil": tehsil,
            "village": village,
            "khasra_number": khasra_number,
            "owner_names": owner_names,
            "area_kanal": area_kanal,
            "area_marla": area_marla,
            "mutation_status": mutation_status,
            "encumbrance_details": encumbrance,
            "source_html": html[:5000],  # store partial HTML for audit
            "fetched_at": datetime.now(timezone.utc),
            "is_cached": False,
        }

    async def _cache_result(
        self, db: AsyncSession, tehsil: str, village: str,
        khasra_number: str, result: dict, ttl_days: int
    ) -> None:
        from sqlalchemy.dialects.postgresql import insert as pg_insert
        expires_at = datetime.now(timezone.utc) + timedelta(days=ttl_days)
        values = {
            "tehsil": tehsil,
            "village": village,
            "khasra_number": khasra_number,
            "owner_names": result.get("owner_names"),
            "area_kanal": result.get("area_kanal"),
            "area_marla": result.get("area_marla"),
            "mutation_status": result.get("mutation_status"),
            "encumbrance_details": result.get("encumbrance_details"),
            "source_html": result.get("source_html"),
            "fetched_at": datetime.now(timezone.utc),
            "expires_at": expires_at,
        }
        stmt = pg_insert(JamabandiCache).values(**values)
        stmt = stmt.on_conflict_do_update(
            index_elements=["tehsil", "village", "khasra_number"],
            set_={
                "owner_names": stmt.excluded.owner_names,
                "area_kanal": stmt.excluded.area_kanal,
                "area_marla": stmt.excluded.area_marla,
                "mutation_status": stmt.excluded.mutation_status,
                "encumbrance_details": stmt.excluded.encumbrance_details,
                "source_html": stmt.excluded.source_html,
                "fetched_at": stmt.excluded.fetched_at,
                "expires_at": stmt.excluded.expires_at,
            }
        )
        await db.execute(stmt)
        await db.commit()

    def _row_to_dict(self, row: JamabandiCache, is_cached: bool = True) -> dict:
        return {
            "tehsil": row.tehsil,
            "village": row.village,
            "khasra_number": row.khasra_number,
            "owner_names": row.owner_names or [],
            "area_kanal": float(row.area_kanal) if row.area_kanal else None,
            "area_marla": float(row.area_marla) if row.area_marla else None,
            "mutation_status": row.mutation_status,
            "encumbrance_details": row.encumbrance_details,
            "fetched_at": row.fetched_at,
            "is_cached": is_cached,
        }
