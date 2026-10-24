from contextlib import asynccontextmanager
from datetime import UTC, date, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.config import settings
from app.schemas.data_hub import ReraVerifyResult
from app.services.content import digest, facts
from app.services.data_hub import provenance
from app.services.data_hub.rera_complaints import ReraComplaintScraper
from app.services.data_hub.rera_projects import ReraProjectScraper
from app.services.data_hub_scheduler import _run_daily_scrapers, _run_weekly_scrapers


def _source(source_key: str, checked_at: datetime) -> dict:
    return {
        "source_key": source_key,
        "authority": "Haryana Real Estate Regulatory Authority",
        "title": "HRERA registry page",
        "canonical_url": f"https://hrera.haryana.gov.in/{source_key}",
        "source_record_id": None,
        "jurisdiction": "Gurugram, Haryana, India",
        "document_type": "registry_page",
        "language": "en",
        "fetched_at": checked_at,
        "checked_at": checked_at,
        "content_sha256": "a" * 64,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("scraper_type", [ReraProjectScraper, ReraComplaintScraper])
async def test_disabled_hrera_scraper_stops_before_run_creation(
    scraper_type, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "HRERA_DATA_ENABLED", False, raising=False)
    monkeypatch.setattr(
        "app.services.data_hub.base_scraper.get_bg_session_factory",
        MagicMock(side_effect=AssertionError("run creation must not happen")),
    )
    scraper = scraper_type()
    scraper._scrape = AsyncMock(side_effect=AssertionError("source fetch must not happen"))

    result = await scraper.run(run_type="manual")

    assert result["status"] == "disabled"
    scraper._scrape.assert_not_awaited()


@pytest.mark.asyncio
async def test_weekly_scheduler_omits_hrera_scrapers_when_disabled(monkeypatch) -> None:
    monkeypatch.setattr(settings, "HRERA_DATA_ENABLED", False, raising=False)
    names: list[str] = []

    async def capture(scraper):
        names.append(scraper.name)

    monkeypatch.setattr("app.services.data_hub_scheduler._run_scraper_limited", capture)

    await _run_weekly_scrapers()

    assert "rera_projects" not in names
    assert "rera_complaints" not in names
    # A derived job must not run when its source is switched off, or it would
    # publish a reading of a register the operator asked not to publish.
    assert "micro_market" not in names
    assert "developer_dossier" not in names
    assert "bank_rates" in names


@pytest.mark.asyncio
async def test_weekly_scheduler_refreshes_filings_but_never_the_gated_search(
    monkeypatch,
) -> None:
    """The list scrape cannot pass HRERA's CAPTCHA, so scheduling it is pointless.

    A weekly run that always failed would train operators to ignore failures. The
    filing detail scrape stays, because it refreshes projects the portal-id scanner
    has already found.
    """
    monkeypatch.setattr(settings, "HRERA_DATA_ENABLED", True, raising=False)
    names: list[str] = []

    async def capture(scraper):
        names.append(scraper.name)

    monkeypatch.setattr("app.services.data_hub_scheduler._run_scraper_limited", capture)

    await _run_weekly_scrapers()

    assert "rera_project_detail" in names
    assert "rera_complaints" in names
    # Both read what the filing refresh writes.
    assert "rera_price_history" in names
    assert "developer_dossier" in names
    # Micro-markets are derived from the location text the filings carry, so they
    # are a reading of the register too — and without this job the micro-market
    # list endpoint stays empty and every micro-market page 404s.
    assert "micro_market" in names
    assert "watchlist_alerts" in names
    assert "rera_projects" not in names
    # The portal-id walk is operator-triggered only; it must never be scheduled.
    assert "rera_portal_scan" not in names


@pytest.mark.asyncio
async def test_market_pulse_runs_daily_and_only_when_hrera_is_on(monkeypatch) -> None:
    """A snapshot is keyed by day, so it cannot wait for the weekly batch."""
    monkeypatch.setattr(settings, "HRERA_DATA_ENABLED", True, raising=False)
    names: list[str] = []

    async def capture(scraper):
        names.append(scraper.name)

    monkeypatch.setattr("app.services.data_hub_scheduler._run_scraper_limited", capture)

    await _run_daily_scrapers()

    assert "market_pulse" in names
    assert "bank_auctions" in names

    monkeypatch.setattr(settings, "HRERA_DATA_ENABLED", False, raising=False)
    names.clear()

    await _run_daily_scrapers()

    assert "market_pulse" not in names
    assert "bank_auctions" in names


def _query_result(*, one=None, scalar=None, all_rows=None, scalar_rows=None):
    result = MagicMock()
    result.one.return_value = one
    result.scalar.return_value = scalar
    result.all.return_value = all_rows or []
    result.scalars.return_value.all.return_value = scalar_rows or []
    return result


@pytest.mark.asyncio
async def test_locality_fact_sheet_does_not_query_or_emit_hrera_facts_by_default(
    monkeypatch,
) -> None:
    monkeypatch.setattr(settings, "HRERA_DATA_ENABLED", False, raising=False)
    db = MagicMock()
    db.execute = AsyncMock(
        side_effect=[
            _query_result(one=(0, None, None, None)),
            _query_result(one=(0, None, None, None)),
            _query_result(one=(0, None)),
            _query_result(scalar_rows=[]),
            _query_result(scalar=None),
            _query_result(all_rows=[]),
            _query_result(one=(0, None, None)),
        ]
    )
    locality = SimpleNamespace(
        slug="sector-56",
        name="Sector 56",
        city="Gurugram",
        place_type="sector",
        aliases=[],
        landmarks=[],
    )

    sheet = await facts.build_locality_sheet(db, locality, today=date(2026, 10, 23))

    statements = [str(call.args[0]).lower() for call in db.execute.await_args_list]
    assert not any("rera_projects" in statement for statement in statements)
    assert not any(f.source == "HRERA registry" for f in sheet.facts)


@pytest.mark.asyncio
async def test_market_digest_is_disabled_before_queries_or_model_calls(monkeypatch) -> None:
    monkeypatch.setattr(settings, "HRERA_DATA_ENABLED", False, raising=False)
    db = AsyncMock()
    provider = SimpleNamespace(calls=[])

    result = await digest.generate_market_digest(
        db, provider, today=date(2026, 10, 23)
    )

    assert result["status"] == "disabled"
    db.execute.assert_not_awaited()
    assert provider.calls == []


def test_market_digest_auto_publish_defaults_off() -> None:
    assert settings.MARKET_DIGEST_AUTO_PUBLISH is False


def test_hrera_access_defaults_on() -> None:
    """HRERA surfaces ship enabled; operators turn them off with the env var."""
    assert settings.HRERA_DATA_ENABLED is True


@pytest.mark.asyncio
async def test_hrera_endpoints_return_503_when_turned_off(monkeypatch) -> None:
    """The off-switch still gates every HRERA endpoint."""
    from fastapi import HTTPException

    from app.api.api_v1.endpoints.data_hub import rera as rera_endpoints

    monkeypatch.setattr(settings, "HRERA_DATA_ENABLED", False, raising=False)
    with pytest.raises(HTTPException) as excinfo:
        rera_endpoints._require_hrera_enabled()
    assert excinfo.value.status_code == 503
    assert excinfo.value.detail["code"] == "HRERA_DISABLED"


@pytest.mark.asyncio
async def test_provenance_maps_checked_time_by_source_key(monkeypatch) -> None:
    monkeypatch.setattr(settings, "HRERA_DATA_ENABLED", True)
    first_checked = datetime(2026, 10, 22, tzinfo=UTC)
    second_checked = datetime(2026, 10, 23, tzinfo=UTC)
    first_entity = SimpleNamespace(
        id=1,
        rera_number="HRERA-1",
        project_name="First",
        last_checked_at=None,
        **{
            field: None
            for field in provenance.RERA_FIELDS
            if field not in {"rera_number", "project_name"}
        },
    )
    second_entity = SimpleNamespace(
        id=2,
        rera_number="HRERA-2",
        project_name="Second",
        last_checked_at=None,
        **{
            field: None
            for field in provenance.RERA_FIELDS
            if field not in {"rera_number", "project_name"}
        },
    )

    @asynccontextmanager
    async def nested():
        yield

    def result(value):
        row = MagicMock()
        row.scalar_one_or_none.return_value = value
        return row

    db = MagicMock()
    db.begin_nested = MagicMock(side_effect=lambda: nested())
    db.execute = AsyncMock(
        side_effect=[
            result(101),
            result(102),
            result(first_entity),
            result(second_entity),
        ]
    )
    db.add = MagicMock()
    db.flush = AsyncMock()
    monkeypatch.setattr(
        provenance, "record_entity_revision", AsyncMock(return_value=None)
    )

    errors = await provenance.persist_scrape_provenance(
        db,
        scraper_name="rera_projects",
        run_id=50,
        records=[
            {"rera_number": "HRERA-1", "project_name": "First", "_source_key": "first"},
            {"rera_number": "HRERA-2", "project_name": "Second", "_source_key": "second"},
        ],
        source_documents=[
            _source("first", first_checked),
            _source("second", second_checked),
        ],
        run_succeeded=False,
    )

    assert errors == []
    assert first_entity.last_checked_at == first_checked
    assert second_entity.last_checked_at == second_checked


def test_rera_project_evidence_excludes_complaint_count() -> None:
    assert "complaint_count" not in provenance.RERA_FIELDS
    assertion_constraint = next(
        constraint
        for constraint in provenance.DataHubEvidenceAssertion.__table__.constraints
        if constraint.name == "ck_data_hub_assertions_field_path"
    )
    revision_constraint = next(
        constraint
        for constraint in provenance.DataHubEntityRevision.__table__.constraints
        if constraint.name == "ck_data_hub_revisions_snapshot_allowlist"
    )
    assert "complaint_count" not in str(assertion_constraint.sqltext)
    assert "complaint_count" not in str(revision_constraint.sqltext)


def test_rera_number_verification_requires_accepted_reviewed_authoritative_evidence() -> None:
    matching = {
        "field_path": "rera_project.rera_number",
        "normalized_value": "HRERA-1",
        "status": "accepted",
        "reviewer_id": 7,
        "authority": "Haryana Real Estate Regulatory Authority",
        "expected_value": "HRERA-1",
    }

    assert provenance.is_accepted_rera_number_assertion(**matching)
    for rejected in (
        {**matching, "status": "unreviewed"},
        {**matching, "reviewer_id": None},
        {**matching, "field_path": "rera_project.project_name"},
        {**matching, "normalized_value": "HRERA-2"},
        {**matching, "authority": "Unknown"},
    ):
        assert not provenance.is_accepted_rera_number_assertion(**rejected)


def test_rera_verify_result_defaults_to_unknown_not_invalid() -> None:
    result = ReraVerifyResult(
        valid=None,
        verification_status="unknown",
    )

    assert result.valid is None
    assert result.verification_status == "unknown"


def test_public_provenance_summary_exposes_only_safe_source_metadata() -> None:
    checked_at = datetime(2026, 10, 23, tzinfo=UTC)
    summary = provenance.build_public_provenance_summary(
        source_documents=[
            {
                "id": 1,
                "authority": "HRERA",
                "canonical_url": "https://hrera.example/project/1",
                "reuse_terms": "citation_permitted",
                "effective_from": date(2026, 1, 1),
                "effective_to": None,
                "checked_at": checked_at,
                "artifact_reference": "restricted://private",
                "reviewer_notes": "internal",
            },
            {
                "id": 2,
                "authority": "Unknown",
                "canonical_url": "https://source.example/2",
                "reuse_terms": None,
                "effective_from": None,
                "effective_to": None,
                "checked_at": checked_at,
            },
        ]
    )

    assert summary.verification_status == "unverified"
    assert summary.model_dump() == {
        "verification_status": "unverified",
        "sources": [
            {
                "authority": "HRERA",
                "citation_url": "https://hrera.example/project/1",
                "effective_from": date(2026, 1, 1),
                "effective_to": None,
                "checked_at": checked_at,
            },
            {
                "authority": "Unknown",
                "citation_url": None,
                "effective_from": None,
                "effective_to": None,
                "checked_at": checked_at,
            },
        ],
    }
