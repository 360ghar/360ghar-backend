from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import BigInteger, CheckConstraint
from sqlalchemy.dialects import postgresql

from app.config import settings
from app.models.data_hub import (
    ColonyApproval,
    DataHubEntityRevision,
    DataHubEvidenceAssertion,
    ReraProject,
    SourceDocument,
    ZoningData,
)
from app.schemas.data_hub import (
    ColonyApprovalResponse,
    DataHubProvenanceSummary,
    ReraProjectResponse,
    ZoningDataResponse,
)
from app.services.data_hub import base_scraper
from app.services.data_hub.base_scraper import (
    ScrapeResult,
    final_run_status,
    successful_provenance_records,
)
from app.services.data_hub.provenance import (
    _get_or_create_source_document,
    build_public_provenance_summary,
    get_public_provenance_summaries,
    record_entity_revision,
    reuse_terms_permit_citation,
    revision_delta,
    snapshot_sha256,
)
from app.services.data_hub.rera_projects import ReraProjectScraper
from app.services.data_hub.zoning import ZoningScraper


def test_revision_delta_skips_noop_but_reports_changed_fields() -> None:
    current = {"status": "registered", "total_units": 120}

    assert revision_delta(current, current) is None
    assert revision_delta(current, {"status": "completed", "total_units": 120}) == (
        {"status"},
        ["status"],
    )


def test_changed_snapshot_hash_is_deterministic() -> None:
    assert snapshot_sha256({"z": 1, "a": "two"}) == snapshot_sha256(
        {"a": "two", "z": 1}
    )
    assert len(snapshot_sha256({"status": "registered"})) == 64


@pytest.mark.asyncio
async def test_noop_revision_does_not_insert_another_row() -> None:
    target_result = MagicMock()
    target_result.scalar_one_or_none.return_value = 11
    latest_result = MagicMock()
    latest_result.scalar_one_or_none.return_value = SimpleNamespace(
        normalized_snapshot={"status": "registered"},
        revision_number=3,
    )
    db = MagicMock()
    db.execute = AsyncMock(side_effect=[target_result, latest_result])
    db.add = MagicMock()
    db.flush = AsyncMock()

    revision = await record_entity_revision(
        db,
        entity_type="rera_project",
        entity_id=11,
        snapshot={"status": "registered"},
        source_run_id=9,
        source_document_id=21,
    )

    assert revision is None
    db.add.assert_not_called()
    db.flush.assert_not_awaited()


@pytest.mark.asyncio
async def test_changed_snapshot_increments_revision_and_lists_changed_fields() -> None:
    target_result = MagicMock()
    target_result.scalar_one_or_none.return_value = 11
    latest_result = MagicMock()
    latest_result.scalar_one_or_none.return_value = SimpleNamespace(
        normalized_snapshot={"status": "registered"},
        revision_number=3,
    )
    db = MagicMock()
    db.execute = AsyncMock(side_effect=[target_result, latest_result])
    db.add = MagicMock()
    db.flush = AsyncMock()

    revision = await record_entity_revision(
        db,
        entity_type="rera_project",
        entity_id=11,
        snapshot={"status": "completed"},
        source_run_id=10,
        source_document_id=22,
    )

    assert revision is not None
    assert revision.revision_number == 4
    assert revision.changed_fields == ["status"]
    assert revision.snapshot_sha256 == snapshot_sha256({"status": "completed"})
    db.add.assert_called_once_with(revision)
    db.flush.assert_awaited_once()


