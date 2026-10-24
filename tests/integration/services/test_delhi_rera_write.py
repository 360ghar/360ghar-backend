"""Integration test for the Delhi RERA register write.

The parts worth checking against a real database are the ones a mocked session
cannot show: that the insert lands, that a re-run updates instead of duplicating,
and — the reason this file exists — that a Delhi project and an HRERA project
whose numeric portal ids are equal can both be stored.

That last one is not hypothetical. ``rera_projects`` carries a unique partial
index on ``(raw_data ->> 'portal_project_id')``. HRERA's portal ids are small
integers (``2779``); Delhi's are larger integers in the *same namespace*
(``10143``). A Delhi row that wrote its id into that key would collide with an
HRERA id-range walk reaching the same number, and the HRERA upsert would
overwrite the Delhi project with Haryana data. Delhi therefore never writes the
key at all, and the test below stores both rows under the same number and asserts
both survive.
"""
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import func, select, text

from app.config import settings
from app.models.data_hub import ReraProject, ReraProjectCost, ReraProjectProfile
from app.services.data_hub.base_scraper import attach_source_checked_at
from app.services.data_hub.delhi_rera_projects import (
    DelhiReraProjectScraper,
    parse_registered_projects_html,
)
from app.services.data_hub.rera_portal_scan import ReraPortalIdScanner
from app.services.data_hub.rera_project_detail import parse_rep_i

pytestmark = pytest.mark.integration

FIXTURE_DIR = Path(__file__).resolve().parents[3] / "tests" / "fixtures"
DELHI_REGISTER = FIXTURE_DIR / "delhi" / "registered_projects.html"
DELHI_DETAIL = FIXTURE_DIR / "delhi" / "project_detail_10143.html"
HRERA_FILING = FIXTURE_DIR / "hrera" / "rep_i_privana_west.html"

REGISTER_URL = "https://erera.co.in/reradelhiindex/PublicView/RegisteredProjectDetail"

# The Delhi project whose portal id collides with an HRERA id in the same range.
COLLIDING_ID = "10143"
DELHI_RERA_NUMBER = "DLRERA2026P0005"
# The HRERA filing page states only its pre-registration identifier; the walk
# addresses it by portal id, which is what shares the namespace with Delhi.
HRERA_FILING_NUMBER = "RERA-GRG-PROJ-1540-2024"


def _install_fetch(monkeypatch: pytest.MonkeyPatch) -> None:
    register_html = DELHI_REGISTER.read_text(encoding="utf-8")
    detail_html = DELHI_DETAIL.read_text(encoding="utf-8")

    async def fake_fetch(_self, url: str, **_kwargs) -> str:
        return register_html if url == REGISTER_URL else detail_html

    monkeypatch.setattr(DelhiReraProjectScraper, "_fetch_url", fake_fetch)


