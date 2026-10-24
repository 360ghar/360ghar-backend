"""Persistence and safe public summaries for Data Hub source provenance."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Literal, TypeVar
from urllib.parse import urlparse

from pydantic import BaseModel
from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.data_hub import (
    ColonyApproval,
    DataHubEntityRevision,
    DataHubEvidenceAssertion,
    ReraProject,
    SourceDocument,
    ZoningData,
)
from app.schemas.data_hub import DataHubProvenanceSource, DataHubProvenanceSummary

RERA_FIELDS = (
    "rera_number",
    "project_name",
    "developer_name",
    "location",
    "district",
    "total_units",
    "units_booked",
    "possession_date",
    "registration_date",
    "expiry_date",
    "status",
    "project_type",
    "total_area_sqm",
)
OFFICIAL_HRERA_AUTHORITY = "Haryana Real Estate Regulatory Authority"
ZONING_FIELDS = (
    "sector",
    "land_use",
    "far_limit",
    "max_height_m",
    "max_coverage_pct",
    "setback_front_m",
    "setback_rear_m",
    "master_plan_year",
    "notes",
)
COLONY_FIELDS = (
    "colony_name",
    "developer_name",
    "district",
    "licence_number",
    "approval_status",
    "clu_status",
    "approval_date",
    "area_acres",
    "sector",
)

ENTITY_TARGETS: dict[str, tuple[Any, str, tuple[str, ...]]] = {
    "rera_project": (ReraProject, "rera_project_id", RERA_FIELDS),
    "zoning_data": (ZoningData, "zoning_data_id", ZONING_FIELDS),
    "colony_approval": (ColonyApproval, "colony_approval_id", COLONY_FIELDS),
}
_UNITS = {
    "total_area_sqm": "sqm",
    "max_height_m": "m",
    "max_coverage_pct": "%",
    "setback_front_m": "m",
    "setback_rear_m": "m",
    "area_acres": "acres",
}
_RESPONSE_T = TypeVar("_RESPONSE_T", bound=BaseModel)


def _json_value(value: Any) -> Any:
    """Convert supported database values to deterministic JSON-safe values."""
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        integer = value.to_integral_value()
        return int(integer) if value == integer else float(value)
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return value


def _normalized_mapping(value: dict[str, Any]) -> dict[str, Any]:
    return {str(key): _json_value(item) for key, item in sorted(value.items())}


def revision_delta(
    previous_snapshot: dict[str, Any] | None, current_snapshot: dict[str, Any]
) -> tuple[set[str], list[str]] | None:
    """Return changed fields, or ``None`` when a normalized snapshot is unchanged."""
    current = _normalized_mapping(current_snapshot)
    previous = _normalized_mapping(previous_snapshot or {})
    changed = {
        key
        for key in previous.keys() | current.keys()
        if previous.get(key) != current.get(key)
    }
    if not changed:
        return None
    return changed, sorted(changed)


def snapshot_sha256(snapshot: dict[str, Any]) -> str:
    serialized = json.dumps(
        _normalized_mapping(snapshot),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


async def record_entity_revision(
    db: AsyncSession,
    *,
    entity_type: str,
    entity_id: int,
    snapshot: dict[str, Any],
    source_run_id: int | None,
    source_document_id: int | None,
) -> DataHubEntityRevision | None:
    """Insert a stable immutable revision only when the normalized snapshot changed."""
    model, target_field, allowed_fields = ENTITY_TARGETS[entity_type]
    target_column = getattr(DataHubEntityRevision, target_field)
    target = await db.execute(
        select(model.id).where(model.id == entity_id).with_for_update()
    )
    if target.scalar_one_or_none() is None:
        raise ValueError(f"{entity_type} entity {entity_id} does not exist")

    latest_result = await db.execute(
        select(DataHubEntityRevision)
        .where(target_column == entity_id)
        .order_by(DataHubEntityRevision.revision_number.desc())
        .limit(1)
    )
    latest = latest_result.scalar_one_or_none()
    normalized_snapshot = _normalized_mapping(
        {field: snapshot[field] for field in allowed_fields if field in snapshot}
    )
    delta = revision_delta(
        latest.normalized_snapshot if latest is not None else None, normalized_snapshot
    )
    if delta is None:
        return None

    revision = DataHubEntityRevision(
        **{target_field: entity_id},
        revision_number=(latest.revision_number + 1) if latest is not None else 1,
        normalized_snapshot=normalized_snapshot,
        snapshot_sha256=snapshot_sha256(normalized_snapshot),
        changed_fields=delta[1],
        source_run_id=source_run_id,
        source_document_id=source_document_id,
    )
    db.add(revision)
    await db.flush()
    return revision


def reuse_terms_permit_citation(reuse_terms: str | None) -> bool:
    """Require an explicit, machine-readable citation permission before returning a URL."""
    return isinstance(reuse_terms, str) and reuse_terms.strip().casefold() in {
        "citation permitted",
        "citation_permitted",
    }


def is_accepted_rera_number_assertion(
    *,
    field_path: str,
    normalized_value: Any,
    status: str,
    reviewer_id: int | None,
    authority: str,
    expected_value: str,
) -> bool:
    """Accept only a reviewer-approved exact RERA number from the official authority."""
    if (
        field_path != "rera_project.rera_number"
        or status != "accepted"
        or reviewer_id is None
        or authority.strip().casefold() != OFFICIAL_HRERA_AUTHORITY.casefold()
        or not isinstance(normalized_value, str)
    ):
        return False
    return normalized_value.strip().casefold() == expected_value.strip().casefold()


def build_public_provenance_summary(
    *,
    source_documents: list[dict[str, Any]],
    verification_status: Literal["unverified", "verified"] = "unverified",
) -> DataHubProvenanceSummary:
    sources: dict[tuple[Any, ...], dict[str, Any]] = {}
    for document in source_documents:
        authority = document.get("authority")
        checked_at = document.get("checked_at")
        if not isinstance(authority, str) or not isinstance(checked_at, datetime):
            continue
        canonical_url = document.get("canonical_url")
        citation_url = None
        if reuse_terms_permit_citation(document.get("reuse_terms")) and isinstance(
            canonical_url, str
        ):
            parsed_url = urlparse(canonical_url)
            if parsed_url.scheme in {"http", "https"} and parsed_url.netloc:
                citation_url = canonical_url
        source = {
            "authority": authority,
            "citation_url": citation_url,
            "effective_from": document.get("effective_from"),
            "effective_to": document.get("effective_to"),
            "checked_at": checked_at,
        }
        key = (
            source["authority"],
            source["citation_url"],
            source["effective_from"],
            source["effective_to"],
            source["checked_at"],
        )
        sources[key] = source
    ordered_sources = sorted(
        sources.values(),
        key=lambda item: (
            item["authority"].casefold(),
            item["citation_url"] or "",
            item["checked_at"],
        ),
    )
    return DataHubProvenanceSummary(
        verification_status=verification_status,
        sources=[
            DataHubProvenanceSource.model_validate(source) for source in ordered_sources
        ],
    )


async def get_public_provenance_summaries(
    db: AsyncSession, entity_type: str, entities: list[Any]
) -> dict[int, DataHubProvenanceSummary]:
    """Return explicitly safe source metadata and reviewer-backed verification status."""
    if not entities:
        return {}
    _, target_field, _ = ENTITY_TARGETS[entity_type]
    entity_ids = [entity.id for entity in entities]
    document_rows: dict[int, list[dict[str, Any]]] = defaultdict(list)
    latest_run_by_entity = {
        entity.id: entity.last_successful_run_id
        for entity in entities
        if getattr(entity, "last_successful_run_id", None) is not None
    }
    latest_run_ids = set(latest_run_by_entity.values())
    if latest_run_ids:
        assertion_target = getattr(DataHubEvidenceAssertion, target_field)
        evidence_result = await db.execute(
            select(
                assertion_target,
                DataHubEvidenceAssertion.source_run_id,
                SourceDocument.id,
                SourceDocument.authority,
                SourceDocument.canonical_url,
                SourceDocument.reuse_terms,
                SourceDocument.effective_from,
                SourceDocument.effective_to,
                SourceDocument.checked_at,
            )
            .join(
                SourceDocument,
                SourceDocument.id == DataHubEvidenceAssertion.source_document_id,
            )
            .where(
                assertion_target.in_(entity_ids),
                DataHubEvidenceAssertion.source_run_id.in_(latest_run_ids),
                DataHubEvidenceAssertion.status.in_(("unreviewed", "accepted")),
            )
        )
        for (
            target_id,
            run_id,
            document_id,
            authority,
            canonical_url,
            reuse_terms,
            effective_from,
            effective_to,
            checked_at,
        ) in (
            evidence_result.all()
        ):
            if latest_run_by_entity.get(target_id) == run_id:
                document_rows[target_id].append(
                    {
                        "id": document_id,
                        "authority": authority,
                        "canonical_url": canonical_url,
                        "reuse_terms": reuse_terms,
                        "effective_from": effective_from,
                        "effective_to": effective_to,
                        "checked_at": checked_at,
                    }
                )

    verified_entity_ids: set[int] = set()
    if entity_type == "rera_project":
        accepted_result = await db.execute(
            select(
                DataHubEvidenceAssertion.rera_project_id,
                DataHubEvidenceAssertion.field_path,
                DataHubEvidenceAssertion.normalized_value,
                DataHubEvidenceAssertion.status,
                DataHubEvidenceAssertion.reviewer_id,
                SourceDocument.id,
                SourceDocument.authority,
                SourceDocument.canonical_url,
                SourceDocument.reuse_terms,
                SourceDocument.effective_from,
                SourceDocument.effective_to,
                SourceDocument.checked_at,
            )
            .join(
                SourceDocument,
                SourceDocument.id == DataHubEvidenceAssertion.source_document_id,
            )
            .where(
                DataHubEvidenceAssertion.rera_project_id.in_(entity_ids),
                DataHubEvidenceAssertion.status == "accepted",
                DataHubEvidenceAssertion.reviewer_id.is_not(None),
            )
        )
        entities_by_id = {entity.id: entity for entity in entities}
        for (
            entity_id,
            field_path,
            normalized_value,
            status,
            reviewer_id,
            document_id,
            authority,
            canonical_url,
            reuse_terms,
            effective_from,
            effective_to,
            checked_at,
        ) in accepted_result.all():
            entity = entities_by_id.get(entity_id)
            if entity is not None and is_accepted_rera_number_assertion(
                field_path=field_path,
                normalized_value=normalized_value,
                status=status,
                reviewer_id=reviewer_id,
                authority=authority,
                expected_value=entity.rera_number,
            ):
                verified_entity_ids.add(entity_id)
                document_rows[entity_id].append(
                    {
                        "id": document_id,
                        "authority": authority,
                        "canonical_url": canonical_url,
                        "reuse_terms": reuse_terms,
                        "effective_from": effective_from,
                        "effective_to": effective_to,
                        "checked_at": checked_at,
                    }
                )

    summaries: dict[int, DataHubProvenanceSummary] = {}
    for entity in entities:
        summaries[entity.id] = build_public_provenance_summary(
            source_documents=document_rows.get(entity.id, []),
            verification_status=(
                "verified" if entity.id in verified_entity_ids else "unverified"
            ),
        )
    return summaries


async def serialize_with_provenance(
    db: AsyncSession,
    entity_type: str,
    entities: list[Any],
    response_schema: type[_RESPONSE_T],
) -> list[_RESPONSE_T]:
    summaries = await get_public_provenance_summaries(db, entity_type, entities)
    return [
        response_schema.model_validate(entity).model_copy(
            update={"provenance": summaries.get(entity.id)}
        )
        for entity in entities
    ]


async def get_or_create_source_document(
    db: AsyncSession, values: dict[str, Any]
) -> int:
    """Resolve a source document to its id, inserting it when it is new.

    Public so a scraper that writes detail rows can cite the document it read in
    the same transaction, instead of waiting for the provenance pass.
    """
    return await _get_or_create_source_document(db, values)


async def _get_or_create_source_document(
    db: AsyncSession, values: dict[str, Any]
) -> int:
    if not values.get("canonical_url") and not values.get("source_record_id"):
        raise ValueError("source document requires a canonical URL or source record ID")
    insert_result = await db.execute(
        pg_insert(SourceDocument).values(**values).on_conflict_do_nothing().returning(
            SourceDocument.id
        )
    )
    document_id = insert_result.scalar_one_or_none()
    if document_id is not None:
        return int(document_id)

    dedupe_conditions = [
        and_(
            SourceDocument.canonical_url == values["canonical_url"],
            SourceDocument.content_sha256 == values["content_sha256"],
        )
    ] if values.get("canonical_url") is not None else []
    if values.get("source_record_id") is not None:
        dedupe_conditions.append(
            and_(
                SourceDocument.authority == values["authority"],
                SourceDocument.source_record_id == values["source_record_id"],
                SourceDocument.content_sha256 == values["content_sha256"],
            )
        )
    result: Any = await db.execute(
        select(SourceDocument.id).where(or_(*dedupe_conditions)).limit(1)
    )
    document_id = result.scalar_one_or_none()
    if document_id is None:
        raise RuntimeError("source document dedupe conflict did not resolve")
    await db.execute(
        update(SourceDocument)
        .where(SourceDocument.id == document_id)
        .values(
            checked_at=func.greatest(
                SourceDocument.checked_at, values["checked_at"]
            )
        )
    )
    return int(document_id)


def _scraper_entity_type(scraper_name: str, record: dict[str, Any]) -> str | None:
    if scraper_name == "rera_projects":
        return "rera_project"
    if scraper_name != "zoning":
        return None
    if record.get("_table") == "colony_approvals":
        return "colony_approval"
    return "zoning_data"


async def persist_scrape_provenance(
    db: AsyncSession,
    *,
    scraper_name: str,
    run_id: int,
    records: list[dict[str, Any]],
    source_documents: list[dict[str, Any]],
    run_succeeded: bool,
) -> list[dict[str, str]]:
    """Persist source metadata, per-field assertions, and changed entity revisions."""
    if scraper_name == "rera_projects" and not settings.HRERA_DATA_ENABLED:
        return [
            {
                "stage": "rights_gate",
                "error_type": "PermissionError",
                "message": "HRERA provenance persistence is disabled",
            }
        ]
    errors: list[dict[str, str]] = []
    document_ids: dict[str, int] = {}
    source_metadata: dict[str, dict[str, Any]] = {}
    checked_entities: list[Any] = []
    for source in source_documents:
        source_key = str(source["source_key"])
        source_metadata[source_key] = source
        values = {key: value for key, value in source.items() if key != "source_key"}
        try:
            async with db.begin_nested():
                document_ids[source_key] = await _get_or_create_source_document(db, values)
        except Exception as exc:
            errors.append(
                {
                    "stage": "source_document",
                    "error_type": type(exc).__name__,
                    "message": "Source document persistence failed",
                }
            )

    seen: set[tuple[str, int, int]] = set()
    for record in records:
        entity_type = _scraper_entity_type(scraper_name, record)
        if entity_type is None:
            continue
        source_key = str(record.get("_source_key", ""))
        document_id = document_ids.get(source_key)
        if document_id is None:
            errors.append(
                {
                    "stage": "source_link",
                    "error_type": "MissingSourceDocument",
                    "message": "Source document link unavailable",
                }
            )
            continue
        model, target_field, allowed_fields = ENTITY_TARGETS[entity_type]
        if entity_type == "rera_project":
            conditions = [model.rera_number == record.get("rera_number")]
        elif entity_type == "zoning_data":
            conditions = [
                model.sector == record.get("sector"),
                model.land_use == record.get("land_use"),
            ]
        else:
            conditions = [model.colony_name == record.get("colony_name")]
            if record.get("licence_number") is not None:
                conditions.append(model.licence_number == record["licence_number"])
            else:
                conditions.append(model.licence_number.is_(None))
        try:
            async with db.begin_nested():
                result = await db.execute(select(model).where(*conditions).limit(1))
                entity = result.scalar_one_or_none()
                if entity is None:
                    raise ValueError(f"{entity_type} record was not found after upsert")
                entity_id = entity.id
                dedupe_key = (entity_type, entity_id, document_id)
                if dedupe_key in seen:
                    continue
                seen.add(dedupe_key)
                entity.last_checked_at = source_metadata[source_key]["checked_at"]

                snapshot = {
                    field: getattr(entity, field)
                    for field in allowed_fields
                }
                await record_entity_revision(
                    db,
                    entity_type=entity_type,
                    entity_id=entity_id,
                    snapshot=snapshot,
                    source_run_id=run_id,
                    source_document_id=document_id,
                )

                target_fk = {target_field: entity_id}
                for field in allowed_fields:
                    if field not in record or record[field] is None:
                        continue
                    db.add(
                        DataHubEvidenceAssertion(
                            **target_fk,
                            field_path=f"{entity_type}.{field}",
                            normalized_value=_json_value(getattr(entity, field)),
                            unit=_UNITS.get(field),
                            source_document_id=document_id,
                            locator_page=record.get("_locator_page"),
                            locator_table=record.get("_locator_table"),
                            locator_row=record.get("_locator_row"),
                            locator_column=record.get("_locator_columns", {}).get(field),
                            method="scrape",
                            status="unreviewed",
                            source_run_id=run_id,
                        )
                    )
                await db.flush()
                checked_entities.append(entity)
        except Exception as exc:
            errors.append(
                {
                    "stage": "entity_provenance",
                    "error_type": type(exc).__name__,
                    "message": "Entity provenance persistence failed",
                }
            )
    if run_succeeded and not errors:
        for entity in checked_entities:
            entity.last_successful_run_id = run_id
    return errors