def test_scrape_result_preserves_complete_partial_and_failed_outcomes() -> None:
    assert ScrapeResult(successful_sources=1).status == "success"
    assert (
        ScrapeResult(successful_sources=1, errors=[{"stage": "parse"}]).status
        == "partial"
    )
    assert ScrapeResult(errors=[{"stage": "fetch"}]).status == "failed"
    assert final_run_status(
        ScrapeResult(successful_sources=1),
        {"found": 2, "upserted": 2, "failed": 0},
    ) == "success"
    assert final_run_status(
        ScrapeResult(successful_sources=1, errors=[{"stage": "parse"}]),
        {"found": 1, "upserted": 1, "failed": 0},
    ) == "partial"
    assert final_run_status(
        ScrapeResult(errors=[{"stage": "fetch"}]),
        {"found": 0, "upserted": 0, "failed": 0},
    ) == "failed"
    assert final_run_status(
        ScrapeResult(successful_sources=1),
        {"found": 2, "upserted": 0, "failed": 2},
    ) == "failed"


def test_provenance_skips_rows_that_failed_the_entity_upsert() -> None:
    checked_at = datetime(2026, 10, 23, tzinfo=UTC)
    assert successful_provenance_records(
        [
            {
                "rera_number": "HRERA-1",
                "_upsert_succeeded": True,
                "_source_checked_at": checked_at,
            },
            {"rera_number": "HRERA-2", "_upsert_succeeded": False},
        ]
    ) == [{"rera_number": "HRERA-1"}]


def test_source_check_time_is_attached_to_the_matching_record() -> None:
    attach = getattr(base_scraper, "attach_source_checked_at", None)
    assert callable(attach)
    checked_at = datetime(2026, 10, 23, tzinfo=UTC)
    records = [
        {"rera_number": "HRERA-1", "_source_key": "source-a"},
        {"rera_number": "HRERA-2", "_source_key": "missing"},
    ]

    attach(
        records,
        [{"source_key": "source-a", "checked_at": checked_at}],
    )

    assert records == [
        {
            "rera_number": "HRERA-1",
            "_source_key": "source-a",
            "_source_checked_at": checked_at,
        },
        {"rera_number": "HRERA-2", "_source_key": "missing"},
    ]


@pytest.mark.asyncio
async def test_rera_upsert_skips_a_stale_source_snapshot(monkeypatch) -> None:
    monkeypatch.setattr(settings, "HRERA_DATA_ENABLED", True)

    @asynccontextmanager
    async def savepoint():
        yield

    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    db = MagicMock()
    db.begin_nested = MagicMock(side_effect=lambda: savepoint())
    db.execute = AsyncMock(return_value=result)
    checked_at = datetime(2026, 10, 22, tzinfo=UTC)
    records = [
        {
            "rera_number": "HRERA-1",
            "project_name": "Older snapshot",
            "_source_checked_at": checked_at,
        }
    ]

    stats = await ReraProjectScraper()._upsert(db, records)

    statement = db.execute.await_args.args[0]
    sql = str(statement.compile(dialect=postgresql.dialect())).lower()
    assert stats == {"found": 1, "upserted": 0, "failed": 0}
    assert records[0]["_upsert_succeeded"] is False
    assert "rera_projects.last_checked_at" in sql


@pytest.mark.asyncio
async def test_zoning_upsert_skips_a_stale_source_snapshot() -> None:
    @asynccontextmanager
    async def savepoint():
        yield

    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    db = MagicMock()
    db.begin_nested = MagicMock(side_effect=lambda: savepoint())
    db.execute = AsyncMock(return_value=result)
    checked_at = datetime(2026, 10, 22, tzinfo=UTC)
    records = [
        {
            "sector": "Sector 1",
            "slug": "sector-1-residential",
            "land_use": "residential",
            "_source_checked_at": checked_at,
        }
    ]

    stats = await ZoningScraper()._upsert(db, records)

    statement = db.execute.await_args.args[0]
    sql = str(statement.compile(dialect=postgresql.dialect())).lower()
    assert stats == {"found": 1, "upserted": 0, "failed": 0}
    assert records[0]["_upsert_succeeded"] is False
    assert "zoning_data.last_checked_at" in sql


