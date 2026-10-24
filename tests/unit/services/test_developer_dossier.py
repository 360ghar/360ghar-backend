"""Developer reconciliation and the five-pillar score: formulas pinned by hand."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

from sqlalchemy import func, select

from app.config import settings
from app.models.data_hub import (
    Developer,
    DeveloperScore,
    ReraComplaint,
    ReraProject,
    ReraProjectCost,
    ReraProjectProfile,
    ReraQuarterlyExpenditure,
    ReraStatutoryApproval,
)
from app.models.enums import ProjectStage
from app.services.data_hub.developer_dossier import (
    DEVELOPER_PILLAR_WEIGHTS,
    DeveloperDossierScraper,
    compute_complaints,
    compute_delivery,
    compute_financials,
    compute_market_reception,
    compute_pillars,
    compute_regulatory,
    compute_total_score,
    count_stages,
    developer_slug,
    should_write_score,
)

ALL_PILLARS_NONE = {
    "delivery": None,
    "regulatory": None,
    "complaints": None,
    "financials": None,
    "market_reception": None,
}


class TestWeights:
    def test_the_five_weights_sum_to_one(self):
        assert set(DEVELOPER_PILLAR_WEIGHTS) == {
            "delivery",
            "regulatory",
            "complaints",
            "financials",
            "market_reception",
        }
        assert sum(DEVELOPER_PILLAR_WEIGHTS.values()) == Decimal("1.00")


class TestDeliveryPillar:
    def test_share_of_staged_projects_that_completed(self):
        assert compute_delivery({"completed": 3, "under_construction": 1}) == Decimal("75.00")

    def test_a_developer_with_staged_but_unfinished_projects_scores_zero(self):
        assert compute_delivery({"under_construction": 2}) == Decimal("0.00")
        assert compute_delivery({"pre_launch": 1, "near_possession": 1}) == Decimal("0.00")

    def test_no_staged_project_is_none_not_zero(self):
        assert compute_delivery({}) is None
        assert compute_delivery({"pre_launch": 0}) is None

    def test_stage_counts_also_feed_the_row_counts(self):
        assert count_stages({"completed": 3, "near_possession": 1}) == (3, 1)
        assert count_stages({}) == (0, 0)


class TestRegulatoryPillar:
    def test_plan_approvals_loi_and_licence_are_averaged(self):
        project = {
            "has_statutory_row": True,
            "plan_approvals_declared": 4,
            "plan_approvals_obtained": 2,
            "has_loi": True,
            "has_licence": False,
            "expired_without_completion": False,
        }
        # (2/4 + 1 + 0) / 3 = 0.5
        assert compute_regulatory([project]) == Decimal("50.00")

    def test_a_blank_plan_approval_table_does_not_enter_the_mean(self):
        project = {
            "has_statutory_row": True,
            "plan_approvals_declared": 0,
            "plan_approvals_obtained": 0,
            "has_loi": False,
            "has_licence": True,
            "expired_without_completion": False,
        }
        # (0 + 1) / 2 = 0.5
        assert compute_regulatory([project]) == Decimal("50.00")

    def test_an_expired_project_costs_fifteen_points(self):
        project = {
            "has_statutory_row": True,
            "plan_approvals_declared": 4,
            "plan_approvals_obtained": 4,
            "has_loi": True,
            "has_licence": True,
            "expired_without_completion": True,
        }
        assert compute_regulatory([project]) == Decimal("85.00")

    def test_the_penalty_never_pushes_the_pillar_below_zero(self):
        project = {
            "has_statutory_row": True,
            "plan_approvals_declared": 0,
            "plan_approvals_obtained": 0,
            "has_loi": False,
            "has_licence": False,
            "expired_without_completion": True,
        }
        assert compute_regulatory([project, project, project]) == Decimal("0.00")

    def test_a_project_without_a_statutory_row_is_excluded_not_failed(self):
        project = {
            "has_statutory_row": False,
            "plan_approvals_declared": 0,
            "plan_approvals_obtained": 0,
            "has_loi": False,
            "has_licence": False,
            "expired_without_completion": False,
        }
        assert compute_regulatory([project]) is None

    def test_no_projects_at_all_is_none(self):
        assert compute_regulatory([]) is None


class TestComplaintsPillar:
    def test_no_complaints_scores_full(self):
        assert compute_complaints(complaint_count=0, project_count=4) == Decimal("100.00")

    def test_one_complaint_per_project_halves_the_score(self):
        assert compute_complaints(complaint_count=4, project_count=4) == Decimal("50.00")

    def test_more_complaints_per_project_keep_lowering_the_score(self):
        assert compute_complaints(complaint_count=8, project_count=4) == Decimal("33.33")
        assert compute_complaints(complaint_count=16, project_count=4) == Decimal("20.00")

    def test_complaints_with_no_filed_project_still_count(self):
        # 100 / (1 + 6/1) = 14.2857...
        assert compute_complaints(complaint_count=6, project_count=0) == Decimal("14.29")

    def test_neither_projects_nor_complaints_is_none(self):
        assert compute_complaints(complaint_count=0, project_count=0) is None


class TestFinancialsPillar:
    def test_share_of_cost_already_spent(self):
        projects = [{"total_cost": Decimal("1000"), "expenditure_incurred": Decimal("250")}]
        assert compute_financials(projects) == Decimal("25.00")

    def test_the_mean_is_taken_over_the_projects_the_filing_supports(self):
        projects = [
            {"total_cost": Decimal("1000"), "expenditure_incurred": Decimal("250")},
            {"total_cost": Decimal("1000"), "expenditure_incurred": Decimal("750")},
            {"total_cost": None, "expenditure_incurred": Decimal("750")},
            {"total_cost": Decimal("1000"), "expenditure_incurred": None},
        ]
        assert compute_financials(projects) == Decimal("50.00")

    def test_spending_above_the_filed_cost_is_held_at_full(self):
        projects = [{"total_cost": Decimal("1000"), "expenditure_incurred": Decimal("1500")}]
        assert compute_financials(projects) == Decimal("100.00")

    def test_no_cost_data_is_none_not_zero(self):
        assert compute_financials([]) is None
        assert compute_financials([{"total_cost": None, "expenditure_incurred": None}]) is None
        assert compute_financials([{"total_cost": Decimal("0"), "expenditure_incurred": Decimal("5")}]) is None


class TestMarketReceptionPillar:
    def test_a_twenty_percent_price_rise_scores_full(self):
        projects = [
            {
                "launch_price_per_sqft": Decimal("100"),
                "current_price_per_sqft": Decimal("120"),
                "units_booked": None,
                "total_units": None,
            }
        ]
        assert compute_market_reception(projects) == Decimal("100.00")

    def test_a_twenty_percent_price_fall_scores_zero(self):
        projects = [
            {
                "launch_price_per_sqft": Decimal("100"),
                "current_price_per_sqft": Decimal("80"),
                "units_booked": None,
                "total_units": None,
            }
        ]
        assert compute_market_reception(projects) == Decimal("0.00")

    def test_a_flat_price_scores_the_midpoint(self):
        projects = [
            {
                "launch_price_per_sqft": Decimal("100"),
                "current_price_per_sqft": Decimal("100"),
                "units_booked": None,
                "total_units": None,
            }
        ]
        assert compute_market_reception(projects) == Decimal("50.00")

    def test_bookings_are_a_component_in_their_own_right(self):
        projects = [
            {
                "launch_price_per_sqft": None,
                "current_price_per_sqft": None,
                "units_booked": 30,
                "total_units": 60,
            }
        ]
        assert compute_market_reception(projects) == Decimal("50.00")

    def test_price_movement_and_bookings_are_averaged(self):
        projects = [
            {
                "launch_price_per_sqft": Decimal("100"),
                "current_price_per_sqft": Decimal("120"),
                "units_booked": 60,
                "total_units": 100,
            }
        ]
        # (100 + 60) / 2
        assert compute_market_reception(projects) == Decimal("80.00")

    def test_no_price_and_no_bookings_is_none(self):
        assert compute_market_reception([]) is None
        assert (
            compute_market_reception(
                [
                    {
                        "launch_price_per_sqft": None,
                        "current_price_per_sqft": None,
                        "units_booked": None,
                        "total_units": 100,
                    }
                ]
            )
            is None
        )


class TestTotalScore:
    def test_every_pillar_none_gives_no_total(self):
        assert compute_total_score(ALL_PILLARS_NONE) is None

    def test_a_lone_pillar_is_the_total(self):
        assert compute_total_score({**ALL_PILLARS_NONE, "delivery": Decimal("80.00")}) == Decimal(
            "80.00"
        )

    def test_the_mean_renormalises_over_the_pillars_present(self):
        pillars = {**ALL_PILLARS_NONE, "delivery": Decimal("100"), "complaints": Decimal("0")}
        # (100 * 0.30 + 0 * 0.20) / 0.50
        assert compute_total_score(pillars) == Decimal("60.00")

    def test_all_five_pillars_use_the_declared_weights(self):
        pillars = {
            "delivery": Decimal("50"),
            "regulatory": Decimal("43.33"),
            "complaints": Decimal("66.67"),
            "financials": Decimal("25"),
            "market_reception": Decimal("80"),
        }
        assert compute_total_score(pillars) == Decimal("50.92")

    def test_a_computed_zero_is_written_but_no_data_is_not(self):
        assert should_write_score({**ALL_PILLARS_NONE, "delivery": Decimal("0.00")}) is True
        assert should_write_score(ALL_PILLARS_NONE) is False


class TestDeveloperSlug:
    def test_a_promoter_name_becomes_a_stable_slug(self):
        assert developer_slug("Godrej Properties Pvt. Ltd.") == "godrej-properties-pvt-ltd"

    def test_the_same_name_always_gives_the_same_slug(self):
        assert developer_slug("DLF Ltd") == developer_slug("dlf ltd")


class TestPillarsTogether:
    def test_each_pillar_is_computed_from_its_own_inputs(self):
        pillars = compute_pillars(
            stage_counts={"completed": 1, "under_construction": 1},
            regulatory_projects=[
                {
                    "has_statutory_row": True,
                    "plan_approvals_declared": 4,
                    "plan_approvals_obtained": 2,
                    "has_loi": True,
                    "has_licence": False,
                    "expired_without_completion": False,
                }
            ],
            complaint_count=0,
            project_count=2,
            financial_projects=[
                {"total_cost": Decimal("1000"), "expenditure_incurred": Decimal("250")}
            ],
            market_projects=[
                {
                    "launch_price_per_sqft": Decimal("100"),
                    "current_price_per_sqft": Decimal("120"),
                    "units_booked": 60,
                    "total_units": 100,
                }
            ],
        )
        assert pillars == {
            "delivery": Decimal("50.00"),
            "regulatory": Decimal("50.00"),
            "complaints": Decimal("100.00"),
            "financials": Decimal("25.00"),
            "market_reception": Decimal("80.00"),
        }

    def test_a_developer_with_no_data_gets_five_nones(self):
        pillars = compute_pillars(
            stage_counts={},
            regulatory_projects=[],
            complaint_count=0,
            project_count=0,
            financial_projects=[],
            market_projects=[],
        )
        assert pillars == ALL_PILLARS_NONE
        assert compute_total_score(pillars) is None


def _score_record(**over):
    record = {
        "developer_slug": "no-data-builders",
        "developer_name": "No Data Builders",
        "pillars": dict(ALL_PILLARS_NONE),
        "total_score": None,
        "project_count": 1,
        "delivered_count": 0,
        "under_construction_count": 0,
        "complaint_count": 0,
        "computed_at": datetime.now(UTC),
    }
    record.update(over)
    return record


class TestUpsertWrites:
    async def test_a_developer_with_no_pillar_data_gets_a_row_but_no_score(self, db_session):
        scraper = DeveloperDossierScraper()

        stats = await scraper._upsert(db_session, [_score_record()])

        assert stats == {"found": 1, "upserted": 1, "failed": 0}
        developer = (
            await db_session.execute(
                select(Developer).where(Developer.slug == "no-data-builders")
            )
        ).scalar_one()
        assert developer.name == "No Data Builders"
        assert developer.legal_name == "No Data Builders"
        score_count = (
            await db_session.execute(
                select(func.count(DeveloperScore.id)).where(
                    DeveloperScore.developer_id == developer.id
                )
            )
        ).scalar_one()
        assert score_count == 0

    async def test_the_score_pipeline_pins_every_number(self, db_session):
        developer_name = "Pinned Builders"
        expired = datetime.now(UTC).date() - timedelta(days=30)
        first = ReraProject(
            rera_number="TEST-DOSSIER-1",
            project_name="Pinned One",
            developer_name=developer_name,
            district="Gurugram",
            status="completed",
            total_units=100,
            units_booked=60,
            registration_date=date(2024, 1, 10),
        )
        second = ReraProject(
            rera_number="TEST-DOSSIER-2",
            project_name="Pinned Two",
            developer_name=developer_name,
            district="Gurugram",
            status="registered",
            total_units=50,
            expiry_date=expired,
            registration_date=date(2024, 6, 10),
        )
        db_session.add_all([first, second])
        await db_session.flush()
        db_session.add_all(
            [
                ReraProjectProfile(
                    rera_project_id=first.id,
                    stage=ProjectStage.completed,
                    launch_price_per_sqft=Decimal("5000"),
                    current_price_per_sqft=Decimal("6000"),
                ),
                ReraProjectProfile(
                    rera_project_id=second.id, stage=ProjectStage.under_construction
                ),
                ReraStatutoryApproval(
                    rera_project_id=first.id,
                    loi_number="LOI-1",
                    plan_approvals={"A": True, "B": False, "C": True, "D": True},
                ),
                ReraProjectCost(rera_project_id=first.id, total_cost=Decimal("1000")),
                ReraQuarterlyExpenditure(
                    rera_project_id=first.id,
                    category="apartment",
                    year=2024,
                    quarter=1,
                    particular="Construction",
                    amount=Decimal("250"),
                ),
                ReraComplaint(
                    order_number="TEST-DOSSIER-COMPLAINT-1",
                    respondent_builder="PINNED BUILDERS",
                    order_date=datetime.now(UTC).date() - timedelta(days=2),
                    rera_number=first.rera_number,
                ),
                # Values another source owns must survive the reconcile.
                Developer(
                    slug="pinned-builders",
                    name="Stale Name",
                    summary="Kept from an earlier source",
                    logo_url="https://example.test/logo.png",
                    website_url="https://example.test",
                ),
            ]
        )
        await db_session.flush()

        scraper = DeveloperDossierScraper()
        records = await scraper._collect(db_session)
        record = next(item for item in records if item["developer_slug"] == "pinned-builders")

        assert record["pillars"] == {
            "delivery": Decimal("50.00"),
            "regulatory": Decimal("43.33"),
            "complaints": Decimal("66.67"),
            "financials": Decimal("25.00"),
            "market_reception": Decimal("80.00"),
        }
        assert record["total_score"] == Decimal("50.92")
        assert record["project_count"] == 2
        assert record["delivered_count"] == 1
        assert record["under_construction_count"] == 1
        assert record["complaint_count"] == 1

        stats = await scraper._upsert(db_session, records)

        assert stats["failed"] == 0
        developer = (
            await db_session.execute(
                select(Developer).where(Developer.slug == "pinned-builders")
            )
        ).scalar_one()
        assert developer.name == developer_name
        assert developer.legal_name == developer_name
        assert developer.summary == "Kept from an earlier source"
        assert developer.logo_url == "https://example.test/logo.png"
        assert developer.website_url == "https://example.test"

        score = (
            await db_session.execute(
                select(DeveloperScore).where(DeveloperScore.developer_id == developer.id)
            )
        ).scalar_one()
        assert score.delivery == Decimal("50.00")
        assert score.regulatory == Decimal("43.33")
        assert score.complaints == Decimal("66.67")
        assert score.financials == Decimal("25.00")
        assert score.market_reception == Decimal("80.00")
        assert score.total_score == Decimal("50.92")
        assert score.project_count == 2
        assert score.delivered_count == 1
        assert score.under_construction_count == 1
        assert score.complaint_count == 1
        assert score.computed_at is not None

    async def test_the_complaint_match_is_case_insensitive(self, db_session):
        project = ReraProject(
            rera_number="TEST-DOSSIER-3",
            project_name="Pinned Three",
            developer_name="Case Test Builders",
            district="Gurugram",
            status="registered",
        )
        db_session.add(project)
        await db_session.flush()
        db_session.add(
            ReraComplaint(
                order_number="TEST-DOSSIER-COMPLAINT-2",
                respondent_builder="case test builders",
                order_date=datetime.now(UTC).date(),
                rera_number=project.rera_number,
            )
        )
        await db_session.flush()

        records = await DeveloperDossierScraper()._collect(db_session)
        record = next(item for item in records if item["developer_slug"] == "case-test-builders")

        assert record["complaint_count"] == 1


class TestComplaintAttributionCoverage:
    """The complaint match is exact, so the gap has to be reported, not hidden.

    The developer name comes from the filing page and the respondent name from the
    complaint page, so a differently-written name matches nothing and the
    complaints pillar reads a perfect 100. These tests pin the reporting that makes
    that visible.
    """

    async def test_an_unmatched_complaint_is_counted_as_unmatched(self, db_session):
        project = ReraProject(
            rera_number="TEST-COVERAGE-RERA-1",
            project_name="Coverage Test Project",
            developer_name="Coverage Test Developers Limited",
            district="Gurugram",
            status="registered",
        )
        db_session.add(project)
        await db_session.flush()
        db_session.add(
            ReraComplaint(
                order_number="TEST-COVERAGE-COMPLAINT-1",
                # The same firm, written the way a complaint page writes it.
                respondent_builder="M/s Coverage Test Developers Ltd",
                order_date=datetime.now(UTC).date(),
                rera_number=project.rera_number,
            )
        )
        await db_session.flush()

        coverage = await DeveloperDossierScraper()._complaint_coverage(db_session)

        assert coverage["complaints_with_a_named_builder"] == 1
        assert coverage["complaints_matched_to_a_register_developer"] == 0
        assert coverage["complaints_unmatched"] == 1

    async def test_an_exact_name_still_matches(self, db_session):
        project = ReraProject(
            rera_number="TEST-COVERAGE-RERA-2",
            project_name="Coverage Test Project Two",
            developer_name="Coverage Test Developers Limited",
            district="Gurugram",
            status="registered",
        )
        db_session.add(project)
        await db_session.flush()
        db_session.add(
            ReraComplaint(
                order_number="TEST-COVERAGE-COMPLAINT-2",
                # Same string, different case: the match is case-insensitive.
                respondent_builder="coverage test developers limited",
                order_date=datetime.now(UTC).date(),
                rera_number=project.rera_number,
            )
        )
        await db_session.flush()

        coverage = await DeveloperDossierScraper()._complaint_coverage(db_session)

        assert coverage["complaints_matched_to_a_register_developer"] == 1
        assert coverage["complaints_unmatched"] == 0


class TestDeveloperSlugBackfill:
    """A project row with a name but no slug is invisible to its builder page.

    The builder list groups projects by ``developer_slug`` while the score matches
    on ``developer_name``, so a null slug makes a project appear in a developer's
    score and not in its project list. Every row written before the column existed
    looked like that, which is why ``GET /data-hub/builders`` returned nothing and
    every builder page was a 404.
    """

    async def test_a_null_slug_is_filled_from_the_rows_own_name(self, db_session):
        db_session.add(
            ReraProject(
                rera_number="TEST-SLUG-RERA-1",
                project_name="Slug Backfill Project",
                developer_name="Backfill Test Developers Limited",
                district="Gurugram",
                status="registered",
            )
        )
        await db_session.flush()

        repaired = await DeveloperDossierScraper()._backfill_developer_slugs(db_session)

        assert repaired == 1
        project = (
            await db_session.execute(
                select(ReraProject).where(ReraProject.rera_number == "TEST-SLUG-RERA-1")
            )
        ).scalar_one()
        assert project.developer_slug == "backfill-test-developers-limited"

    async def test_the_backfill_matches_generate_slug_exactly(self, db_session):
        """The repair must produce the same slug the upsert path would.

        Two implementations of one rule would drift, and a drifted slug splits one
        developer into two groups — the score on one slug and the projects on
        another. This pins them together.
        """
        name = "M/s Drift Check & Sons (India) Pvt. Ltd."
        db_session.add(
            ReraProject(
                rera_number="TEST-SLUG-RERA-2",
                project_name="Slug Drift Project",
                developer_name=name,
                district="Gurugram",
                status="registered",
            )
        )
        await db_session.flush()

        await DeveloperDossierScraper()._backfill_developer_slugs(db_session)

        project = (
            await db_session.execute(
                select(ReraProject).where(ReraProject.rera_number == "TEST-SLUG-RERA-2")
            )
        ).scalar_one()
        assert project.developer_slug == developer_slug(name)

    async def test_a_slug_that_is_already_set_is_never_touched(self, db_session):
        """The repair must not re-group a project another writer already placed."""
        db_session.add(
            ReraProject(
                rera_number="TEST-SLUG-RERA-3",
                project_name="Slug Pinned Project",
                developer_name="Backfill Test Developers Limited",
                developer_slug="a-different-group-entirely",
                district="Gurugram",
                status="registered",
            )
        )
        await db_session.flush()

        await DeveloperDossierScraper()._backfill_developer_slugs(db_session)

        project = (
            await db_session.execute(
                select(ReraProject).where(ReraProject.rera_number == "TEST-SLUG-RERA-3")
            )
        ).scalar_one()
        assert project.developer_slug == "a-different-group-entirely"

    async def test_a_second_pass_repairs_nothing(self, db_session):
        """The repair is idempotent, so a weekly run costs one select when clean."""
        db_session.add(
            ReraProject(
                rera_number="TEST-SLUG-RERA-4",
                project_name="Slug Idempotent Project",
                developer_name="Idempotent Test Developers",
                district="Gurugram",
                status="registered",
            )
        )
        await db_session.flush()

        scraper = DeveloperDossierScraper()
        assert await scraper._backfill_developer_slugs(db_session) == 1
        assert await scraper._backfill_developer_slugs(db_session) == 0


class TestRightsGate:
    async def test_run_is_disabled_before_any_read(self, monkeypatch):
        monkeypatch.setattr(settings, "HRERA_DATA_ENABLED", False, raising=False)
        monkeypatch.setattr(
            "app.services.data_hub.base_scraper.get_bg_session_factory",
            MagicMock(side_effect=AssertionError("no run row may be created")),
        )
        scraper = DeveloperDossierScraper()
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
        scraper = DeveloperDossierScraper()

        assert (await scraper._scrape()).records == []
        assert await scraper._upsert(MagicMock(), [_score_record()]) == {
            "found": 0,
            "upserted": 0,
            "failed": 0,
        }
