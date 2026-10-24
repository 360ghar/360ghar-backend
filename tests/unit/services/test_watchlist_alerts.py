"""Watchlist alert tests: pure change detection, the disabled gate, and dispatch."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest

from app.models.data_hub import (
    ProjectPriceHistory,
    ProjectWatchlist,
    ReraProject,
    ReraProjectDocument,
    ReraProjectProfile,
)
from app.models.enums import ProjectPriceSource, ProjectStage
from app.services.data_hub import watchlist_alerts as alerts
from app.services.data_hub.watchlist_alerts import (
    CHANGE_TYPE_KEYS,
    WatchlistAlertScraper,
    alert_pref_enabled,
    current_alert_snapshot,
    detect_change_kinds,
    document_key,
    filing_is_new,
    merge_baseline,
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
    alert_baseline: dict | None = None,
    alert_prefs: dict | None = None,
) -> ProjectWatchlist:
    watch = ProjectWatchlist(
        user_id=user_id,
        rera_project_id=project_id,
        created_at=BASELINE,
        updated_at=BASELINE,
        alert_prefs=alert_prefs,
        alert_baseline=alert_baseline,
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
) -> ProjectPriceHistory:
    point = ProjectPriceHistory(
        rera_project_id=project_id,
        quarter=quarter,
        unit_type="all",
        price_per_sqft=Decimal(price),
        source=ProjectPriceSource.filing,
        recorded_at=recorded_at,
    )
    db_session.add(point)
    await db_session.flush()
    return point


async def _document(
    db_session, *, project_id: int, ordinal: int, uploaded_on: date, description: str = "Filing document"
) -> None:
    db_session.add(
        ReraProjectDocument(
            rera_project_id=project_id,
            ordinal=ordinal,
            description=description,
            uploaded_on=uploaded_on,
        )
    )
    await db_session.flush()


def _baseline(**overrides) -> dict:
    """A stored baseline that matches a fresh ``_project`` with no price or documents."""
    return {
        "price_per_sqft": None,
        "stage": None,
        "possession_date": "2031-12-31",
        "documents": [],
        **overrides,
    }


def _kinds(records: list[dict]) -> list[str]:
    return [record["kind"] for record in records if record["kind"] != alerts.BASELINE_KIND]


@pytest.mark.asyncio
async def test_a_run_with_no_change_sends_nothing(db_session, test_user):
    project = await _project(db_session, rera_number="RERA-NA-1")
    await _price_point(
        db_session, project_id=project.id, quarter="2026-Q1", price="5000.00", recorded_at=BASELINE
    )
    await _document(db_session, project_id=project.id, ordinal=1, uploaded_on=date(2026, 5, 1))
    snapshot = await current_alert_snapshot(db_session, project)
    await _watch(db_session, user_id=test_user.id, project_id=project.id, alert_baseline=snapshot)

    records = await WatchlistAlertScraper()._collect_changes(db_session)

    assert _kinds(records) == []


@pytest.mark.asyncio
async def test_a_watch_without_a_baseline_gets_one_and_sends_nothing(
    db_session, test_user, monkeypatch
):
    project = await _project(db_session, rera_number="RERA-NB-1")
    await _price_point(
        db_session, project_id=project.id, quarter="2026-Q1", price="5000.00", recorded_at=BASELINE
    )
    watch = await _watch(db_session, user_id=test_user.id, project_id=project.id)
    dispatch = AsyncMock()
    monkeypatch.setattr(alerts, "dispatch_notification_to_user", dispatch)

    scraper = WatchlistAlertScraper()
    records = await scraper._collect_changes(db_session)
    stats = await scraper._upsert(db_session, records)

    assert stats == {"found": 0, "upserted": 0, "failed": 0}
    dispatch.assert_not_awaited()
    refreshed = await db_session.get(ProjectWatchlist, watch.id)
    assert refreshed.alert_baseline["price_per_sqft"] == "5000.00"


@pytest.mark.asyncio
async def test_a_same_quarter_price_overwrite_is_detected(db_session, test_user):
    """The quarter's point is overwritten in place; the stored value still differs."""
    project = await _project(db_session, rera_number="RERA-PC-1")
    point = await _price_point(
        db_session, project_id=project.id, quarter="2026-Q3", price="5000.00", recorded_at=BASELINE
    )
    await _watch(
        db_session,
        user_id=test_user.id,
        project_id=project.id,
        alert_baseline=_baseline(price_per_sqft="5000.00"),
    )
    point.price_per_sqft = Decimal("6000.00")
    point.recorded_at = BASELINE + timedelta(days=30)
    await db_session.flush()

    records = await WatchlistAlertScraper()._collect_changes(db_session)

    assert _kinds(records) == ["price"]
    price = next(record for record in records if record["kind"] == "price")
    assert price["type_key"] == "watchlist_price_change"
    assert price["user_id"] == test_user.id