@pytest.mark.asyncio
async def test_colony_approval_upsert_skips_a_stale_source_snapshot() -> None:
    @asynccontextmanager
    async def savepoint():
        yield

    checked_at = datetime(2026, 10, 22, tzinfo=UTC)
    current = SimpleNamespace(
        id=11,
        colony_name="Example Colony",
        licence_number="LIC-1",
        developer_name="Current value",
        last_checked_at=datetime(2026, 10, 23, tzinfo=UTC),
    )
    result = MagicMock()
    result.scalar_one_or_none.return_value = current
    db = MagicMock()
    db.begin_nested = MagicMock(side_effect=lambda: savepoint())
    db.execute = AsyncMock(return_value=result)
    db.flush = AsyncMock()
    records = [
        {
            "_table": "colony_approvals",
            "colony_name": "Example Colony",
            "licence_number": "LIC-1",
            "developer_name": "Older value",
            "_source_checked_at": checked_at,
        }
    ]

    stats = await ZoningScraper()._upsert(db, records)

    assert stats == {"found": 1, "upserted": 0, "failed": 0}
    assert records[0]["_upsert_succeeded"] is False
    assert current.developer_name == "Current value"


@pytest.mark.asyncio
async def test_zoning_run_reports_partial_when_one_page_fetch_fails(monkeypatch) -> None:
    html = (
        "<table><tr><th>Sector</th><th>Land Use</th></tr>"
        "<tr><td>Sector 1</td><td>Residential</td></tr></table>"
    )
    scraper = ZoningScraper()
    scraper._fetch_url = AsyncMock(side_effect=[RuntimeError("TCP unavailable"), html])
    monkeypatch.setattr(
        "app.services.data_hub.zoning.asyncio.sleep", AsyncMock()
    )

    result = await scraper._scrape()

    assert result.status == "partial"
    assert [entry["status"] for entry in result.source_coverage] == ["failed", "success"]
    assert result.errors[0]["stage"] == "fetch"
    assert len(result.records) == 1
    assert len(result.source_documents) == 1
    assert "content_sha256" in result.source_documents[0]
    assert "html" not in result.source_documents[0]


@pytest.mark.asyncio
async def test_rera_record_failure_uses_savepoint_without_losing_other_rows(
    monkeypatch,
) -> None:
    monkeypatch.setattr(settings, "HRERA_DATA_ENABLED", True)
    @asynccontextmanager
    async def savepoint():
        yield

    first = MagicMock()
    first.scalar_one_or_none.return_value = 1
    third = MagicMock()
    third.scalar_one_or_none.return_value = 3
    db = MagicMock()
    db.begin_nested = MagicMock(side_effect=lambda: savepoint())
    db.execute = AsyncMock(
        side_effect=[first, RuntimeError("invalid record"), third]
    )
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    checked_at = datetime(2026, 10, 23, tzinfo=UTC)
    records = [
        {
            "rera_number": "HRERA-1",
            "project_name": "First",
            "_source_checked_at": checked_at,
        },
        {
            "rera_number": "HRERA-2",
            "project_name": "Bad",
            "_source_checked_at": checked_at,
        },
        {
            "rera_number": "HRERA-3",
            "project_name": "Third",
            "_source_checked_at": checked_at,
        },
    ]

    stats = await ReraProjectScraper()._upsert(db, records)

    assert stats == {"found": 3, "upserted": 2, "failed": 1}
    assert [record["_upsert_succeeded"] for record in records] == [True, False, True]
    assert db.begin_nested.call_count == 3
    db.rollback.assert_not_awaited()
    db.commit.assert_not_awaited()


def test_source_documents_require_locator_and_hash_at_database_layer() -> None:
    checks = {
        constraint.name: str(constraint.sqltext)
        for constraint in SourceDocument.__table__.constraints
        if isinstance(constraint, CheckConstraint)
    }
    assert "canonical_url" in checks["ck_source_documents_has_locator"]
    assert "source_record_id" in checks["ck_source_documents_has_locator"]
    assert "BTRIM" in checks["ck_source_documents_has_locator"]
    assert "content_sha256" in checks["ck_source_documents_sha256"]
    assert not {"source_html", "pdf_text", "source_text", "content"} & set(
        SourceDocument.__table__.columns.keys()
    )


