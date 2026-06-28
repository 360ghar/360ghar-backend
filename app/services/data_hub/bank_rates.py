"""Bank rate scraper — RBI repo rate (HTML page) + major bank MCLR rates."""
from __future__ import annotations

import asyncio
import logging
import re
from datetime import date

from bs4 import BeautifulSoup
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.data_hub import BankRate
from app.services.data_hub.base_scraper import BaseScraper

logger = logging.getLogger(__name__)

_RBI_DATA_URL = "https://www.rbi.org.in/Scripts/BS_PressReleaseDisplay.aspx"  # best-effort

_BANK_MCLR_URLS = {
    "HDFC Bank": "https://www.hdfcbank.com/content/api/propertyValue?id=MCLRRatesNew",
    "SBI": "https://homeloans.sbi/interest-rate",
    "ICICI Bank": "https://www.icicibank.com/personal-banking/loans/home-loan/home-loan-interest-rates",
}


class BankRateScraper(BaseScraper):
    name = "bank_rates"

    async def _scrape(self) -> list[dict]:
        results = []
        # Try RBI repo rate page
        try:
            html = await self._fetch_url(_RBI_DATA_URL)
            repo_rate = self._parse_rbi_repo_rate(html)
            if repo_rate:
                results.append(repo_rate)
        except Exception as e:
            logger.warning("Failed to fetch RBI rate: %s", e)
        # Try bank MCLR pages
        for bank_name, url in _BANK_MCLR_URLS.items():
            try:
                html = await self._fetch_url(url)
                rates = self._parse_bank_mclr(html, bank_name, url)
                results.extend(rates)
                await asyncio.sleep(2)
            except Exception as e:
                logger.warning("Failed to fetch %s MCLR: %s", bank_name, e)
        return results

    def _parse_rbi_repo_rate(self, html: str) -> dict | None:
        """Parse RBI repo rate from press release page."""
        soup = BeautifulSoup(html, "html.parser")
        text = soup.get_text()
        match = re.search(
            r"repo rate[^\d]*(\d+\.?\d*)\s*(?:per cent|%)", text, re.IGNORECASE
        )
        if match:
            return {
                "bank_name": "RBI",
                "rate_type": "repo",
                "rate_value": float(match.group(1)),
                "effective_date": date.today(),
                "source": _RBI_DATA_URL,
                "raw_data": {"parsed_text": match.group(0)},
            }
        return None

    def _parse_bank_mclr(self, html: str, bank_name: str, source_url: str) -> list[dict]:
        """Best-effort parse of bank MCLR table."""
        soup = BeautifulSoup(html, "html.parser")
        rates = []
        text = soup.get_text()
        matches = re.findall(r"(\d+\.\d+)\s*%", text)
        if matches:
            # Take the first reasonable looking rate (6-20%)
            for m in matches[:3]:
                val = float(m)
                if 6.0 <= val <= 20.0:
                    rates.append(
                        {
                            "bank_name": bank_name,
                            "rate_type": "home_loan_min",
                            "rate_value": val,
                            "effective_date": date.today(),
                            "source": source_url,
                            "raw_data": {"parsed": m},
                        }
                    )
                    break
        return rates

    async def _upsert(self, db: AsyncSession, records: list[dict]) -> dict:
        found = len(records)
        upserted = 0
        failed = 0
        for rec in records:
            try:
                stmt = pg_insert(BankRate).values(
                    **{
                        k: v
                        for k, v in rec.items()
                        if hasattr(BankRate, k) and k not in ("id", "created_at", "updated_at")
                    }
                )
                stmt = stmt.on_conflict_do_update(
                    index_elements=["bank_name", "rate_type", "effective_date"],
                    set_={
                        "rate_value": stmt.excluded.rate_value,
                        "raw_data": stmt.excluded.raw_data,
                    },
                )
                await db.execute(stmt)
                upserted += 1
            except Exception as e:
                logger.warning("Failed to upsert bank rate: %s", e)
                await db.rollback()
                failed += 1
        await db.commit()
        return {"found": found, "upserted": upserted, "failed": failed}
