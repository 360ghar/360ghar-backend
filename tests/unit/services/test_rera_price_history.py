"""Price-history derivation: quarter labels, interpolation, and the no-guessing rule."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.config import settings
from app.models.enums import ProjectPriceSource
from app.services.data_hub.rera_price_history import (
    ReraPriceHistoryScraper,
    derive_price_points,
    quarter_from_index,
    quarter_index,
    quarter_key,
    quarter_start_date,
)


class TestQuarterLabels:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            (date(2024, 1, 1), "2024-Q1"),
            (date(2024, 3, 31), "2024-Q1"),
            (date(2024, 4, 1), "2024-Q2"),
            (date(2024, 6, 30), "2024-Q2"),
            (date(2024, 7, 15), "2024-Q3"),
            (date(2024, 12, 31), "2024-Q4"),
        ],
    )
    def test_every_boundary_month_maps_to_its_quarter(self, value, expected):
        assert quarter_key(value) == expected

    def test_a_timestamp_uses_its_own_quarter(self):
        assert quarter_key(datetime(2025, 12, 31, 23, 30, tzinfo=UTC)) == "2025-Q4"

    def test_quarter_start_is_the_first_day_of_the_quarter(self):
        assert quarter_start_date("2024-Q3") == date(2024, 7, 1)
        assert quarter_start_date("2024-Q4") == date(2024, 10, 1)
        assert quarter_start_date("2025-Q1") == date(2025, 1, 1)

    def test_index_round_trips(self):
        for quarter in ("2023-Q4", "2024-Q1", "2024-Q2", "2030-Q3"):
            assert quarter_from_index(quarter_index(quarter)) == quarter

    def test_consecutive_quarters_are_one_index_apart(self):
        assert quarter_index("2025-Q1") - quarter_index("2024-Q4") == 1
        assert quarter_index("2025-Q1") - quarter_index("2024-Q1") == 4

    def test_a_non_quarter_label_is_rejected_rather_than_guessed(self):
        with pytest.raises(ValueError):
            quarter_index("2024-Q5")
        with pytest.raises(ValueError):
            quarter_index("nonsense")


class TestDerivedPoints:
    def test_no_filed_price_means_no_point(self):
        assert (
            derive_price_points(
                rera_project_id=1,
                launch_price_per_sqft=None,
                launch_quarter=None,
                current_price_per_sqft=None,
                current_quarter=None,
            )
            == []
        )

    def test_a_price_with_no_date_to_place_it_is_not_written(self):
        # The filing carries a launch price but no date can put it in a quarter.
        assert (
            derive_price_points(
                rera_project_id=1,
                launch_price_per_sqft=Decimal("5000"),
                launch_quarter=None,
                current_price_per_sqft=None,
                current_quarter=None,
            )
            == []
        )

    def test_a_current_price_with_no_date_to_place_it_is_not_written(self):
        assert (
            derive_price_points(
                rera_project_id=1,
                launch_price_per_sqft=None,
                launch_quarter=None,
                current_price_per_sqft=Decimal("8000"),
                current_quarter=None,
            )
            == []
        )

    def test_filed_points_are_written_as_filed(self):
        points = derive_price_points(
            rera_project_id=7,
            launch_price_per_sqft=Decimal("5000"),
            launch_quarter="2024-Q1",
            current_price_per_sqft=Decimal("5000"),
            current_quarter="2024-Q1",
        )
        assert [point["source"] for point in points] == [
            ProjectPriceSource.launch,
            ProjectPriceSource.filing,
        ]
        assert all(point["rera_project_id"] == 7 for point in points)
        assert all(point["unit_type"] == "all" for point in points)
        assert points[0]["period_start"] == date(2024, 1, 1)
        assert points[1]["period_start"] == date(2024, 1, 1)
        assert points[0]["price_per_sqft"] == Decimal("5000")
        assert points[1]["price_per_sqft"] == Decimal("5000")

    def test_quarters_between_two_filed_points_are_interpolated(self):
        points = derive_price_points(
            rera_project_id=7,
            launch_price_per_sqft=Decimal("5000"),
            launch_quarter="2024-Q1",
            current_price_per_sqft=Decimal("8000"),
            current_quarter="2025-Q1",
        )
        by_quarter = {point["quarter"]: point for point in points}
        assert set(by_quarter) == {"2024-Q1", "2024-Q2", "2024-Q3", "2024-Q4", "2025-Q1"}
        assert by_quarter["2024-Q1"]["price_per_sqft"] == Decimal("5000.00")
        assert by_quarter["2024-Q2"]["price_per_sqft"] == Decimal("5750.00")
        assert by_quarter["2024-Q3"]["price_per_sqft"] == Decimal("6500.00")
        assert by_quarter["2024-Q4"]["price_per_sqft"] == Decimal("7250.00")
        assert by_quarter["2025-Q1"]["price_per_sqft"] == Decimal("8000.00")

    def test_every_computed_point_is_labelled_derived(self):
        points = derive_price_points(
            rera_project_id=7,
            launch_price_per_sqft=Decimal("5000"),
            launch_quarter="2024-Q1",
            current_price_per_sqft=Decimal("8000"),
            current_quarter="2025-Q1",
        )
        by_quarter = {point["quarter"]: point for point in points}
        assert by_quarter["2024-Q2"]["source"] is ProjectPriceSource.derived
        assert by_quarter["2024-Q3"]["source"] is ProjectPriceSource.derived
        assert by_quarter["2024-Q4"]["source"] is ProjectPriceSource.derived
        assert by_quarter["2024-Q1"]["source"] is ProjectPriceSource.launch
        assert by_quarter["2025-Q1"]["source"] is ProjectPriceSource.filing

    def test_interpolated_points_carry_their_own_period_start(self):
        points = derive_price_points(
            rera_project_id=7,
            launch_price_per_sqft=Decimal("5000"),
            launch_quarter="2024-Q1",
            current_price_per_sqft=Decimal("8000"),
            current_quarter="2025-Q1",
        )
        by_quarter = {point["quarter"]: point for point in points}
        assert by_quarter["2024-Q2"]["period_start"] == date(2024, 4, 1)
        assert by_quarter["2024-Q3"]["period_start"] == date(2024, 7, 1)
        assert by_quarter["2024-Q4"]["period_start"] == date(2024, 10, 1)

    def test_no_interpolation_when_no_whole_quarter_sits_between(self):
        points = derive_price_points(
            rera_project_id=7,
            launch_price_per_sqft=Decimal("5000"),
            launch_quarter="2024-Q1",
            current_price_per_sqft=Decimal("8000"),
            current_quarter="2024-Q2",
        )
        assert len(points) == 2
        assert {point["source"] for point in points} == {
            ProjectPriceSource.launch,
            ProjectPriceSource.filing,
        }

    def test_equal_filed_prices_produce_no_derived_rows(self):
        points = derive_price_points(
            rera_project_id=7,
            launch_price_per_sqft=Decimal("5000"),
            launch_quarter="2024-Q1",
            current_price_per_sqft=Decimal("5000"),
            current_quarter="2025-Q1",
        )
        assert len(points) == 2
        assert all(point["source"] is not ProjectPriceSource.derived for point in points)

    def test_a_filing_quarter_before_the_launch_quarter_invents_nothing(self):
        points = derive_price_points(
            rera_project_id=7,
            launch_price_per_sqft=Decimal("5000"),
            launch_quarter="2024-Q3",
            current_price_per_sqft=Decimal("8000"),
            current_quarter="2024-Q1",
        )
        assert len(points) == 2
        assert {point["quarter"] for point in points} == {"2024-Q1", "2024-Q3"}

    def test_recorded_at_is_the_moment_of_computation(self):
        moment = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
        points = derive_price_points(
            rera_project_id=7,
            launch_price_per_sqft=Decimal("5000"),
            launch_quarter="2024-Q1",
            current_price_per_sqft=Decimal("8000"),
            current_quarter="2025-Q1",
            recorded_at=moment,
        )
        assert all(point["recorded_at"] == moment for point in points)


def _work_item(**over):
    item = {
        "rera_project_id": 11,
        "registration_date": None,
        "rera_received_date": None,
        "launch_price_per_sqft": None,
        "current_price_per_sqft": None,
        "profile_updated_at": None,
        "latest_document_on": None,
    }
    item.update(over)
    return item


class TestScrapeReadsTheRegister:
    async def test_a_project_with_no_dates_writes_nothing(self, monkeypatch):
        scraper = ReraPriceHistoryScraper()
        monkeypatch.setattr(
            scraper,
            "_work_list",
            AsyncMock(
                return_value=[
                    _work_item(
                        launch_price_per_sqft=Decimal("5000"),
                        current_price_per_sqft=Decimal("9000"),
                    )
                ]
            ),
        )

        result = await scraper._scrape()

        assert result.records == []
        assert result.source_coverage[0]["projects_skipped"] == 1
        assert result.source_coverage[0]["projects_priced"] == 0

    async def test_the_launch_quarter_falls_back_to_the_registration_date(self, monkeypatch):
        scraper = ReraPriceHistoryScraper()
        monkeypatch.setattr(
            scraper,
            "_work_list",
            AsyncMock(
                return_value=[
                    _work_item(
                        rera_received_date=None,
                        registration_date=date(2024, 5, 20),
                        launch_price_per_sqft=Decimal("4200"),
                    )
                ]
            ),
        )

        result = await scraper._scrape()

        assert len(result.records) == 1
        assert result.records[0]["quarter"] == "2024-Q2"
        assert result.records[0]["source"] is ProjectPriceSource.launch
        assert result.records[0]["price_per_sqft"] == Decimal("4200")

    async def test_the_filing_quarter_prefers_the_latest_document_date(self, monkeypatch):
        scraper = ReraPriceHistoryScraper()
        monkeypatch.setattr(
            scraper,
            "_work_list",
            AsyncMock(
                return_value=[
                    _work_item(
                        current_price_per_sqft=Decimal("7100"),
                        latest_document_on=date(2025, 2, 9),
                        profile_updated_at=datetime(2026, 8, 1, tzinfo=UTC),
                    )
                ]
            ),
        )

        result = await scraper._scrape()

        assert len(result.records) == 1
        assert result.records[0]["quarter"] == "2025-Q1"
        assert result.records[0]["source"] is ProjectPriceSource.filing

    async def test_a_filing_without_a_document_date_writes_no_filing_point(self, monkeypatch):
        """The profile update time is when we read the filing, not a date it states."""
        scraper = ReraPriceHistoryScraper()
        monkeypatch.setattr(
            scraper,
            "_work_list",
            AsyncMock(
                return_value=[
                    _work_item(
                        current_price_per_sqft=Decimal("7100"),
                        profile_updated_at=datetime(2025, 11, 3, tzinfo=UTC),
                    )
                ]
            ),
        )

        result = await scraper._scrape()

        assert [r for r in result.records if r["source"] is ProjectPriceSource.filing] == []

    async def test_a_successful_read_with_no_points_is_not_a_failed_run(self, monkeypatch):
        scraper = ReraPriceHistoryScraper()
        monkeypatch.setattr(scraper, "_work_list", AsyncMock(return_value=[]))

        result = await scraper._scrape()

        assert result.successful_sources == 1
        assert result.status == "success"
        assert result.records == []


class TestRightsGate:
    async def test_run_is_disabled_before_any_read(self, monkeypatch):
        monkeypatch.setattr(settings, "HRERA_DATA_ENABLED", False, raising=False)
        monkeypatch.setattr(
            "app.services.data_hub.base_scraper.get_bg_session_factory",
            MagicMock(side_effect=AssertionError("no run row may be created")),
        )
        scraper = ReraPriceHistoryScraper()
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
        scraper = ReraPriceHistoryScraper()

        assert (await scraper._scrape()).records == []
        assert await scraper._upsert(MagicMock(), [{"rera_project_id": 1}]) == {
            "found": 0,
            "upserted": 0,
            "failed": 0,
        }