async def _delhi_records(monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    """Build records the way ``BaseScraper.run`` builds them."""
    _install_fetch(monkeypatch)
    result = await DelhiReraProjectScraper()._scrape()
    attach_source_checked_at(result.records, result.source_documents)
    assert result.records
    assert all(record.get("_source_checked_at") for record in result.records)
    return result.records


async def _write_delhi(db_session, monkeypatch: pytest.MonkeyPatch) -> dict:
    records = await _delhi_records(monkeypatch)
    stats = await DelhiReraProjectScraper()._upsert(db_session, records)
    await db_session.flush()
    assert stats["failed"] == 0
    return stats


async def _delhi_row(db_session) -> ReraProject:
    result = await db_session.execute(
        select(ReraProject).where(ReraProject.rera_number == DELHI_RERA_NUMBER)
    )
    return result.scalar_one()


async def _hrera_record() -> dict:
    """A scan record for the HRERA filing, addressed by the colliding id."""
    html = HRERA_FILING.read_text(encoding="utf-8")
    filing = parse_rep_i(html, portal_project_id=COLLIDING_ID)
    assert filing.ok, filing.errors
    url = (
        "https://haryanarera.gov.in/view_project/project_preview_open/"
        f"{COLLIDING_ID}"
    )
    document = {
        "source_key": f"{url}#fixture",
        "authority": "Haryana Real Estate Regulatory Authority",
        "title": f"FORM REP-I filing for portal project {COLLIDING_ID}",
        "canonical_url": url,
        "source_record_id": COLLIDING_ID,
        "jurisdiction": "Haryana, India",
        "document_type": "regulatory_filing",
        "language": "en",
        "license_name": None,
        "reuse_terms": None,
        "terms_url": None,
        "published_at": None,
        "effective_from": None,
        "effective_to": None,
        "fetched_at": datetime.now(UTC),
        "checked_at": datetime.now(UTC),
        "content_sha256": "0" * 64,
        "artifact_reference": None,
    }
    record = filing.to_dict()
    record["_source_key"] = document["source_key"]
    record["_source_document"] = document
    record["_source_checked_at"] = document["checked_at"]
    return record


async def test_the_register_row_is_created_from_the_register(
    db_session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Everything the register states lands on the row, unaltered."""
    await _write_delhi(db_session, monkeypatch)

    project = await _delhi_row(db_session)

    assert project.project_name == "Bharat Business Park"
    assert project.district == "South West Delhi"
    assert project.project_type == "Commercial"
    assert project.status == "registered"
    assert project.expiry_date is not None and project.expiry_date.year == 2031
    assert project.developer_name == "NBCC (India) Limited"
    assert project.developer_slug == "nbcc-india-limited"
    assert project.slug == "bharat-business-park-dlrera2026p0005"
    assert project.source_url.endswith(f"inProject_ID={COLLIDING_ID}&inPromoter_ID=1153&inPromoterType=2")
    assert project.raw_data["portal"] == "delhi_rera"
    assert project.raw_data["delhi_project_id"] == COLLIDING_ID
    assert project.raw_data["promoter_type"] == "2"
    assert project.raw_data["certificate_url"].endswith(".pdf")


async def test_the_filing_fills_the_columns_the_register_does_not_state(
    db_session, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _write_delhi(db_session, monkeypatch)

    project = await _delhi_row(db_session)

    assert project.location is not None
    assert project.location.startswith("Bharat Business Park")
    assert project.total_area_sqm is not None
    assert project.total_units == 78
    assert project.possession_date is not None and project.possession_date.year == 2031
    assert project.raw_data["detail"]["towers"] == 8
    assert project.raw_data["detail"]["inventory_parsed"] is True


async def test_the_filing_lands_in_the_profile_table(
    db_session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The project pages read this table, so the filing has to reach it.

    ``GET /projects/{slug}`` joins ``rera_project_profiles``. A filing kept only
    under ``raw_data.detail`` is fetched, stored and never shown, which is why
    this is asserted against a real database rather than a mocked session.
    """
    await _write_delhi(db_session, monkeypatch)

    profile = (
        await db_session.execute(
            select(ReraProjectProfile)
            .join(ReraProject, ReraProject.id == ReraProjectProfile.rera_project_id)
            .where(ReraProject.rera_number == DELHI_RERA_NUMBER)
        )
    ).scalar_one()
    assert profile.towers == 8
    assert profile.total_units == 78
    assert profile.land_area_sqm is not None
    assert profile.proposed_completion_date is not None
    assert profile.proposed_completion_date.year == 2031
    # 78 units over the filing's own land area.
    assert profile.units_per_acre is not None
    assert profile.source_document_id is not None


async def test_no_cost_row_is_written_from_the_delhi_filing(
    db_session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Delhi's cost field is not credible as rupees, so it is not published.

    The same field states ``1.00`` on 92 of the 120 projects that carry a value,
    and ``249885954900000.00`` on the largest, so a per-row figure cannot be
    trusted. The number stays in ``raw_data.detail``; the cost table stays empty.
    """
    await _write_delhi(db_session, monkeypatch)

    costs = await db_session.execute(
        select(func.count(ReraProjectCost.id))
        .join(ReraProject, ReraProject.id == ReraProjectCost.rera_project_id)
        .where(ReraProject.rera_number == DELHI_RERA_NUMBER)
    )
    assert costs.scalar_one() == 0
    # The register's own figure is still recorded verbatim for a future reader.
    project = await _delhi_row(db_session)
    assert project.raw_data["detail"]["project_cost_inr"] is not None


async def test_a_rescan_updates_the_profile_instead_of_duplicating_it(
    db_session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The profile is 1:1 with the project, so a re-read must not add a second row."""
    await _write_delhi(db_session, monkeypatch)

    await _write_delhi(db_session, monkeypatch)

    profiles = await db_session.execute(
        select(func.count(ReraProjectProfile.id))
        .join(ReraProject, ReraProject.id == ReraProjectProfile.rera_project_id)
        .where(ReraProject.rera_number == DELHI_RERA_NUMBER)
    )
    assert profiles.scalar_one() == 1


async def test_no_delhi_row_carries_the_hrera_index_key(
    db_session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The partial unique index is NULL on a Delhi row, so it cannot constrain one.

    This is the mechanism, not the symptom: the index is built on
    ``raw_data ->> 'portal_project_id'``, and a NULL key is not indexed, so no
    HRERA write can match this row through it.
    """
    await _write_delhi(db_session, monkeypatch)

    expression = await db_session.execute(
        text(
            "SELECT raw_data ->> 'portal_project_id' FROM rera_projects "
            "WHERE rera_number = :number"
        ),
        {"number": DELHI_RERA_NUMBER},
    )

    assert expression.scalar_one() is None


async def test_a_delhi_project_and_an_hrera_project_survive_the_same_numeric_id(
    db_session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The collision this scraper is designed around, stored and checked.

    Both portals address projects by a bare integer. Delhi's 10143 is Bharat
    Business Park; HRERA's 10143 would be some other project entirely. If Delhi
    wrote ``raw_data.portal_project_id = "10143"`` the HRERA upsert below would
    land on the Delhi row and overwrite it, and this test would find one row
    instead of two.
    """
    await _write_delhi(db_session, monkeypatch)

    hrera = await _hrera_record()
    stats = await ReraPortalIdScanner(start_id=1, end_id=1)._upsert(db_session, [hrera])
    await db_session.flush()

    assert stats == {"found": 1, "upserted": 1, "failed": 0}
    count = await db_session.execute(
        select(func.count(ReraProject.id)).where(
            ReraProject.rera_number.in_([DELHI_RERA_NUMBER, HRERA_FILING_NUMBER])
        )
    )
    assert count.scalar_one() == 2

    delhi = await _delhi_row(db_session)
    # The Delhi row is untouched: same district, same registration number, same
    # portal id, and still no HRERA key.
    assert delhi.district == "South West Delhi"
    assert delhi.project_name == "Bharat Business Park"
    assert delhi.raw_data["delhi_project_id"] == COLLIDING_ID
    assert "portal_project_id" not in delhi.raw_data

    hrera_row = (
        await db_session.execute(
            select(ReraProject).where(ReraProject.rera_number == HRERA_FILING_NUMBER)
        )
    ).scalar_one()
    assert hrera_row.raw_data["portal_project_id"] == COLLIDING_ID
    assert hrera_row.district == "Gurugram"


async def test_rescanning_the_register_does_not_duplicate_a_project(
    db_session, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = await _write_delhi(db_session, monkeypatch)

    second = await _write_delhi(db_session, monkeypatch)

    assert first["upserted"] == second["upserted"] == 17
    count = await db_session.execute(
        select(func.count(ReraProject.id)).where(
            ReraProject.rera_number.like("DLRERA%")
        )
    )
    assert count.scalar_one() == 17


async def test_a_rescan_refreshes_the_register_facts_and_leaves_the_url_alone(
    db_session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The register owns its facts; the published slug is not one of them."""
    await _write_delhi(db_session, monkeypatch)
    project = await _delhi_row(db_session)
    project.project_type = "stale"
    project.district = "Wrong Delhi"
    project.slug = "bharat-business-park"
    await db_session.flush()

    await _write_delhi(db_session, monkeypatch)

    # Read the columns, not the entity. The rescan writes through a Core upsert,
    # which the ORM's identity map does not see, so an entity read would return
    # the object mutated above and the assertions would hold whatever the row
    # now says — the test would pass even if the rescan updated nothing.
    after = (
        await db_session.execute(
            select(ReraProject.project_type, ReraProject.district, ReraProject.slug).where(
                ReraProject.rera_number == DELHI_RERA_NUMBER
            )
        )
    ).one()
    assert after.project_type == "Commercial"
    assert after.district == "South West Delhi"
    # Rewriting a published URL key would break every existing link to it.
    assert after.slug == "bharat-business-park"


async def test_the_flag_blocks_the_write(db_session, monkeypatch: pytest.MonkeyPatch) -> None:
    records = await _delhi_records(monkeypatch)
    monkeypatch.setattr(settings, "HRERA_DATA_ENABLED", False)

    stats = await DelhiReraProjectScraper()._upsert(db_session, records)

    assert stats == {"found": 0, "upserted": 0, "failed": 0}
    count = await db_session.execute(
        select(func.count(ReraProject.id)).where(ReraProject.rera_number.like("DLRERA%"))
    )
    assert count.scalar_one() == 0


def test_the_fixture_holds_the_register_the_parser_reads() -> None:
    """A guard on the fixture itself: the live register is 133 rows, the trim is 17."""
    parsed = parse_registered_projects_html(DELHI_REGISTER.read_text(encoding="utf-8"))

    assert parsed.errors == []
    assert len(parsed.records) == 17
    assert COLLIDING_ID in {r["raw_data"]["delhi_project_id"] for r in parsed.records}