def test_migration_is_additive_private_and_does_not_backfill_old_rows() -> None:
    migration = (
        Path(__file__).resolve().parents[3]
        / "supabase/migrations/20261023000000_data_hub_provenance.sql"
    ).read_text()

    assert "ADD COLUMN IF NOT EXISTS last_checked_at TIMESTAMPTZ" in migration
    assert "ADD COLUMN IF NOT EXISTS last_successful_run_id INTEGER" in migration
    assert "UPDATE rera_projects" not in migration
    assert "UPDATE zoning_data" not in migration
    assert "UPDATE colony_approvals" not in migration
    assert "rera_project.complaint_count" not in migration
    assert migration.count("num_nonnulls(rera_project_id, zoning_data_id, colony_approval_id) = 1") == 2
    assert "data_hub_entity_revisions_immutable" in migration
    assert "ALTER TABLE data_hub_evidence_assertions ENABLE ROW LEVEL SECURITY" in migration


def test_existing_entities_remain_unknown_until_checked() -> None:
    for model in (ReraProject, ZoningData, ColonyApproval):
        assert model.__table__.c.last_checked_at.nullable is True
        assert model.__table__.c.last_successful_run_id.nullable is True
        assert {
            foreign_key.target_fullname
            for foreign_key in model.__table__.c.last_successful_run_id.foreign_keys
        } == {"scraper_runs.id"}
    for schema in (ReraProjectResponse, ZoningDataResponse, ColonyApprovalResponse):
        assert "provenance" in schema.model_fields
    assert set(DataHubProvenanceSummary.model_fields) == {
        "verification_status",
        "sources",
    }


def test_assertions_and_revisions_enforce_one_typed_foreign_key_and_allowlists() -> None:
    target_fks = {
        "rera_projects.id",
        "zoning_data.id",
        "colony_approvals.id",
    }
    for model in (DataHubEvidenceAssertion, DataHubEntityRevision):
        typed_target_fks = {
            foreign_key.target_fullname
            for column in model.__table__.columns
            for foreign_key in column.foreign_keys
            if foreign_key.target_fullname in target_fks
        }
        assert typed_target_fks == target_fks
        checks = {
            constraint.name: str(constraint.sqltext)
            for constraint in model.__table__.constraints
            if isinstance(constraint, CheckConstraint)
        }
        assert "num_nonnulls" in checks[
            "ck_data_hub_assertions_exactly_one_target"
            if model is DataHubEvidenceAssertion
            else "ck_data_hub_revisions_exactly_one_target"
        ]
    reviewer_fk = DataHubEvidenceAssertion.__table__.c.reviewer_id
    assert isinstance(reviewer_fk.type, BigInteger)
    assert {foreign_key.target_fullname for foreign_key in reviewer_fk.foreign_keys} == {
        "users.id"
    }
    assert any(
        constraint.name == "ck_data_hub_assertions_status"
        for constraint in DataHubEvidenceAssertion.__table__.constraints
    )
    assert any(
        constraint.name == "ck_data_hub_assertions_field_path"
        for constraint in DataHubEvidenceAssertion.__table__.constraints
    )
    assert any(
        constraint.name == "ck_data_hub_assertions_method"
        for constraint in DataHubEvidenceAssertion.__table__.constraints
    )
    assert any(
        constraint.name == "ck_data_hub_revisions_snapshot_allowlist"
        for constraint in DataHubEntityRevision.__table__.constraints
    )


