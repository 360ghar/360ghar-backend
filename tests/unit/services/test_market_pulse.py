"""Market pulse aggregates: means, the 90-day move, and the sentiment fallback."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

from sqlalchemy import select

from app.config import settings
from app.models.data_hub import (
    MarketPulseSnapshot,
    ProjectPriceHistory,
    ReraComplaint,
    ReraProject,
)
from app.models.enums import MarketSentiment, ProjectPriceSource
from app.services.data_hub.market_pulse import (
    MarketPulseScraper,
    classify_sentiment,
    compute_pulse,
    mean_price,
    percent_change,
)
from app.services.data_hub.rera_price_history import quarter_key


class TestMeanPrice:
    def test_the_mean_of_the_price_points(self):
        assert mean_price([Decimal("5000"), Decimal("7000")]) == Decimal("6000.00")

    def test_the_mean_is_rounded_to_two_places(self):
        assert mean_price([Decimal("1000"), Decimal("1001"), Decimal("1000")]) == Decimal(
            "1000.33"
        )

    def test_no_price_points_is_none_not_zero(self):
        assert mean_price([]) is None


class TestPercentChange:
    def test_a_rise_is_a_positive_percentage(self):
        assert percent_change(Decimal("110"), Decimal("100")) == Decimal("10.00")

    def test_a_fall_is_a_negative_percentage(self):
        assert percent_change(Decimal("90"), Decimal("100")) == Decimal("-10.00")

    def test_no_movement_is_zero(self):
        assert percent_change(Decimal("100"), Decimal("100")) == Decimal("0.00")

    def test_a_missing_side_is_none(self):
        assert percent_change(None, Decimal("100")) is None
        assert percent_change(Decimal("100"), None) is None
        assert percent_change(None, None) is None

    def test_a_zero_base_is_none_rather_than_infinite(self):
        assert percent_change(Decimal("100"), Decimal("0")) is None


class TestSentiment:
    def test_a_move_above_the_threshold_is_positive(self):
        assert classify_sentiment(Decimal("1.01"), 0) is MarketSentiment.positive

    def test_a_move_below_the_threshold_is_negative(self):
        assert classify_sentiment(Decimal("-1.01"), 0) is MarketSentiment.negative

    def test_a_move_inside_the_threshold_is_neutral(self):
        assert classify_sentiment(Decimal("1.00"), 0) is MarketSentiment.neutral
        assert classify_sentiment(Decimal("0.00"), 0) is MarketSentiment.neutral
        assert classify_sentiment(Decimal("-1.00"), 0) is MarketSentiment.neutral

    def test_without_prices_new_registrations_carry_the_reading(self):
        assert classify_sentiment(None, 3) is MarketSentiment.positive

    def test_without_prices_a_quiet_week_is_neutral_never_negative(self):
        assert classify_sentiment(None, 0) is MarketSentiment.neutral

    def test_no_price_and_no_registration_count_is_unknown_not_neutral(self):
        """The Delhi register states no registration date, so there is no signal.

        ``neutral`` is published as "Steady", which a reader takes as a measured
        flat market. Reading that off an absent field would be a claim this code
        cannot support, so the reading is ``unknown`` instead.
        """
        assert classify_sentiment(None, None) is MarketSentiment.unknown

    def test_a_measured_flat_price_move_outranks_a_missing_count(self):
        """A real price move is a signal even when the filing count is unknown."""
        assert classify_sentiment(Decimal("0.00"), None) is MarketSentiment.neutral
        assert classify_sentiment(Decimal("5.00"), None) is MarketSentiment.positive
        assert classify_sentiment(Decimal("-5.00"), None) is MarketSentiment.negative


class TestComputePulse:
    def test_a_full_reading_from_plain_values(self):
        captured_on = date(2026, 10, 1)
        computed_at = datetime(2026, 10, 1, 4, 30, tzinfo=UTC)

        pulse = compute_pulse(
            city="Gurugram",
            captured_on=captured_on,
            latest_prices=[Decimal("6000")],
            prices_90d_ago=[Decimal("5000")],
            new_registrations=2,
            new_complaints=1,
            computed_at=computed_at,
        )

        assert pulse == {
            "city": "Gurugram",
            "captured_on": date(2026, 10, 1),
            "sentiment": MarketSentiment.positive,
            "avg_price_per_sqft": Decimal("6000.00"),
            "price_change_90d_pct": Decimal("20.00"),
            "new_registrations": 2,
            "new_complaints": 1,
            "computed_at": computed_at,
        }

    def test_no_prices_leaves_the_price_fields_empty_and_falls_back(self):
        pulse = compute_pulse(
            city="Faridabad",
            captured_on=date(2026, 10, 1),
            latest_prices=[],
            prices_90d_ago=[],
            new_registrations=0,
            new_complaints=0,
            computed_at=datetime(2026, 10, 1, 4, 30, tzinfo=UTC),
        )

        assert pulse["avg_price_per_sqft"] is None
        assert pulse["price_change_90d_pct"] is None
        assert pulse["sentiment"] is MarketSentiment.neutral

    def test_counts_that_were_never_taken_stay_empty_on_the_reading(self):
        """``None`` is not ``0``: an unmeasured count is reported as unmeasured.

        Every Delhi project has a NULL ``registration_date`` and ``rera_complaints``
        is empty, so both counts are unknown for those cities. Storing ``0`` would
        publish "0 new registrations" for a city that may have filed that morning.
        """
        pulse = compute_pulse(
            city="new delhi",
            captured_on=date(2026, 10, 1),
            latest_prices=[],
            prices_90d_ago=[],
            new_registrations=None,
            new_complaints=None,
            computed_at=datetime(2026, 10, 1, 4, 30, tzinfo=UTC),
        )

        assert pulse["new_registrations"] is None
        assert pulse["new_complaints"] is None
        assert pulse["sentiment"] is MarketSentiment.unknown

    def test_a_counted_zero_is_kept_as_zero(self):
        """A quiet window the register could actually be counted over is a real 0."""
        pulse = compute_pulse(
            city="gurugram",
            captured_on=date(2026, 10, 1),
            latest_prices=[],
            prices_90d_ago=[],
            new_registrations=0,
            new_complaints=0,
            computed_at=datetime(2026, 10, 1, 4, 30, tzinfo=UTC),
        )

        assert pulse["new_registrations"] == 0
        assert pulse["new_complaints"] == 0
        assert pulse["sentiment"] is MarketSentiment.neutral

    def test_no_earlier_price_point_leaves_the_change_empty(self):
        pulse = compute_pulse(
            city="Gurugram",
            captured_on=date(2026, 10, 1),
            latest_prices=[Decimal("6000")],
            prices_90d_ago=[],
            new_registrations=1,
            new_complaints=0,
            computed_at=datetime(2026, 10, 1, 4, 30, tzinfo=UTC),
        )

        assert pulse["avg_price_per_sqft"] == Decimal("6000.00")
        assert pulse["price_change_90d_pct"] is None
        assert pulse["sentiment"] is MarketSentiment.positive

    def test_a_falling_market_reads_negative(self):
        pulse = compute_pulse(
            city="Gurugram",
            captured_on=date(2026, 10, 1),
            latest_prices=[Decimal("4500")],
            prices_90d_ago=[Decimal("5000")],
            new_registrations=5,
            new_complaints=0,
            computed_at=datetime(2026, 10, 1, 4, 30, tzinfo=UTC),
        )

        assert pulse["price_change_90d_pct"] == Decimal("-10.00")
        assert pulse["sentiment"] is MarketSentiment.negative


class TestAggregateReadsTheRegister:
    async def test_one_reading_per_city_with_the_register_behind_it(self, db_session):
        today = datetime.now(UTC).date()
        gurugram_one = ReraProject(
            rera_number="TEST-PULSE-1",
            project_name="Pulse One",
            district="Gurugram",
            registration_date=today - timedelta(days=3),
        )
        gurugram_two = ReraProject(
            rera_number="TEST-PULSE-2",
            project_name="Pulse Two",
            district="Gurugram",
            registration_date=today - timedelta(days=30),
        )
        faridabad = ReraProject(
            rera_number="TEST-PULSE-3",
            project_name="Pulse Three",
            district="Faridabad",
            registration_date=today - timedelta(days=40),
        )
        db_session.add_all([gurugram_one, gurugram_two, faridabad])
        await db_session.flush()
        db_session.add_all(
            [
                ReraComplaint(
                    order_number="TEST-PULSE-COMPLAINT-1",
                    respondent_builder="Pulse Builders",
                    order_date=today - timedelta(days=2),
                    rera_number=gurugram_one.rera_number,
                ),
                ProjectPriceHistory(
                    rera_project_id=gurugram_one.id,
                    quarter=quarter_key(today - timedelta(days=10)),
                    period_start=today - timedelta(days=10),
                    unit_type="all",
                    price_per_sqft=Decimal("6000"),
                    source=ProjectPriceSource.filing,
                    recorded_at=datetime.now(UTC),
                ),
                # Same quarter as the filing point: the filed price must win.
                ProjectPriceHistory(
                    rera_project_id=gurugram_one.id,
                    quarter=quarter_key(today - timedelta(days=10)),
                    period_start=today - timedelta(days=10),
                    unit_type="all",
                    price_per_sqft=Decimal("1000"),
                    source=ProjectPriceSource.launch,
                    recorded_at=datetime.now(UTC),
                ),
                ProjectPriceHistory(
                    rera_project_id=gurugram_one.id,
                    quarter=quarter_key(today - timedelta(days=100)),
                    period_start=today - timedelta(days=100),
                    unit_type="all",
                    price_per_sqft=Decimal("5000"),
                    source=ProjectPriceSource.filing,
                    recorded_at=datetime.now(UTC),
                ),
            ]
        )
        await db_session.flush()

        records = await MarketPulseScraper()._aggregate(db_session, today)
        by_city = {record["city"]: record for record in records}

        assert by_city["gurugram"]["captured_on"] == today
        assert by_city["gurugram"]["new_registrations"] == 1
        assert by_city["gurugram"]["new_complaints"] == 1
        assert by_city["gurugram"]["avg_price_per_sqft"] == Decimal("6000.00")
        assert by_city["gurugram"]["price_change_90d_pct"] == Decimal("20.00")
        assert by_city["gurugram"]["sentiment"] is MarketSentiment.positive
        assert by_city["gurugram"]["computed_at"] is not None

        assert by_city["faridabad"]["new_registrations"] == 0
        assert by_city["faridabad"]["new_complaints"] == 0
        assert by_city["faridabad"]["avg_price_per_sqft"] is None
        assert by_city["faridabad"]["price_change_90d_pct"] is None
        assert by_city["faridabad"]["sentiment"] is MarketSentiment.neutral

    async def test_a_city_with_no_registration_dates_reports_unknown(self, db_session):
        """The Delhi case: 133 projects, every ``registration_date`` NULL.

        Counting only the dated rows returns ``0`` for such a city, which the page
        renders as "0 new registrations" and reads as "none filed". The register
        states no date at all, so the honest reading is that no count was taken.
        """
        today = datetime.now(UTC).date()
        db_session.add(
            ReraProject(
                rera_number="TEST-PULSE-UNDATED-1",
                project_name="Undated One",
                district="New Delhi",
                registration_date=None,
            )
        )
        await db_session.flush()

        records = await MarketPulseScraper()._aggregate(db_session, today)
        by_city = {record["city"]: record for record in records}

        assert by_city["new delhi"]["new_registrations"] is None
        assert by_city["new delhi"]["new_complaints"] is None
        assert by_city["new delhi"]["sentiment"] is MarketSentiment.unknown

    async def test_one_dated_project_makes_the_city_countable_again(self, db_session):
        """The rule is per city, so a dated filing restores that city's real count.

        Adding a registration date to a single project must start publishing the
        count for its district without touching any other district.
        """
        today = datetime.now(UTC).date()
        db_session.add_all(
            [
                ReraProject(
                    rera_number="TEST-PULSE-UNDATED-2",
                    project_name="Undated Two",
                    district="New Delhi",
                    registration_date=None,
                ),
                ReraProject(
                    rera_number="TEST-PULSE-DATED-2",
                    project_name="Dated Two",
                    district="South Delhi",
                    registration_date=today - timedelta(days=2),
                ),
            ]
        )
        await db_session.flush()

        records = await MarketPulseScraper()._aggregate(db_session, today)
        by_city = {record["city"]: record for record in records}

        # South Delhi can be counted and filed nothing outside its one project.
        assert by_city["south delhi"]["new_registrations"] == 1
        assert by_city["south delhi"]["sentiment"] is MarketSentiment.positive
        # New Delhi still cannot be counted, and is not reported as a quiet zero.
        assert by_city["new delhi"]["new_registrations"] is None
        assert by_city["new delhi"]["sentiment"] is MarketSentiment.unknown

    async def test_two_spellings_of_one_district_are_one_reading(self, db_session):
        """One place, one pulse: the register's spelling is not the city's identity.

        Both unique constraint on ``(city, captured_on)`` and the aggregation key
        on the city, so two spellings of one district used to write two snapshots
        for one place, each holding part of its numbers.
        """
        today = datetime.now(UTC).date()
        db_session.add_all(
            [
                ReraProject(
                    rera_number="TEST-PULSE-CASE-1",
                    project_name="Pulse Case One",
                    district="Gurugram",
                    registration_date=today - timedelta(days=1),
                ),
                ReraProject(
                    rera_number="TEST-PULSE-CASE-2",
                    project_name="Pulse Case Two",
                    district="gurugram",
                    registration_date=today - timedelta(days=1),
                ),
            ]
        )
        await db_session.flush()

        records = await MarketPulseScraper()._aggregate(db_session, today)

        assert [record["city"] for record in records] == ["gurugram"]
        assert records[0]["new_registrations"] == 2

    async def test_a_complaint_on_another_city_project_is_not_counted(self, db_session):
        today = datetime.now(UTC).date()
        other = ReraProject(
            rera_number="TEST-PULSE-4",
            project_name="Pulse Four",
            district="Karnal",
            registration_date=today - timedelta(days=1),
        )
        db_session.add(other)
        await db_session.flush()
        db_session.add(
            ReraComplaint(
                order_number="TEST-PULSE-COMPLAINT-2",
                respondent_builder="Pulse Builders",
                order_date=today - timedelta(days=1),
                rera_number=other.rera_number,
            )
        )
        await db_session.flush()

        records = await MarketPulseScraper()._aggregate(db_session, today)
        by_city = {record["city"]: record for record in records}

        assert by_city["karnal"]["new_registrations"] == 1
        assert by_city["karnal"]["new_complaints"] == 1

    async def test_a_snapshot_upserts_on_city_and_day(self, db_session):
        today = datetime.now(UTC).date()
        scraper = MarketPulseScraper()
        first = compute_pulse(
            city="Rewari",
            captured_on=today,
            latest_prices=[Decimal("4000")],
            prices_90d_ago=[],
            new_registrations=1,
            new_complaints=0,
            computed_at=datetime.now(UTC),
        )

        assert await scraper._upsert(db_session, [first]) == {
            "found": 1,
            "upserted": 1,
            "failed": 0,
        }
        second = compute_pulse(
            city="Rewari",
            captured_on=today,
            latest_prices=[Decimal("4400")],
            prices_90d_ago=[],
            new_registrations=2,
            new_complaints=1,
            computed_at=datetime.now(UTC),
        )
        assert await scraper._upsert(db_session, [second]) == {
            "found": 1,
            "upserted": 1,
            "failed": 0,
        }

        rows = (
            (
                await db_session.execute(
                    select(MarketPulseSnapshot).where(MarketPulseSnapshot.city == "Rewari")
                )
            )
            .scalars()
            .all()
        )
        assert len(rows) == 1
        assert rows[0].captured_on == today
        assert rows[0].avg_price_per_sqft == Decimal("4400.00")
        assert rows[0].new_registrations == 2
        assert rows[0].new_complaints == 1


class TestRightsGate:
    async def test_run_is_disabled_before_any_read(self, monkeypatch):
        monkeypatch.setattr(settings, "HRERA_DATA_ENABLED", False, raising=False)
        monkeypatch.setattr(
            "app.services.data_hub.base_scraper.get_bg_session_factory",
            MagicMock(side_effect=AssertionError("no run row may be created")),
        )
        scraper = MarketPulseScraper()
        scraper._scrape = AsyncMock(side_effect=AssertionError("no register read may happen"))

        result = await scraper.run(run_type="manual")

        assert result == {
            "status": "disabled",
            "run_id": None,
            "reason": "hrera_disabled_by_configuration",
        }
        scraper._scrape.assert_not_awaited()

    async def test_scrape_and_upsert_write_nothing_when_disabled(self, monkeypatch):
        monkeypatch.setattr(settings, "HRERA_DATA_ENABLED", False, raising=False)
        scraper = MarketPulseScraper()

        assert (await scraper._scrape()).records == []
        assert await scraper._upsert(MagicMock(), [{"city": "Gurugram"}]) == {
            "found": 0,
            "upserted": 0,
            "failed": 0,
        }
