"""GET /data-hub/auctions: source and bank filters for each kind."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
import pytest_asyncio

from app.models.data_hub import BankAuction, CourtAuction
from app.models.enums import AuctionSource


@pytest_asyncio.fixture
async def court_rows(db_session):
    """Two court rows from different sources in the same city."""
    rows = [
        CourtAuction(
            source=AuctionSource.sarfaesi,
            case_number="FILTER-COURT-SARFAESI",
            borrower_name="Sarfaesi Borrower",
            city="Gurugram",
            property_type="residential",
            reserve_price=Decimal("4500000.00"),
            auction_date=date(2026, 11, 1),
            is_active=True,
        ),
        CourtAuction(
            source=AuctionSource.ibapi,
            case_number="FILTER-COURT-IBAPI",
            borrower_name="Ibapi Borrower",
            city="Gurugram",
            property_type="residential",
            reserve_price=Decimal("5500000.00"),
            auction_date=date(2026, 11, 2),
            is_active=True,
        ),
    ]
    db_session.add_all(rows)
    await db_session.commit()
    return rows


@pytest_asyncio.fixture
async def bank_rows(db_session):
    """Two bank rows from different sources."""
    rows = [
        BankAuction(
            source=AuctionSource.sarfaesi,
            bank_name="Filter Bank",
            property_description="Flat 1",
            city="Gurugram",
            property_type="residential",
            reserve_price=Decimal("3500000.00"),
            auction_date=date(2026, 11, 3),
            is_active=True,
        ),
        BankAuction(
            source=AuctionSource.ibapi,
            bank_name="Filter Bank",
            property_description="Flat 2",
            city="Gurugram",
            property_type="residential",
            reserve_price=Decimal("3600000.00"),
            auction_date=date(2026, 11, 4),
            is_active=True,
        ),
    ]
    db_session.add_all(rows)
    await db_session.commit()
    return rows


def _case_numbers(body: dict) -> list[str]:
    return sorted(item["case_number"] for item in body["items"])


@pytest.mark.asyncio
async def test_court_source_filter_returns_only_that_source(client, court_rows):
    response = await client.get(
        "/api/v1/data-hub/auctions", params={"type": "court", "source": "ibapi"}
    )

    assert response.status_code == 200, response.text
    assert _case_numbers(response.json()) == ["FILTER-COURT-IBAPI"]


@pytest.mark.asyncio
async def test_court_without_source_filter_returns_every_source(client, court_rows):
    response = await client.get("/api/v1/data-hub/auctions", params={"type": "court"})

    assert response.status_code == 200, response.text
    assert _case_numbers(response.json()) == ["FILTER-COURT-IBAPI", "FILTER-COURT-SARFAESI"]


@pytest.mark.asyncio
async def test_court_with_bank_filter_is_refused(client, court_rows):
    response = await client.get(
        "/api/v1/data-hub/auctions", params={"type": "court", "bank": "Filter Bank"}
    )

    assert response.status_code == 422, response.text
    error = response.json()["error"]
    assert error["code"] == "FILTER_NOT_SUPPORTED_FOR_KIND"
    assert error["details"]["field"] == "query.bank"


@pytest.mark.asyncio
async def test_bank_source_filter_returns_only_that_source(client, bank_rows):
    response = await client.get(
        "/api/v1/data-hub/auctions", params={"type": "bank", "source": "sarfaesi"}
    )

    assert response.status_code == 200, response.text
    items = response.json()["items"]
    assert len(items) == 1
    assert items[0]["source"] == "sarfaesi"


@pytest.mark.asyncio
async def test_bank_bank_filter_matches_bank_name(client, bank_rows):
    response = await client.get(
        "/api/v1/data-hub/auctions", params={"type": "bank", "bank": "Filter"}
    )

    assert response.status_code == 200, response.text
    assert len(response.json()["items"]) == 2


@pytest.mark.asyncio
async def test_source_categories_is_one_page_with_group_and_count(client, bank_rows):
    response = await client.get("/api/v1/data-hub/auctions/source-categories")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["has_more"] is False
    assert body["total"] is None
    items = body["items"]
    assert {item["category"] for item in items} >= {
        "central",
        "delhi",
        "gurgaon",
        "meerut",
        "aggregators",
        "banks",
    }
    sarfaesi = [item for item in items if item["source"] == "sarfaesi"]
    assert len(sarfaesi) == 1
    assert sarfaesi[0]["category"] == "banks"
    assert sarfaesi[0]["count"] == 1