def test_public_summary_exposes_only_safe_freshness_and_permitted_citations() -> None:
    checked_at = datetime(2026, 10, 23, tzinfo=UTC)
    summary = build_public_provenance_summary(
        source_documents=[
            {
                "authority": "A Authority",
                "canonical_url": "https://authority.example/record",
                "reuse_terms": "citation_permitted",
                "effective_from": None,
                "effective_to": None,
                "checked_at": checked_at,
                "artifact_reference": "private://restricted/file.pdf",
            },
            {
                "authority": "B Authority",
                "canonical_url": "https://authority.example/other",
                "reuse_terms": "unknown",
                "effective_from": None,
                "effective_to": None,
                "checked_at": checked_at,
            },
            {
                "authority": "C Authority",
                "canonical_url": "javascript:alert(1)",
                "reuse_terms": "citation permitted",
                "effective_from": None,
                "effective_to": None,
                "checked_at": checked_at,
            },
        ],
    )

    assert summary == DataHubProvenanceSummary(
        verification_status="unverified",
        sources=[
            {
                "authority": "A Authority",
                "citation_url": "https://authority.example/record",
                "effective_from": None,
                "effective_to": None,
                "checked_at": checked_at,
            },
            {
                "authority": "B Authority",
                "citation_url": None,
                "effective_from": None,
                "effective_to": None,
                "checked_at": checked_at,
            },
            {
                "authority": "C Authority",
                "citation_url": None,
                "effective_from": None,
                "effective_to": None,
                "checked_at": checked_at,
            },
        ],
    )
    assert "artifact_reference" not in summary.model_fields
    assert reuse_terms_permit_citation("unknown") is False
    assert reuse_terms_permit_citation("citation_permitted") is True


@pytest.mark.asyncio
async def test_public_provenance_uses_latest_successful_run_after_noop_revision() -> None:
    checked_at = datetime(2026, 10, 24, tzinfo=UTC)
    previous_revision = SimpleNamespace(
        rera_project_id=7, source_run_id=9, revision_number=1
    )
    revision_result = MagicMock()
    revision_result.scalars.return_value.all.return_value = [previous_revision]
    evidence_result = MagicMock()
    evidence_result.all.return_value = [
        (
            7,
            11,
            21,
            "Haryana Real Estate Regulatory Authority",
            "https://authority.example/record",
            "citation_permitted",
            None,
            None,
            checked_at,
        )
    ]
    accepted_result = MagicMock()
    accepted_result.all.return_value = []

    async def execute_for_query(statement):
        sql = str(statement).lower()
        if "from data_hub_entity_revisions" in sql:
            return revision_result
        if "source_run_id" in sql:
            return evidence_result
        return accepted_result

    db = MagicMock()
    db.execute = AsyncMock(side_effect=execute_for_query)
    entity = SimpleNamespace(
        id=7, rera_number="HRERA-7", last_successful_run_id=11
    )

    summaries = await get_public_provenance_summaries(
        db, "rera_project", [entity]
    )

    assert summaries[7].sources[0].checked_at == checked_at


@pytest.mark.asyncio
async def test_existing_source_document_refreshes_only_its_check_time() -> None:
    checked_at = datetime(2026, 10, 24, tzinfo=UTC)
    insert_result = MagicMock()
    insert_result.scalar_one_or_none.return_value = None
    existing_result = MagicMock()
    existing_result.scalar_one_or_none.return_value = 21
    db = MagicMock()
    db.execute = AsyncMock(
        side_effect=[insert_result, existing_result, MagicMock()]
    )

    document_id = await _get_or_create_source_document(
        db,
        {
            "authority": "Haryana Real Estate Regulatory Authority",
            "canonical_url": "https://authority.example/record",
            "content_sha256": "a" * 64,
            "checked_at": checked_at,
        },
    )

    assert document_id == 21
    assert db.execute.await_count == 3
    update = db.execute.await_args_list[2].args[0]
    compiled = update.compile(dialect=postgresql.dialect())
    assert "UPDATE SOURCE_DOCUMENTS" in str(compiled).upper()
    assert "GREATEST" in str(compiled).upper()
    assert checked_at in compiled.params.values()
    assert "reuse_terms" not in str(compiled).lower()
