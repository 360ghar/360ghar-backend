"""Integration test for the REP-I filing write path.

The parser is unit-tested against a captured filing. This test covers the other
half: that a parsed filing actually lands in the database, that re-running it
updates rather than duplicates, and that the PII rules survive the round trip.
Unit tests with a mocked session cannot catch a wrong `on_conflict` target or a
collection table that is appended to instead of replaced.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.models.data_hub import (
    ReraLandUsage,
    ReraProject,
    ReraProjectBankAccount,
    ReraProjectCost,
    ReraProjectDocument,
    ReraProjectFacility,
    ReraProjectNoc,
    ReraProjectPerson,
    ReraProjectProfile,
    ReraProjectSpecification,
    ReraProjectUnitConfig,
    ReraQuarterlyExpenditure,
    ReraStatutoryApproval,
)
from app.services.data_hub.rera_project_detail import (
    ReraProjectDetailScraper,
    filing_source_document,
    parse_rep_i,
    project_slug,
)

pytestmark = pytest.mark.integration

FIXTURE = (
    Path(__file__).resolve().parents[3]
    / "tests"
    / "fixtures"
    / "hrera"
    / "rep_i_privana_west.html"
)
RERA_NUMBER = "RERA-GRG-1540-2024"
PORTAL_PROJECT_ID = "2779"


async def _seed_project(db_session) -> ReraProject:
    project = ReraProject(
        rera_number=RERA_NUMBER,
        project_name="DLF PRIVANA WEST",
        developer_name="DLF LIMITED",
        developer_slug="dlf-limited",
        district="Gurugram",
        status="registered",
        raw_data={"portal_project_id": PORTAL_PROJECT_ID},
    )
    db_session.add(project)
    await db_session.flush()
    return project


def _record_for(project: ReraProject, html: str) -> dict:
    filing = parse_rep_i(html, portal_project_id=PORTAL_PROJECT_ID)
    assert filing.ok, filing.errors
    document = filing_source_document(html, portal_project_id=PORTAL_PROJECT_ID)
    document["source_key"] = document["canonical_url"]
    record = filing.to_dict()
    record["rera_project_id"] = project.id
    record["rera_number"] = project.rera_number
    record["project_name"] = filing.header.get("project_name")
    record["register_status"] = project.status
    record["_source_key"] = document["source_key"]
    record["_source_document"] = document
    # ``BaseScraper.run`` attaches this from the source document before upsert;
    # a direct ``_upsert`` call has to set it the same way.
    record["_source_checked_at"] = document["checked_at"]
    return record


async def _write(db_session, record: dict) -> dict:
    scraper = ReraProjectDetailScraper()
    stats = await scraper._upsert(db_session, [record])
    await db_session.flush()
    return stats


async def test_a_filing_lands_in_every_detail_table(db_session) -> None:
    project = await _seed_project(db_session)
    html = FIXTURE.read_text(encoding="utf-8")

    stats = await _write(db_session, _record_for(project, html))

    assert stats == {"found": 1, "upserted": 1, "failed": 0}

    async def count(model) -> int:
        result = await db_session.execute(
            select(func.count(model.id)).where(model.rera_project_id == project.id)
        )
        return int(result.scalar_one())

    assert await count(ReraLandUsage) == 12
    assert await count(ReraProjectDocument) == 127
    assert await count(ReraProjectFacility) == 18
    assert await count(ReraProjectNoc) == 5
    assert await count(ReraProjectPerson) == 41
    assert await count(ReraProjectUnitConfig) == 2
    assert await count(ReraProjectSpecification) == 23
    assert await count(ReraQuarterlyExpenditure) > 0

    profile = (
        await db_session.execute(
            select(ReraProjectProfile).where(ReraProjectProfile.rera_project_id == project.id)
        )
    ).scalar_one()
    assert profile.total_units == 795
    assert profile.towers == 5
    assert profile.portal_project_id == PORTAL_PROJECT_ID
    assert profile.stage is not None
    # The filing's completion date is 2031, so the project is under construction.
    assert profile.stage.value == "under_construction"

    cost = (
        await db_session.execute(
            select(ReraProjectCost).where(ReraProjectCost.rera_project_id == project.id)
        )
    ).scalar_one()
    assert cost.total_cost == 28370967000

    statutory = (
        await db_session.execute(
            select(ReraStatutoryApproval).where(
                ReraStatutoryApproval.rera_project_id == project.id
            )
        )
    ).scalar_one()
    assert statutory.licence_date.isoformat() == "2023-10-25"
    assert statutory.plan_approvals["Lay out Plan"] is True

    bank = (
        await db_session.execute(
            select(ReraProjectBankAccount).where(
                ReraProjectBankAccount.rera_project_id == project.id
            )
        )
    ).scalar_one()
    assert bank.account_number == "017705014520"


async def test_the_slug_is_backfilled_on_the_project_row(db_session) -> None:
    project = await _seed_project(db_session)
    assert project.slug is None
    html = FIXTURE.read_text(encoding="utf-8")

    await _write(db_session, _record_for(project, html))

    await db_session.refresh(project)
    assert project.slug == project_slug("DLF PRIVANA WEST", RERA_NUMBER)
    assert project.slug == "dlf-privana-west-rera-grg-1540-2024"


async def test_only_the_last_four_pan_characters_reach_the_database(db_session) -> None:
    project = await _seed_project(db_session)
    html = FIXTURE.read_text(encoding="utf-8")

    await _write(db_session, _record_for(project, html))

    people = (
        await db_session.execute(
            select(ReraProjectPerson).where(ReraProjectPerson.rera_project_id == project.id)
        )
    ).scalars().all()
    assert len(people) == 41
    for person in people:
        assert person.pan_last4 is None or len(person.pan_last4) == 4
    chairman = next(p for p in people if p.role.value == "chairman")
    assert chairman.pan_last4 == "665G"


async def test_rewriting_a_filing_updates_instead_of_duplicating(db_session) -> None:
    project = await _seed_project(db_session)
    html = FIXTURE.read_text(encoding="utf-8")

    await _write(db_session, _record_for(project, html))
    first_profile = (
        await db_session.execute(
            select(ReraProjectProfile).where(ReraProjectProfile.rera_project_id == project.id)
        )
    ).scalar_one()
    first_id = first_profile.id

    second = await _write(db_session, _record_for(project, html))
    assert second == {"found": 1, "upserted": 1, "failed": 0}

    profiles = (
        await db_session.execute(
            select(ReraProjectProfile).where(ReraProjectProfile.rera_project_id == project.id)
        )
    ).scalars().all()
    assert len(profiles) == 1
    assert profiles[0].id == first_id

    # The collection tables are replaced, not appended to.
    documents = await db_session.execute(
        select(func.count(ReraProjectDocument.id)).where(
            ReraProjectDocument.rera_project_id == project.id
        )
    )
    assert int(documents.scalar_one()) == 127
    people = await db_session.execute(
        select(func.count(ReraProjectPerson.id)).where(
            ReraProjectPerson.rera_project_id == project.id
        )
    )
    assert int(people.scalar_one()) == 41


async def test_every_detail_row_cites_the_filing_it_came_from(db_session) -> None:
    project = await _seed_project(db_session)
    html = FIXTURE.read_text(encoding="utf-8")

    await _write(db_session, _record_for(project, html))

    for model in (
        ReraLandUsage,
        ReraProjectDocument,
        ReraProjectFacility,
        ReraProjectPerson,
        ReraProjectUnitConfig,
        ReraProjectSpecification,
    ):
        uncited = await db_session.execute(
            select(func.count(model.id)).where(
                model.rera_project_id == project.id,
                model.source_document_id.is_(None),
            )
        )
        assert int(uncited.scalar_one()) == 0, f"{model.__name__} rows without a source document"


async def test_upsert_is_refused_when_hrera_is_turned_off(db_session, monkeypatch) -> None:
    from app.config import settings

    project = await _seed_project(db_session)
    html = FIXTURE.read_text(encoding="utf-8")
    monkeypatch.setattr(settings, "HRERA_DATA_ENABLED", False)

    stats = await _write(db_session, _record_for(project, html))

    assert stats == {"found": 0, "upserted": 0, "failed": 0}
    rows = await db_session.execute(
        select(func.count(ReraProjectProfile.id)).where(
            ReraProjectProfile.rera_project_id == project.id
        )
    )
    assert int(rows.scalar_one()) == 0


async def test_a_record_without_a_source_checked_at_is_not_written(db_session) -> None:
    project = await _seed_project(db_session)
    html = FIXTURE.read_text(encoding="utf-8")
    record = _record_for(project, html)
    record.pop("_source_checked_at", None)

    stats = await _write(db_session, record)

    assert stats == {"found": 1, "upserted": 0, "failed": 1}
    rows = await db_session.execute(
        select(func.count(ReraProjectProfile.id)).where(
            ReraProjectProfile.rera_project_id == project.id
        )
    )
    assert int(rows.scalar_one()) == 0


async def test_the_source_document_records_the_filing_hash(db_session) -> None:
    from app.models.data_hub import SourceDocument

    project = await _seed_project(db_session)
    html = FIXTURE.read_text(encoding="utf-8")
    record = _record_for(project, html)

    await _write(db_session, record)

    document = (
        await db_session.execute(
            select(SourceDocument).where(
                SourceDocument.canonical_url == record["_source_document"]["canonical_url"]
            )
        )
    ).scalar_one()
    assert document.authority == "Haryana Real Estate Regulatory Authority"
    assert document.source_record_id == PORTAL_PROJECT_ID
    assert len(document.content_sha256) == 64


async def test_a_reparse_that_cannot_read_a_figure_keeps_the_stored_one(db_session) -> None:
    """The regression: a re-parse used to overwrite good figures with NULL.

    A label the parser cannot read this time is not evidence that the figure went
    away. Before this was fixed the update set was every key in the payload, so a
    transient portal relabelling erased values a previous parse had read.
    """
    project = await _seed_project(db_session)
    html = FIXTURE.read_text(encoding="utf-8")

    await _write(db_session, _record_for(project, html))
    stored = (
        await db_session.execute(
            select(
                ReraProjectCost.land_cost,
                ReraProjectCost.infrastructure_cost,
            ).where(ReraProjectCost.rera_project_id == project.id)
        )
    ).one()
    assert stored.land_cost is not None and stored.infrastructure_cost is not None

    # A re-parse in which two cost labels came back unreadable. The other three
    # still read, so this is not the "every value is None" early return.
    record = _record_for(project, html)
    record["cost"]["land_cost"] = None
    record["cost"]["infrastructure_cost"] = None
    await _write(db_session, record)

    # Read the columns, not the entity: the write goes through a Core upsert that
    # the ORM's identity map does not see, so an entity read would return the
    # object cached above and the assertions would hold whatever the row says.
    after = (
        await db_session.execute(
            select(
                ReraProjectCost.land_cost,
                ReraProjectCost.infrastructure_cost,
                ReraProjectCost.total_cost,
            ).where(ReraProjectCost.rera_project_id == project.id)
        )
    ).one()
    assert after.land_cost == stored.land_cost
    assert after.infrastructure_cost == stored.infrastructure_cost
    # The figures the re-parse did read are still refreshed.
    assert after.total_cost is not None


async def test_a_reparse_may_clear_the_stage_on_purpose(db_session) -> None:
    """`stage` is the one field a re-parse may set back to NULL.

    ``derive_stage`` returns None when the filed completion date has passed but
    the register still lists the project as live, so its stage is unknown rather
    than assumed. Keeping the previous stage there would assert something the
    filing no longer supports.
    """
    project = await _seed_project(db_session)
    html = FIXTURE.read_text(encoding="utf-8")

    await _write(db_session, _record_for(project, html))
    stored_stage = (
        await db_session.execute(
            select(ReraProjectProfile.stage).where(ReraProjectProfile.rera_project_id == project.id)
        )
    ).scalar_one()
    assert stored_stage is not None

    # Without a construction start date the filing cannot place the project, so
    # derive_stage answers None.
    record = _record_for(project, html)
    record["profile"]["construction_start_date"] = None
    await _write(db_session, record)

    # Column read, not entity: see the note in the test above.
    after = (
        await db_session.execute(
            select(ReraProjectProfile.stage).where(ReraProjectProfile.rera_project_id == project.id)
        )
    ).scalar_one()
    assert after is None
