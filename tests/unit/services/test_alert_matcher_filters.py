"""AlertMatcherService applies the city and keyword filters of an auction alert (be-content-11).

A null city or keyword matches every city or every description.
"""

from __future__ import annotations

import pytest

from app.models.data_hub import AuctionAlert, BankAuction, CourtAuction
from app.models.enums import AuctionSource
from app.services.data_hub.alerts import AlertMatcherService


@pytest.mark.asyncio
async def test_city_and_keyword_filters_select_matching_auctions(db_session, test_user):
    bank_mumbai_villa = BankAuction(
        source=AuctionSource.sarfaesi,
        bank_name="SBI",
        property_description="Luxury villa with a garden",
        city="Mumbai",
    )
    bank_pune_flat = BankAuction(
        source=AuctionSource.sarfaesi,
        bank_name="SBI",
        property_description="Flat in a tower block",
        city="Pune",
    )
    court_mumbai_plot = CourtAuction(
        source=AuctionSource.drt,
        case_number="OA-1/2026",
        property_description="Plot of land near the highway",
        city="Mumbai",
    )
    db_session.add_all([bank_mumbai_villa, bank_pune_flat, court_mumbai_plot])
    await db_session.flush()

    city_and_keyword = AuctionAlert(user_id=test_user.id, city="Mumbai", keyword="villa")
    any_city_any_keyword = AuctionAlert(user_id=test_user.id)
    pune_only = AuctionAlert(user_id=test_user.id, city="Pune")
    db_session.add_all([city_and_keyword, any_city_any_keyword, pune_only])
    await db_session.flush()

    matches = await AlertMatcherService()._find_matches(db_session)
    found = {
        (m["alert_id"], m["auction_type"], m["auction_id"])
        for m in matches
        if m["alert_id"] in {city_and_keyword.id, any_city_any_keyword.id, pune_only.id}
    }

    assert found == {
        (city_and_keyword.id, "bank", bank_mumbai_villa.id),
        (any_city_any_keyword.id, "bank", bank_mumbai_villa.id),
        (any_city_any_keyword.id, "bank", bank_pune_flat.id),
        (any_city_any_keyword.id, "court", court_mumbai_plot.id),
        (pune_only.id, "bank", bank_pune_flat.id),
    }