@pytest.mark.asyncio
async def test_editing_a_watch_does_not_hide_a_change(db_session, test_user):
    """A notes edit moves updated_at, but the baseline is a separate column."""
    project = await _project(db_session, rera_number="RERA-ED-1")
    await _price_point(
        db_session, project_id=project.id, quarter="2026-Q1", price="6000.00", recorded_at=BASELINE
    )
    watch = await _watch(
        db_session,
        user_id=test_user.id,
        project_id=project.id,
        alert_baseline=_baseline(price_per_sqft="5000.00"),
    )
    watch.notes = "call the builder"
    watch.updated_at = BASELINE + timedelta(days=60)
    await db_session.flush()

    assert _kinds(await WatchlistAlertScraper()._collect_changes(db_session)) == ["price"]


@pytest.mark.asyncio
async def test_a_possession_move_is_detected(db_session, test_user):
    project = await _project(db_session, rera_number="RERA-PS-1")
    project.possession_date = date(2032, 6, 30)
    await db_session.flush()
    await _watch(db_session, user_id=test_user.id, project_id=project.id, alert_baseline=_baseline())

    records = await WatchlistAlertScraper()._collect_changes(db_session)

    assert _kinds(records) == ["possession"]


@pytest.mark.asyncio
async def test_a_stage_change_is_detected(db_session, test_user):
    project = await _project(db_session, rera_number="RERA-ST-1")
    db_session.add(
        ReraProjectProfile(rera_project_id=project.id, stage=ProjectStage("under_construction"))
    )
    await db_session.flush()
    await _watch(
        db_session,
        user_id=test_user.id,
        project_id=project.id,
        alert_baseline=_baseline(stage="pre_launch"),
    )

    records = await WatchlistAlertScraper()._collect_changes(db_session)

    assert _kinds(records) == ["stage"]


@pytest.mark.asyncio
async def test_a_second_document_on_the_same_day_is_detected(db_session, test_user):
    project = await _project(db_session, rera_number="RERA-FI-1")
    day = date(2026, 6, 1)
    await _document(db_session, project_id=project.id, ordinal=1, uploaded_on=day, description="Form B")
    await _document(db_session, project_id=project.id, ordinal=2, uploaded_on=day, description="Form C")
    await _watch(
        db_session,
        user_id=test_user.id,
        project_id=project.id,
        alert_baseline=_baseline(documents=[document_key(day, "Form B")]),
    )

    records = await WatchlistAlertScraper()._collect_changes(db_session)

    assert _kinds(records) == ["filing"]


@pytest.mark.asyncio
async def test_an_opt_out_in_alert_prefs_suppresses_that_kind(db_session, test_user):
    project = await _project(db_session, rera_number="RERA-OP-1")
    await _price_point(
        db_session, project_id=project.id, quarter="2026-Q1", price="6000.00", recorded_at=BASELINE
    )
    await _watch(
        db_session,
        user_id=test_user.id,
        project_id=project.id,
        alert_baseline=_baseline(price_per_sqft="5000.00"),
        alert_prefs={"watchlist_price_change": False},
    )

    assert _kinds(await WatchlistAlertScraper()._collect_changes(db_session)) == []


