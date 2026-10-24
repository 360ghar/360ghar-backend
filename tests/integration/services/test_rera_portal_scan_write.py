"""Integration test for the portal-id scanner's register-row write.

The scanner is the only path that discovers HRERA projects, and it has no list
page to read: it creates the ``rera_projects`` row from the filing itself. This
test covers that write against a real database, because the parts worth checking
are the ones a mocked session cannot show — that the insert actually lands, that
a second pass updates instead of duplicating, and that a re-scan does not reset
a register status somebody else set.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.models.data_hub import ReraProject, ReraProjectProfile, ReraStatutoryApproval
from app.services.data_hub.rera_portal_scan import ReraPortalIdScanner
from app.services.data_hub.rera_project_detail import (
    filing_source_document,
    parse_rep_i,
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
# The filing page states only the portal's pre-registration identifier. The real
# registration number above is assigned at registration and never appears on it.
FILING_IDENTIFIER = "RERA-GRG-PROJ-1540-2024"
PORTAL_PROJECT_ID = "2779"


def _scan_record(html: str) -> dict:
    """Build a record the way ``ReraPortalIdScanner._scrape`` builds it."""
    filing = parse_rep_i(html, portal_project_id=PORTAL_PROJECT_ID)
    assert filing.ok, filing.errors
    url = f"https://haryanarera.gov.in/view_project/project_preview_open/{PORTAL_PROJECT_ID}"
    document = filing_source_document(html, portal_project_id=PORTAL_PROJECT_ID)
    document["source_key"] = f"{url}#{document['content_sha256']}"
    record = filing.to_dict()
    record["_source_key"] = document["source_key"]
    record["_source_document"] = document
    # ``BaseScraper.run`` attaches this from the source document before upsert.
    record["_source_checked_at"] = document["checked_at"]
    return record


async def _scan(db_session, record: dict) -> dict:
    stats = await ReraPortalIdScanner(start_id=1, end_id=1)._upsert(db_session, [record])
    await db_session.flush()
    return stats


async def _one_project(db_session) -> ReraProject:
    result = await db_session.execute(
        select(ReraProject).where(
            ReraProject.raw_data["portal_project_id"].astext == PORTAL_PROJECT_ID
        )
    )
    return result.scalar_one()


async def test_the_filing_page_never_states_a_registration_number() -> None:
    """The premise the scanner's conflict target rests on.

    If HRERA ever starts publishing the registration number on the filing page,
    this test fails and the scanner should be re-keyed onto it.
    """
    html = FIXTURE.read_text(encoding="utf-8")
    assert FILING_IDENTIFIER in html
    assert RERA_NUMBER not in html


async def test_a_scan_creates_the_register_row_from_the_filing(db_session) -> None:
    """No listing page can supply this row, so the filing has to."""
    record = _scan_record(FIXTURE.read_text(encoding="utf-8"))

    stats = await _scan(db_session, record)

    assert stats == {"found": 1, "upserted": 1, "failed": 0}
    project = await _one_project(db_session)
    assert project.project_name == "DLF PRIVANA WEST"
    assert project.developer_name == "DLF LIMITED"
    # The developer pages group projects by this slug and the dossier derives it
    # the same way from the same name. Without it a developer page shows a score
    # but no projects, because the score matches on the name and the project list
    # matches on the slug.
    assert project.developer_slug == "dlf-limited"
    assert project.district == "Gurugram"
    assert project.status == "registered"
    # The portal's filing identifier, recorded verbatim rather than reshaped.
    assert project.rera_number == FILING_IDENTIFIER
    assert project.slug == "dlf-privana-west-rera-grg-proj-1540-2024"
    assert project.total_units == 795
    assert project.raw_data["portal_project_id"] == PORTAL_PROJECT_ID
    assert project.raw_data["identifier_kind"] == "temp_project_id"
    # The filing's own site address, not a synthesised one.
    assert "SECTOR 76/77" in (project.location or "")
    # The detail scraper ran on the row the scanner just created.
    profile = (
        await db_session.execute(
            select(ReraProjectProfile).where(ReraProjectProfile.rera_project_id == project.id)
        )
    ).scalar_one()
    assert profile.towers == 5
    assert profile.land_area_sqm is not None


async def test_rescanning_the_same_project_does_not_duplicate_it(db_session) -> None:
    html = FIXTURE.read_text(encoding="utf-8")
    await _scan(db_session, _scan_record(html))

    stats = await _scan(db_session, _scan_record(html))

    assert stats == {"found": 1, "upserted": 1, "failed": 0}
    count = await db_session.execute(
        select(func.count(ReraProject.id)).where(
            ReraProject.raw_data["portal_project_id"].astext == PORTAL_PROJECT_ID
        )
    )
    assert count.scalar_one() == 1


async def test_a_rescan_does_not_overwrite_registration_facts(db_session) -> None:
    """A status, a registration number, and a published slug outrank a filing read.

    The portal re-issues project ids, so a project already stored can be reached
    again under a new one. That must not flip a revoked project back to
    registered, rename it back to its filing id, or move a published URL.
    """
    html = FIXTURE.read_text(encoding="utf-8")
    await _scan(db_session, _scan_record(html))
    project = await _one_project(db_session)
    project.status = "revoked"
    project.rera_number = RERA_NUMBER
    project.slug = "dlf-privana-west"
    await db_session.flush()

    await _scan(db_session, _scan_record(html))

    after = await _one_project(db_session)
    assert after.status == "revoked"
    assert after.rera_number == RERA_NUMBER
    assert after.slug == "dlf-privana-west"
    # The descriptive fields it does own still refresh.
    assert after.project_name == "DLF PRIVANA WEST"


async def test_a_scan_without_a_check_time_is_refused(db_session) -> None:
    record = _scan_record(FIXTURE.read_text(encoding="utf-8"))
    del record["_source_checked_at"]

    stats = await _scan(db_session, record)

    assert stats == {"found": 1, "upserted": 0, "failed": 1}
    remaining = await db_session.execute(
        select(func.count(ReraProject.id)).where(
            ReraProject.raw_data["portal_project_id"].astext == PORTAL_PROJECT_ID
        )
    )
    assert remaining.scalar_one() == 0


async def test_the_licence_date_is_not_published_as_the_registration_date(db_session) -> None:
    """The filing states when the DTCP licence was granted, not when HRERA registered.

    Part B row 5 reads ``DTCP 219 of 2023 25.10.2023 valid upto 24.10.2028``, so
    the date the parser reads is the licence grant date. Writing it into
    ``rera_projects.registration_date`` publishes it as the RERA registration
    date, which ``GET /data-hub/rera-projects`` serves: the live register held
    2009-11-19 for RERA-PKL-PROJ-628-2019 and 2013-12-11 for
    RERA-GRG-PROJ-1182-2022, years before the RERA Act came into force. The date
    belongs on the statutory approval row, and it is still written there.
    """
    await _scan(db_session, _scan_record(FIXTURE.read_text(encoding="utf-8")))

    project = await _one_project(db_session)
    assert project.registration_date is None
    statutory = (
        await db_session.execute(
            select(ReraStatutoryApproval).where(
                ReraStatutoryApproval.rera_project_id == project.id
            )
        )
    ).scalar_one()
    assert statutory.licence_date == date(2023, 10, 25)


async def test_a_rescan_clears_a_registration_date_read_from_the_licence(db_session) -> None:
    """A row an earlier run wrote the licence date into is repaired, not kept."""
    html = FIXTURE.read_text(encoding="utf-8")
    await _scan(db_session, _scan_record(html))
    project = await _one_project(db_session)
    project.registration_date = date(2009, 11, 19)
    await db_session.flush()

    await _scan(db_session, _scan_record(html))

    # The scanner writes through Core, so the session's copy of the row is stale.
    db_session.expire_all()
    after = await _one_project(db_session)
    assert after.registration_date is None
