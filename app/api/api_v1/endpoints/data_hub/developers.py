"""Developer (promoter) intelligence endpoints: list, detail, trust score.

Gated on ``settings.HRERA_DATA_ENABLED`` like the rest of the HRERA surface.
Project and complaint counts are counted live from the filings, not read from the
cached score row, so a newly ingested filing shows up immediately.
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.core.database import get_db
from app.models.data_hub import Developer, DeveloperScore, ReraComplaint, ReraProject
from app.schemas.data_hub import (
    DeveloperDetailResponse,
    DeveloperScoreResponse,
    DeveloperSummaryResponse,
    ProjectSummaryResponse,
)
from app.schemas.pagination import (
    CursorPage,
    CursorParams,
    build_cursor_page,
    offset_payload,
    read_offset,
)

from .projects import execute_safe, project_summary_query, serialize_summaries
from .rera import _require_hrera_enabled

router = APIRouter()

# A developer page shows a profile and its portfolio. The portfolio is capped:
# the public contract types it as a plain list, so it cannot carry a cursor.
DEVELOPER_PROJECTS_LIMIT = 50


def _as_float(value: Any) -> float | None:
    return None if value is None else float(value)


async def _project_counts(db: AsyncSession, slugs: list[str]) -> dict[str, int]:
    if not slugs:
        return {}
    rows = await execute_safe(
        db,
        select(ReraProject.developer_slug, func.count())
        .where(ReraProject.developer_slug.in_(slugs))
        .group_by(ReraProject.developer_slug),
    )
    return {slug: count for slug, count in rows if slug is not None}


async def _complaint_counts(db: AsyncSession, slugs: list[str]) -> dict[str, int]:
    if not slugs:
        return {}
    rows = await execute_safe(
        db,
        select(ReraComplaint.builder_slug, func.count())
        .where(ReraComplaint.builder_slug.in_(slugs))
        .group_by(ReraComplaint.builder_slug),
    )
    return {slug: count for slug, count in rows if slug is not None}


def _developer_summary(
    developer: Developer,
    score: DeveloperScore | None,
    project_count: int,
    complaint_count: int,
) -> DeveloperSummaryResponse:
    return DeveloperSummaryResponse(
        id=developer.id,
        slug=developer.slug,
        name=developer.name,
        legal_name=developer.legal_name,
        logo_url=developer.logo_url,
        website_url=developer.website_url,
        headquarters=developer.headquarters,
        founded_year=developer.founded_year,
        is_listed=developer.is_listed,
        total_score=_as_float(score.total_score) if score is not None else None,
        project_count=project_count,
        complaint_count=complaint_count,
    )


async def _serialize_developers(db: AsyncSession, rows: list[Any]) -> list[DeveloperSummaryResponse]:
    slugs = [developer.slug for developer, _score in rows]
    project_counts = await _project_counts(db, slugs)
    complaint_counts = await _complaint_counts(db, slugs)
    return [
        _developer_summary(
            developer,
            score,
            project_counts.get(developer.slug, 0),
            complaint_counts.get(developer.slug, 0),
        )
        for developer, score in rows
    ]


@router.get(
    "/developers",
    response_model=CursorPage[DeveloperSummaryResponse],
    summary="List developers",
    responses={503: {"description": "HRERA surface turned off by configuration"}},
)
async def list_developers(
    q: str | None = Query(None, description="Search developer name"),
    order_by: Literal["name", "score"] = Query(
        "name", description="Sort by developer name or by total trust score"
    ),
    page: CursorParams = Depends(),
    db: AsyncSession = Depends(get_db),
):
    """List developers with cursor paging, ordered by name or by total score."""
    _require_hrera_enabled()
    filters_payload = {"q": q, "order_by": order_by}
    cursor_payload = page.decoded(filters_payload)
    offset = read_offset(cursor_payload)

    filters: list[ColumnElement[bool]] = []
    if q:
        filters.append(Developer.name.ilike(f"%{q}%"))

    # The two orderings sort on different column types (a nullable score and a
    # name), so the tuple is annotated rather than inferred from one branch.
    ordering: tuple[Any, ...] = (
        (DeveloperScore.total_score.desc().nulls_last(), Developer.id)
        if order_by == "score"
        else (Developer.name, Developer.id)
    )

    total: int | None = None
    if page.include_total:
        count_q = select(func.count()).select_from(Developer)
        if filters:
            count_q = count_q.where(and_(*filters))
        total = await execute_safe(db, count_q, mode="scalar")

    data_q = (
        select(Developer, DeveloperScore)
        .outerjoin(DeveloperScore, DeveloperScore.developer_id == Developer.id)
        .order_by(*ordering)
    )
    if filters:
        data_q = data_q.where(and_(*filters))
    rows = await execute_safe(db, data_q.offset(offset).limit(page.limit + 1))

    has_more = len(rows) > page.limit
    page_rows = rows[: page.limit]
    items = await _serialize_developers(db, page_rows)
    next_payload = offset_payload(offset + page.limit) if has_more else None
    return build_cursor_page(
        items,
        limit=page.limit,
        next_payload=next_payload,
        total=total,
        filters=filters_payload,
    )


async def _load_developer(db: AsyncSession, slug: str) -> Developer:
    developer: Developer | None = await execute_safe(
        db, select(Developer).where(Developer.slug == slug), mode="one_or_none"
    )
    if developer is None:
        raise HTTPException(status_code=404, detail="Developer not found")
    return developer


@router.get(
    "/developers/{slug}",
    response_model=DeveloperDetailResponse,
    summary="Get developer detail",
    responses={503: {"description": "HRERA surface turned off by configuration"}},
)
async def get_developer(slug: str, db: AsyncSession = Depends(get_db)):
    """Return one developer with its score and its filed portfolio."""
    _require_hrera_enabled()
    developer = await _load_developer(db, slug)

    score = await execute_safe(
        db,
        select(DeveloperScore).where(DeveloperScore.developer_id == developer.id),
        mode="one_or_none",
    )
    project_count = await execute_safe(
        db,
        select(func.count())
        .select_from(ReraProject)
        .where(ReraProject.developer_slug == slug),
        mode="scalar",
    )
    complaint_count = await execute_safe(
        db,
        select(func.count())
        .select_from(ReraComplaint)
        .where(ReraComplaint.builder_slug == slug),
        mode="scalar",
    )
    rows = await execute_safe(
        db,
        project_summary_query()
        .where(ReraProject.developer_slug == slug, ReraProject.slug.isnot(None))
        .order_by(ReraProject.id)
        .limit(DEVELOPER_PROJECTS_LIMIT),
    )
    projects: list[ProjectSummaryResponse] = await serialize_summaries(db, rows)

    return DeveloperDetailResponse(
        **_developer_summary(developer, score, project_count, complaint_count).model_dump(),
        summary=developer.summary,
        dossier=developer.dossier,
        cin=developer.cin,
        geographies=developer.geographies,
        score=DeveloperScoreResponse.model_validate(score) if score is not None else None,
        projects=projects,
    )


@router.get(
    "/developers/{slug}/score",
    response_model=DeveloperScoreResponse,
    summary="Get developer score",
    responses={503: {"description": "HRERA surface turned off by configuration"}},
)
async def get_developer_score(slug: str, db: AsyncSession = Depends(get_db)):
    """Return the current five-pillar trust score for one developer."""
    _require_hrera_enabled()
    developer = await _load_developer(db, slug)
    score = await execute_safe(
        db,
        select(DeveloperScore).where(DeveloperScore.developer_id == developer.id),
        mode="one_or_none",
    )
    if score is None:
        raise HTTPException(status_code=404, detail="Developer score not available")
    return DeveloperScoreResponse.model_validate(score)