@pytest.mark.asyncio
async def test_upsert_dispatches_and_moves_the_baseline(db_session, test_user, monkeypatch):
    project = await _project(db_session, rera_number="RERA-UP-1")
    await _price_point(
        db_session, project_id=project.id, quarter="2026-Q1", price="6000.00", recorded_at=BASELINE
    )
    watch = await _watch(
        db_session,
        user_id=test_user.id,
        project_id=project.id,
        alert_baseline=_baseline(price_per_sqft="5000.00"),
    )
    dispatch = AsyncMock(
        return_value={"type_key": "watchlist_price_change", "channels": {"in_app": {"ok": True}}}
    )
    monkeypatch.setattr(alerts, "dispatch_notification_to_user", dispatch)

    scraper = WatchlistAlertScraper()
    stats = await scraper._upsert(db_session, await scraper._collect_changes(db_session))

    assert stats == {"found": 1, "upserted": 1, "failed": 0}
    assert dispatch.await_args.kwargs["type_key"] == "watchlist_price_change"
    refreshed = await db_session.get(ProjectWatchlist, watch.id)
    assert refreshed.alert_baseline["price_per_sqft"] == "6000.00"
    # The next run finds nothing new.
    assert _kinds(await scraper._collect_changes(db_session)) == []


@pytest.mark.asyncio
async def test_a_failed_kind_keeps_its_baseline_and_the_others_move(
    db_session, test_user, monkeypatch
):
    """Price fails, possession sends: only price is retried on the next run."""
    project = await _project(db_session, rera_number="RERA-FA-1")
    project.possession_date = date(2032, 6, 30)
    await _price_point(
        db_session, project_id=project.id, quarter="2026-Q1", price="6000.00", recorded_at=BASELINE
    )
    watch = await _watch(
        db_session,
        user_id=test_user.id,
        project_id=project.id,
        alert_baseline=_baseline(price_per_sqft="5000.00"),
    )

    async def dispatch(_db, **kwargs):
        if kwargs["type_key"] == "watchlist_price_change":
            # Every channel tried failed: not delivered.
            return {"type_key": kwargs["type_key"], "channels": {"push": {"ok": False}}}
        return {"type_key": kwargs["type_key"], "channels": {"in_app": {"ok": True}}}

    monkeypatch.setattr(alerts, "dispatch_notification_to_user", dispatch)

    scraper = WatchlistAlertScraper()
    stats = await scraper._upsert(db_session, await scraper._collect_changes(db_session))

    assert stats == {"found": 2, "upserted": 1, "failed": 1}
    refreshed = await db_session.get(ProjectWatchlist, watch.id)
    assert refreshed.alert_baseline["price_per_sqft"] == "5000.00"
    assert refreshed.alert_baseline["possession_date"] == "2032-06-30"
    assert _kinds(await scraper._collect_changes(db_session)) == ["price"]


def test_merge_baseline_keeps_only_the_failed_fields():
    previous = _baseline(price_per_sqft="5000.00")
    snapshot = _baseline(price_per_sqft="6000.00", possession_date="2032-06-30")

    merged = merge_baseline(previous, snapshot, {"price"})

    assert merged["price_per_sqft"] == "5000.00"
    assert merged["possession_date"] == "2032-06-30"


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


def test_a_missing_reading_keeps_the_last_known_value():
    """A None reading is not a new value; replacing it would hide the next change."""
    previous = _baseline(price_per_sqft="5000.00", documents=["2026-06-01|Form B"])
    snapshot = _baseline(price_per_sqft=None, documents=[])

    merged = merge_baseline(previous, snapshot, set())

    assert merged["price_per_sqft"] == "5000.00"
    assert merged["documents"] == ["2026-06-01|Form B"]
