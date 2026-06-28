"""Integration tests for data hub upserts using column-based ON CONFLICT.

These tests verify that the index_elements-based upsert pattern works
against a real PostgreSQL instance — catching schema/code mismatches
(e.g., constraint name vs index name discrepancies) that unit tests miss.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.data_hub import (
    BankAuction,
    BankRate,
    CircleRate,
    CourtAuction,
    JamabandiCache,
    ZoningData,
)
from app.models.enums import AuctionSource

pytestmark = pytest.mark.integration


@pytest.fixture()
def _seed_data():
    """Minimal seed data for each model, respecting NOT NULL constraints."""
    return {
        "bank_auction": {
            "source": AuctionSource.sarfaesi,
            "bank_name": "Test Bank",
            "property_description": "Test property description",
            "city": "Test City",
            "normalized_address_hash": "abc123hash",
            "auction_date": date(2026, 1, 15),
            "reserve_price": 1000000,
            "is_active": True,
        },
        "court_auction": {
            "source": AuctionSource.ecourts,
            "case_number": "CA-2026-001",
            "city": "Test City",
            "auction_date": date(2026, 2, 20),
            "is_active": True,
        },
        "bank_rate": {
            "bank_name": "Test Bank",
            "rate_type": "home_loan_min",
            "rate_value": 8.5,
            "effective_date": date(2026, 1, 1),
        },
        "jamabandi_cache": {
            "tehsil": "Test Tehsil",
            "village": "Test Village",
            "khasra_number": "KH-001",
            "expires_at": datetime.now(timezone.utc) + timedelta(hours=1),
        },
        "circle_rate": {
            "sector": "Sector 1",
            "colony": "Test Colony",
            "property_type": "residential",
            "revision_year": 2026,
            "slug": "sector-1-test-colony-residential-2026",
            "rate_per_sqyd": 50000,
        },
        "zoning_data": {
            "sector": "Sector 1",
            "land_use": "residential",
            "slug": "sector-1-residential",
            "far_limit": 2.0,
        },
    }


class TestBankAuctionUpsert:
    """Verify column-based ON CONFLICT works for BankAuction."""

    async def test_insert_and_upsert(
        self, db_session: AsyncSession, _seed_data: dict
    ) -> None:
        data = _seed_data["bank_auction"]
        insert_data = {
            k: v for k, v in data.items() if hasattr(BankAuction, k)
        }

        # First insert
        stmt = pg_insert(BankAuction).values(**insert_data)
        stmt = stmt.on_conflict_do_update(
            index_elements=["bank_name", "normalized_address_hash", "auction_date"],
            set_={"reserve_price": stmt.excluded.reserve_price},
        )
        result = await db_session.execute(stmt)
        assert result.rowcount >= 1

        # Second insert (ON CONFLICT triggers update)
        insert_data["reserve_price"] = 2000000
        stmt2 = pg_insert(BankAuction).values(**insert_data)
        stmt2 = stmt2.on_conflict_do_update(
            index_elements=["bank_name", "normalized_address_hash", "auction_date"],
            set_={"reserve_price": stmt2.excluded.reserve_price},
        )
        result2 = await db_session.execute(stmt2)
        assert result2.rowcount >= 1

        # Verify the value was updated
        row = await db_session.execute(
            select(BankAuction).where(
                BankAuction.bank_name == "Test Bank",
                BankAuction.normalized_address_hash == "abc123hash",
                BankAuction.auction_date == date(2026, 1, 15),
            )
        )
        auction = row.scalar_one()
        assert auction.reserve_price == 2000000


class TestCourtAuctionUpsert:
    """Verify column-based ON CONFLICT works for CourtAuction."""

    async def test_insert_and_upsert(
        self, db_session: AsyncSession, _seed_data: dict
    ) -> None:
        data = _seed_data["court_auction"]
        insert_data = {
            k: v for k, v in data.items() if hasattr(CourtAuction, k)
        }

        # First insert
        stmt = pg_insert(CourtAuction).values(**insert_data)
        stmt = stmt.on_conflict_do_update(
            index_elements=["case_number", "auction_date"],
            set_={"reserve_price": stmt.excluded.reserve_price},
        )
        result = await db_session.execute(stmt)
        assert result.rowcount >= 1

        # Second insert (ON CONFLICT triggers update)
        insert_data["reserve_price"] = 500000
        stmt2 = pg_insert(CourtAuction).values(**insert_data)
        stmt2 = stmt2.on_conflict_do_update(
            index_elements=["case_number", "auction_date"],
            set_={"reserve_price": stmt2.excluded.reserve_price},
        )
        result2 = await db_session.execute(stmt2)
        assert result2.rowcount >= 1

        row = await db_session.execute(
            select(CourtAuction).where(
                CourtAuction.case_number == "CA-2026-001",
                CourtAuction.auction_date == date(2026, 2, 20),
            )
        )
        auction = row.scalar_one()
        assert auction.reserve_price == 500000


class TestBankRateUpsert:
    """Verify column-based ON CONFLICT works for BankRate."""

    async def test_insert_and_upsert(
        self, db_session: AsyncSession, _seed_data: dict
    ) -> None:
        data = _seed_data["bank_rate"]
        insert_data = {k: v for k, v in data.items() if hasattr(BankRate, k)}

        stmt = pg_insert(BankRate).values(**insert_data)
        stmt = stmt.on_conflict_do_update(
            index_elements=["bank_name", "rate_type", "effective_date"],
            set_={"rate_value": stmt.excluded.rate_value},
        )
        result = await db_session.execute(stmt)
        assert result.rowcount >= 1

        insert_data["rate_value"] = 9.0
        stmt2 = pg_insert(BankRate).values(**insert_data)
        stmt2 = stmt2.on_conflict_do_update(
            index_elements=["bank_name", "rate_type", "effective_date"],
            set_={"rate_value": stmt2.excluded.rate_value},
        )
        result2 = await db_session.execute(stmt2)
        assert result2.rowcount >= 1

        row = await db_session.execute(
            select(BankRate).where(
                BankRate.bank_name == "Test Bank",
                BankRate.rate_type == "home_loan_min",
                BankRate.effective_date == date(2026, 1, 1),
            )
        )
        rate = row.scalar_one()
        assert rate.rate_value == 9.0


class TestJamabandiCacheUpsert:
    """Verify column-based ON CONFLICT works for JamabandiCache."""

    async def test_insert_and_upsert(
        self, db_session: AsyncSession, _seed_data: dict
    ) -> None:
        data = _seed_data["jamabandi_cache"]
        insert_data = {
            k: v for k, v in data.items() if hasattr(JamabandiCache, k)
        }

        stmt = pg_insert(JamabandiCache).values(**insert_data)
        stmt = stmt.on_conflict_do_update(
            index_elements=["tehsil", "village", "khasra_number"],
            set_={"khewat_number": stmt.excluded.khewat_number},
        )
        result = await db_session.execute(stmt)
        assert result.rowcount >= 1

        insert_data["khewat_number"] = "KW-999"
        stmt2 = pg_insert(JamabandiCache).values(**insert_data)
        stmt2 = stmt2.on_conflict_do_update(
            index_elements=["tehsil", "village", "khasra_number"],
            set_={"khewat_number": stmt2.excluded.khewat_number},
        )
        result2 = await db_session.execute(stmt2)
        assert result2.rowcount >= 1

        row = await db_session.execute(
            select(JamabandiCache).where(
                JamabandiCache.tehsil == "Test Tehsil",
                JamabandiCache.village == "Test Village",
                JamabandiCache.khasra_number == "KH-001",
            )
        )
        cache = row.scalar_one()
        assert cache.khewat_number == "KW-999"


class TestCircleRateUpsert:
    """Verify column-based ON CONFLICT works for CircleRate."""

    async def test_insert_and_upsert(
        self, db_session: AsyncSession, _seed_data: dict
    ) -> None:
        data = _seed_data["circle_rate"]
        insert_data = {
            k: v for k, v in data.items() if hasattr(CircleRate, k)
        }

        stmt = pg_insert(CircleRate).values(**insert_data)
        stmt = stmt.on_conflict_do_update(
            index_elements=["sector", "colony", "property_type", "revision_year"],
            set_={"rate_per_sqyd": stmt.excluded.rate_per_sqyd},
        )
        result = await db_session.execute(stmt)
        assert result.rowcount >= 1

        insert_data["rate_per_sqyd"] = 60000
        stmt2 = pg_insert(CircleRate).values(**insert_data)
        stmt2 = stmt2.on_conflict_do_update(
            index_elements=["sector", "colony", "property_type", "revision_year"],
            set_={"rate_per_sqyd": stmt2.excluded.rate_per_sqyd},
        )
        result2 = await db_session.execute(stmt2)
        assert result2.rowcount >= 1

        row = await db_session.execute(
            select(CircleRate).where(
                CircleRate.sector == "Sector 1",
                CircleRate.colony == "Test Colony",
                CircleRate.property_type == "residential",
                CircleRate.revision_year == 2026,
            )
        )
        rate = row.scalar_one()
        assert rate.rate_per_sqyd == 60000


class TestZoningDataUpsert:
    """Verify column-based ON CONFLICT works for ZoningData."""

    async def test_insert_and_upsert(
        self, db_session: AsyncSession, _seed_data: dict
    ) -> None:
        data = _seed_data["zoning_data"]
        insert_data = {
            k: v for k, v in data.items() if hasattr(ZoningData, k)
        }

        stmt = pg_insert(ZoningData).values(**insert_data)
        stmt = stmt.on_conflict_do_update(
            index_elements=["sector", "land_use"],
            set_={"far_limit": stmt.excluded.far_limit},
        )
        result = await db_session.execute(stmt)
        assert result.rowcount >= 1

        insert_data["far_limit"] = 3.5
        stmt2 = pg_insert(ZoningData).values(**insert_data)
        stmt2 = stmt2.on_conflict_do_update(
            index_elements=["sector", "land_use"],
            set_={"far_limit": stmt2.excluded.far_limit},
        )
        result2 = await db_session.execute(stmt2)
        assert result2.rowcount >= 1

        row = await db_session.execute(
            select(ZoningData).where(
                ZoningData.sector == "Sector 1",
                ZoningData.land_use == "residential",
            )
        )
        zone = row.scalar_one()
        assert zone.far_limit == 3.5
