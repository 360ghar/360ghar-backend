"""AlertMatcherService applies the city and keyword filters of an auction alert (be-content-11).

A null city or keyword matches every city or every description.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.models.data_hub import AuctionAlert, BankAuction, CourtAuction
from app.models.enums import AuctionSource
from app.services.data_hub.alerts import AlertMatcherService
from app.services.notification_config import NOTIFICATION_TYPES


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


def test_the_auction_alert_type_is_registered():
    # An unregistered type key makes the dispatcher send nothing, so the auction
    # path must have its own registered type.
    assert "auction_alert_match" in NOTIFICATION_TYPES


@pytest.mark.asyncio
async def test_upsert_dispatches_through_the_notification_dispatcher(
    db_session, test_user, monkeypatch
):
    from app.services import notification_dispatcher

    auction = BankAuction(
        source=AuctionSource.sarfaesi,
        bank_name="SBI",
        property_description="Flat in a tower block",
        city="Mumbai",
    )
    db_session.add(auction)
    await db_session.flush()
    alert = AuctionAlert(user_id=test_user.id, city="Mumbai")
    db_session.add(alert)
    await db_session.flush()

    dispatch = AsyncMock(return_value={"type_key": "auction_alert_match", "channels": {}})
    monkeypatch.setattr(notification_dispatcher, "dispatch_notification_to_user", dispatch)

    matches = await AlertMatcherService()._find_matches(db_session)
    stats = await AlertMatcherService()._upsert(db_session, matches)

    assert stats["upserted"] >= 1
    assert stats["failed"] == 0
    assert dispatch.await_args.kwargs["type_key"] == "auction_alert_match"
    assert dispatch.await_args.kwargs["user_db_id"] == test_user.id
    await db_session.refresh(alert)
    assert alert.last_notified_at is not None


@pytest.mark.asyncio
async def test_a_failed_dispatch_leaves_last_notified_at_unset(
    db_session, test_user, monkeypatch
):
    from app.services import notification_dispatcher

    auction = BankAuction(
        source=AuctionSource.sarfaesi,
        bank_name="SBI",
        property_description="Flat in a tower block",
        city="Mumbai",
    )
    db_session.add(auction)
    await db_session.flush()
    alert = AuctionAlert(user_id=test_user.id, city="Mumbai")
    db_session.add(alert)
    await db_session.flush()

    dispatch = AsyncMock(return_value={"type_key": "auction_alert_match", "error": "user_not_found"})
    monkeypatch.setattr(notification_dispatcher, "dispatch_notification_to_user", dispatch)

    matches = await AlertMatcherService()._find_matches(db_session)
    stats = await AlertMatcherService()._upsert(db_session, matches)

    assert stats["failed"] >= 1
    await db_session.refresh(alert)
    assert alert.last_notified_at is None


@pytest.mark.asyncio
async def test_a_sent_auction_is_not_sent_again_on_the_next_run(
    db_session, test_user, monkeypatch
):
    from app.services import notification_dispatcher

    db_session.add(
        BankAuction(
            source=AuctionSource.sarfaesi,
            bank_name="SBI",
            property_description="Flat in a tower block",
            city="Mumbai",
        )
    )
    alert = AuctionAlert(user_id=test_user.id, city="Mumbai", keyword="tower block")
    db_session.add(alert)
    await db_session.flush()
    dispatch = AsyncMock(
        return_value={"type_key": "auction_alert_match", "channels": {"in_app": {"ok": True}}}
    )
    monkeypatch.setattr(notification_dispatcher, "dispatch_notification_to_user", dispatch)

    service = AlertMatcherService()
    first = [m for m in await service._find_matches(db_session) if m["alert_id"] == alert.id]
    await service._upsert(db_session, first)
    second = [m for m in await service._find_matches(db_session) if m["alert_id"] == alert.id]

    assert len(first) == 1
    assert second == []


@pytest.mark.asyncio
async def test_a_dispatch_where_every_channel_failed_counts_as_failed(
    db_session, test_user, monkeypatch
):
    from app.services import notification_dispatcher

    db_session.add(
        BankAuction(
            source=AuctionSource.sarfaesi,
            bank_name="SBI",
            property_description="Shop on the main road",
            city="Mumbai",
        )
    )
    alert = AuctionAlert(user_id=test_user.id, city="Mumbai", keyword="main road")
    db_session.add(alert)
    await db_session.flush()
    dispatch = AsyncMock(
        return_value={"type_key": "auction_alert_match", "channels": {"push": {"ok": False}}}
    )
    monkeypatch.setattr(notification_dispatcher, "dispatch_notification_to_user", dispatch)

    service = AlertMatcherService()
    matches = [m for m in await service._find_matches(db_session) if m["alert_id"] == alert.id]
    stats = await service._upsert(db_session, matches)

    assert stats["failed"] == 1
    await db_session.refresh(alert)
    assert alert.last_notified_at is None


@pytest.mark.asyncio
async def test_more_matches_than_one_run_reads_are_all_sent_over_two_runs(
    db_session, test_user, monkeypatch
):
    """Twelve auctions share one created_at; a run reads ten, the next run the rest."""
    from app.services import notification_dispatcher

    db_session.add_all(
        [
            BankAuction(
                source=AuctionSource.sarfaesi,
                bank_name="SBI",
                property_description=f"Batch shop {index}",
                city="Mumbai",
            )
            for index in range(12)
        ]
    )
    alert = AuctionAlert(user_id=test_user.id, city="Mumbai", keyword="Batch shop")
    db_session.add(alert)
    await db_session.flush()
    dispatch = AsyncMock(
        return_value={"type_key": "auction_alert_match", "channels": {"in_app": {"ok": True}}}
    )
    monkeypatch.setattr(notification_dispatcher, "dispatch_notification_to_user", dispatch)

    service = AlertMatcherService()
    sent: set[int] = set()
    for _run in range(3):
        matches = [m for m in await service._find_matches(db_session) if m["alert_id"] == alert.id]
        await service._upsert(db_session, matches)
        sent.update(m["auction_id"] for m in matches)

    assert len(sent) == 12
    assert dispatch.await_count == 12
