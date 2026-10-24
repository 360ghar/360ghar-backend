"""Watchlist alert tests: pure change detection, the disabled gate, and dispatch."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest

from app.models.data_hub import (
    DataHubEntityRevision,
    ProjectPriceHistory,
    ProjectWatchlist,
    ReraProject,
    ReraProjectDocument,
)
from app.models.enums import ProjectPriceSource
from app.services.data_hub import watchlist_alerts as alerts
from app.services.data_hub.watchlist_alerts import (
    CHANGE_TYPE_KEYS,
    WatchlistAlertScraper,
    alert_pref_enabled,
    detect_change_kinds,
    filing_is_new,
    possession_changed,
    price_changed,
    stage_changed,
)

BASELINE = datetime(2026, 6, 1, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


class TestPureChangeHelpers:
    def test_price_changed_only_when_the_value_differs(self):
        assert price_changed(Decimal("5000.00"), Decimal("6000.00")) is True
        assert price_changed(Decimal("5000.00"), Decimal("5000.00")) is False
        # Numeric forms of the same value are the same value.
        assert price_changed(5000, Decimal("5000.00")) is False

    def test_a_missing_side_is_never_a_change(self):
        assert price_changed(None, Decimal("6000.00")) is False
        assert price_changed(Decimal("5000.00"), None) is False
        assert possession_changed(None, date(2032, 1, 1)) is False

    def test_stage_changed_compares_enum_and_string_forms(self):
        assert stage_changed("under_construction", "near_possession") is True
        assert stage_changed("under_construction", "under_construction") is False

    def test_possession_changed_compares_date_and_iso_string(self):
        assert possession_changed(date(2031, 12, 31), date(2032, 6, 30)) is True
        # A revision snapshot stores the date as an ISO string.
        assert possession_changed("2031-12-31", date(2031, 12, 31)) is False

    def test_filing_is_new_is_an_ordering_test(self):
        assert filing_is_new(date(2026, 6, 1), date(2026, 6, 2)) is True
        assert filing_is_new(date(2026, 6, 1), date(2026, 6, 1)) is False
        assert filing_is_new(date(2026, 6, 1), None) is False

    def test_alert_prefs_are_opt_in(self):
        assert alert_pref_enabled(None, "watchlist_price_change") is True
        assert alert_pref_enabled({}, "watchlist_price_change") is True
        assert alert_pref_enabled({"watchlist_price_change": True}, "watchlist_price_change") is True
        assert alert_pref_enabled({"watchlist_price_change": False}, "watchlist_price_change") is False


class TestDetectChangeKinds:
    def test_no_change_produces_no_dispatch(self):
        assert (
            detect_change_kinds(
                previous_price_per_sqft=Decimal("5000"),
                current_price_per_sqft=Decimal("5000"),
                previous_possession_date=date(2031, 12, 31),
                current_possession_date=date(2031, 12, 31),
                previous_filing_uploaded_on=date(2026, 6, 1),
                latest_filing_uploaded_on=date(2026, 6, 1),
            )
            == []
        )

    def test_every_change_kind_is_reported_in_order(self):
        kinds = detect_change_kinds(
            previous_price_per_sqft=Decimal("5000"),
            current_price_per_sqft=Decimal("6000"),
            previous_stage="under_construction",
            current_stage="near_possession",
            previous_possession_date=date(2031, 12, 31),
            current_possession_date=date(2032, 6, 30),
            previous_filing_uploaded_on=date(2026, 6, 1),
            latest_filing_uploaded_on=date(2026, 6, 2),
        )
        assert kinds == ["price", "stage", "possession", "filing"]

    def test_an_opt_out_suppresses_only_that_kind(self):
        kinds = detect_change_kinds(
            previous_price_per_sqft=Decimal("5000"),
            current_price_per_sqft=Decimal("6000"),
            previous_filing_uploaded_on=date(2026, 6, 1),
            latest_filing_uploaded_on=date(2026, 6, 2),
            alert_prefs={"watchlist_price_change": False},
        )
        assert kinds == ["filing"]

    def test_change_type_keys_cover_every_kind(self):
        assert set(CHANGE_TYPE_KEYS) == {"price", "stage", "possession", "filing"}


# ---------------------------------------------------------------------------
# Database-backed scraper
# ---------------------------------------------------------------------------


async def _project(db_session, *, rera_number: str) -> ReraProject:
    project = ReraProject(
        rera_number=rera_number,
        project_name=f"Project {rera_number}",
        slug=rera_number.lower(),
        possession_date=date(2031, 12, 31),
    )
    db_session.add(project)
    await db_session.flush()
    return project


async def _watch(
    db_session,
    *,
    user_id: int,
    project_id: int,
    updated_at: datetime = BASELINE,
    alert_prefs: dict | None = None,
) -> ProjectWatchlist:
    watch = ProjectWatchlist(
        user_id=user_id,
        rera_project_id=project_id,
        created_at=updated_at,
        updated_at=updated_at,
        alert_prefs=alert_prefs,
    )
    db_session.add(watch)
    await db_session.flush()
    return watch


async def _price_point(
    db_session,
    *,
    project_id: int,
    quarter: str,
    price: str,
    recorded_at: datetime,
) -> None:
    db_session.add(
        ProjectPriceHistory(
            rera_project_id=project_id,
            quarter=quarter,
            unit_type="all",
            price_per_sqft=Decimal(price),
            source=ProjectPriceSource.filing,
            recorded_at=recorded_at,
        )
    )
    await db_session.flush()


async def _revision(
    db_session,
    *,
    project_id: int,
    revision_number: int,
    possession_date: str,
    created_at: datetime,
) -> None:
    db_session.add(
        DataHubEntityRevision(
            rera_project_id=project_id,
            revision_number=revision_number,
            normalized_snapshot={"possession_date": possession_date},
            snapshot_sha256="0" * 64,
            changed_fields=["possession_date"],
            created_at=created_at,
        )
    )
    await db_session.flush()


async def _document(db_session, *, project_id: int, ordinal: int, uploaded_on: date) -> None:
    db_session.add(
        ReraProjectDocument(
            rera_project_id=project_id,
            ordinal=ordinal,
            description="Filing document",
            uploaded_on=uploaded_on,
        )
    )
    await db_session.flush()


@pytest.mark.asyncio
async def test_a_run_with_no_change_sends_nothing(db_session, test_user):
    project = await _project(db_session, rera_number="RERA-NA-1")
    await _price_point(
        db_session,
        project_id=project.id,
        quarter="2026-Q1",
        price="5000.00",
        recorded_at=BASELINE - timedelta(days=30),
    )
    await _revision(
        db_session,
        project_id=project.id,
        revision_number=1,
        possession_date="2031-12-31",
        created_at=BASELINE - timedelta(days=30),
    )
    await _document(
        db_session, project_id=project.id, ordinal=1, uploaded_on=BASELINE.date() - timedelta(days=30)
    )
    await _watch(db_session, user_id=test_user.id, project_id=project.id)

    scraper = WatchlistAlertScraper()

    assert await scraper._collect_changes(db_session) == []
    assert await scraper._upsert(db_session, []) == {"found": 0, "upserted": 0, "failed": 0}


@pytest.mark.asyncio
async def test_a_price_move_since_the_baseline_is_detected(db_session, test_user):
    project = await _project(db_session, rera_number="RERA-PC-1")
    await _price_point(
        db_session,
        project_id=project.id,
        quarter="2026-Q1",
        price="5000.00",
        recorded_at=BASELINE - timedelta(days=30),
    )
    await _price_point(
        db_session,
        project_id=project.id,
        quarter="2026-Q3",
        price="6000.00",
        recorded_at=BASELINE + timedelta(days=30),
    )
    await _revision(
        db_session,
        project_id=project.id,
        revision_number=1,
        possession_date="2031-12-31",
        created_at=BASELINE - timedelta(days=30),
    )
    await _watch(db_session, user_id=test_user.id, project_id=project.id)

    records = await WatchlistAlertScraper()._collect_changes(db_session)

    assert [record["kind"] for record in records] == ["price"]
    assert records[0]["type_key"] == "watchlist_price_change"
    assert records[0]["user_id"] == test_user.id


@pytest.mark.asyncio
async def test_a_possession_move_since_the_baseline_is_detected(db_session, test_user):
    project = await _project(db_session, rera_number="RERA-PS-1")
    project.possession_date = date(2032, 6, 30)
    await _price_point(
        db_session,
        project_id=project.id,
        quarter="2026-Q1",
        price="5000.00",
        recorded_at=BASELINE - timedelta(days=30),
    )
    await _revision(
        db_session,
        project_id=project.id,
        revision_number=1,
        possession_date="2031-12-31",
        created_at=BASELINE - timedelta(days=30),
    )
    await _watch(db_session, user_id=test_user.id, project_id=project.id)

    records = await WatchlistAlertScraper()._collect_changes(db_session)

    assert [record["kind"] for record in records] == ["possession"]
    assert records[0]["type_key"] == "watchlist_possession_change"


@pytest.mark.asyncio
async def test_a_document_uploaded_after_the_baseline_is_detected(db_session, test_user):
    project = await _project(db_session, rera_number="RERA-FI-1")
    await _revision(
        db_session,
        project_id=project.id,
        revision_number=1,
        possession_date="2031-12-31",
        created_at=BASELINE - timedelta(days=30),
    )
    await _document(
        db_session, project_id=project.id, ordinal=1, uploaded_on=BASELINE.date() + timedelta(days=1)
    )
    await _watch(db_session, user_id=test_user.id, project_id=project.id)

    records = await WatchlistAlertScraper()._collect_changes(db_session)

    assert [record["kind"] for record in records] == ["filing"]
    assert records[0]["type_key"] == "watchlist_new_filing"


@pytest.mark.asyncio
async def test_an_opt_out_in_alert_prefs_suppresses_that_kind(db_session, test_user):
    project = await _project(db_session, rera_number="RERA-OP-1")
    await _price_point(
        db_session,
        project_id=project.id,
        quarter="2026-Q1",
        price="5000.00",
        recorded_at=BASELINE - timedelta(days=30),
    )
    await _price_point(
        db_session,
        project_id=project.id,
        quarter="2026-Q3",
        price="6000.00",
        recorded_at=BASELINE + timedelta(days=30),
    )
    await _watch(
        db_session,
        user_id=test_user.id,
        project_id=project.id,
        alert_prefs={"watchlist_price_change": False},
    )

    assert await WatchlistAlertScraper()._collect_changes(db_session) == []


@pytest.mark.asyncio
async def test_upsert_dispatches_and_advances_the_watch_baseline(
    db_session, test_user, monkeypatch
):
    project = await _project(db_session, rera_number="RERA-UP-1")
    watch = await _watch(db_session, user_id=test_user.id, project_id=project.id)
    dispatch = AsyncMock(return_value={"type_key": "watchlist_price_change", "channels": {}})
    monkeypatch.setattr(alerts, "dispatch_notification_to_user", dispatch)

    scraper = WatchlistAlertScraper()
    record = scraper._build_record(watch, project, "price")
    stats = await scraper._upsert(db_session, [record])

    assert stats == {"found": 1, "upserted": 1, "failed": 0}
    dispatch.assert_awaited_once()
    assert dispatch.await_args.kwargs["type_key"] == "watchlist_price_change"
    refreshed = await db_session.get(ProjectWatchlist, watch.id)
    assert refreshed.updated_at > BASELINE


@pytest.mark.asyncio
async def test_a_failed_dispatch_does_not_abort_the_batch_and_holds_the_baseline(
    db_session, test_user, monkeypatch
):
    first = await _project(db_session, rera_number="RERA-FA-1")
    second = await _project(db_session, rera_number="RERA-FA-2")
    watch_one = await _watch(db_session, user_id=test_user.id, project_id=first.id)
    watch_two = await _watch(db_session, user_id=test_user.id, project_id=second.id)
    dispatch = AsyncMock(
        side_effect=[{"type_key": "watchlist_price_change", "error": "unknown_type_key"}, {"channels": {}}]
    )
    monkeypatch.setattr(alerts, "dispatch_notification_to_user", dispatch)

    scraper = WatchlistAlertScraper()
    records = [
        scraper._build_record(watch_one, first, "price"),
        scraper._build_record(watch_two, second, "price"),
    ]
    stats = await scraper._upsert(db_session, records)

    assert stats == {"found": 2, "upserted": 1, "failed": 1}
    # The failed watch keeps its baseline so the alert is retried next run.
    failed = await db_session.get(ProjectWatchlist, watch_one.id)
    assert failed.updated_at == BASELINE
    delivered = await db_session.get(ProjectWatchlist, watch_two.id)
    assert delivered.updated_at > BASELINE


@pytest.mark.asyncio
async def test_run_is_gated_on_hrera_data_enabled(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "HRERA_DATA_ENABLED", False)

    result = await WatchlistAlertScraper().run()

    assert result == {
        "status": "disabled",
        "run_id": None,
        "reason": "hrera_disabled_by_configuration",
    }
    assert {key: result[key] for key in ("status", "reason")} == {
        "status": "disabled",
        "reason": "hrera_disabled_by_configuration",
    }
