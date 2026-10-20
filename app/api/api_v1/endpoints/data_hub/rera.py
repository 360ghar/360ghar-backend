"""RERA project, complaint, and builder endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.exceptions import ServiceUnavailableException
from app.core.logging import get_logger
from app.models.data_hub import ReraComplaint, ReraProject
from app.schemas.data_hub import (
    BuilderReputationResponse,
    ReraProjectResponse,
    ReraVerifyResult,
)
from app.schemas.pagination import (
    CursorPage,
    CursorParams,
    build_cursor_page,
    offset_payload,
    read_offset,
)
from app.services.data_hub.utils import calculate_builder_score

from .helpers import _safe_list_query

router = APIRouter()
logger = get_logger(__name__)


@router.get(
    "/rera-projects", response_model=CursorPage[ReraProjectResponse], summary="List RERA projects"
)
async def list_rera_projects(
    status: str | None = Query(None),
    q: str | None = Query(None, description="Search project name or developer"),
    page: CursorParams = Depends(),
    db: AsyncSession = Depends(get_db),
):
    """List RERA projects with optional status filter and text search."""
    filters_payload = {"status": status, "q": q}
    filters = []
    if status:
        filters.append(ReraProject.status == status)
    if q:
        filters.append(
            ReraProject.project_name.ilike(f"%{q}%") | ReraProject.developer_name.ilike(f"%{q}%")
        )

    count_q = select(func.count()).select_from(ReraProject)
    data_q = select(ReraProject)
    if filters:
        count_q = count_q.where(and_(*filters))
        data_q = data_q.where(and_(*filters))

    cursor_payload = page.decoded(filters_payload)
    offset = read_offset(cursor_payload)
    rows, total = await _safe_list_query(
        db, ReraProject, count_q, data_q, offset, page.limit, with_total=page.include_total
    )

    has_more = len(rows) > page.limit
    items = rows[: page.limit]
    next_payload = offset_payload(offset + page.limit) if has_more else None
    return build_cursor_page(
        items, limit=page.limit, next_payload=next_payload, total=total, filters=filters_payload
    )


@router.get(
    "/rera-projects/verify/{rera_number}",
    response_model=ReraVerifyResult,
    summary="Verify RERA number",
)
async def verify_rera_project(rera_number: str, db: AsyncSession = Depends(get_db)):
    """Verify a RERA number — returns validity, status, and project name."""
    result = await db.execute(select(ReraProject).where(ReraProject.rera_number == rera_number))
    row = result.scalar_one_or_none()
    if row is None:
        return ReraVerifyResult(valid=False)
    return ReraVerifyResult(valid=True, status=row.status, project_name=row.project_name)


# ---------------------------------------------------------------------------
# Builders (aggregated from RERA data)
# ---------------------------------------------------------------------------


@router.get(
    "/builders", response_model=CursorPage[BuilderReputationResponse], summary="List builders"
)
async def list_builders(
    q: str | None = Query(None, description="Search builder name"),
    order_by: str | None = Query(None, description="Set to 'score' to sort by builder score"),
    page: CursorParams = Depends(),
    db: AsyncSession = Depends(get_db),
):
    """List builders aggregated from RERA projects, with complaint counts and scores."""
    filters_payload = {"q": q, "order_by": order_by}
    cursor_payload = page.decoded(filters_payload)
    offset = read_offset(cursor_payload)

    slug_q = (
        select(
            ReraProject.developer_slug.label("slug"),
            ReraProject.developer_name.label("builder_name"),
            func.count(ReraProject.id).label("total_projects"),
        )
        .where(ReraProject.developer_slug.isnot(None))
        .group_by(ReraProject.developer_slug, ReraProject.developer_name)
        .order_by(ReraProject.developer_slug, ReraProject.developer_name)
    )
    if q:
        slug_q = slug_q.where(ReraProject.developer_name.ilike(f"%{q}%"))

    try:
        all_rows = (await db.execute(slug_q)).all()
        all_slugs = [r.slug for r in all_rows if r.slug]

        complaint_counts: dict[str, int] = {}
        if all_slugs:
            complaint_count_rows = (
                await db.execute(
                    select(ReraComplaint.builder_slug, func.count().label("cnt"))
                    .where(ReraComplaint.builder_slug.in_(all_slugs))
                    .group_by(ReraComplaint.builder_slug)
                )
            ).all()
            complaint_counts = {r.builder_slug: r.cnt for r in complaint_count_rows}

        summaries: list[dict] = []
        for row in all_rows:
            total_complaints = complaint_counts.get(row.slug, 0)
            summaries.append(
                {
                    "slug": row.slug,
                    "builder_name": row.builder_name or row.slug,
                    "total_projects": row.total_projects,
                    "total_complaints": total_complaints,
                    "builder_score": calculate_builder_score(total_complaints, row.total_projects),
                }
            )
        if order_by == "score":
            summaries.sort(key=lambda x: (-x["builder_score"], x["slug"]))

        total = len(summaries)
        page_summaries = summaries[offset : offset + page.limit]
        page_slugs = [s["slug"] for s in page_summaries]

        projects_by_slug: dict[str, list] = {slug: [] for slug in page_slugs}
        complaints_by_slug: dict[str, list] = {slug: [] for slug in page_slugs}
        if page_slugs:
            proj_rows = (
                (
                    await db.execute(
                        select(ReraProject)
                        .where(ReraProject.developer_slug.in_(page_slugs))
                        .order_by(ReraProject.id)
                    )
                )
                .scalars()
                .all()
            )
            for p in proj_rows:
                if p.developer_slug in projects_by_slug:
                    projects_by_slug[p.developer_slug].append(p)

            comp_rows = (
                (
                    await db.execute(
                        select(ReraComplaint)
                        .where(ReraComplaint.builder_slug.in_(page_slugs))
                        .order_by(ReraComplaint.order_date.desc(), ReraComplaint.id.desc())
                    )
                )
                .scalars()
                .all()
            )
            for c in comp_rows:
                if c.builder_slug in complaints_by_slug:
                    complaints_by_slug[c.builder_slug].append(c)
    except SQLAlchemyError as exc:
        logger.error("Builders query failed: %s", exc)
        raise ServiceUnavailableException(
            detail="Auction data is temporarily unavailable",
            error_code="DATA_UNAVAILABLE",
        ) from exc

    # Children are validated by the constructor, never assigned after it.
    items = [
        BuilderReputationResponse(
            builder_name=s["builder_name"],
            slug=s["slug"],
            total_projects=s["total_projects"],
            total_complaints=s["total_complaints"],
            builder_score=s["builder_score"],
            rera_projects=projects_by_slug[s["slug"]][:5],
            recent_complaints=complaints_by_slug[s["slug"]][:5],
        )
        for s in page_summaries
    ]

    has_more = (offset + page.limit) < total
    next_payload = offset_payload(offset + page.limit) if has_more else None
    return build_cursor_page(
        items,
        limit=page.limit,
        next_payload=next_payload,
        total=total if page.include_total else None,
        filters=filters_payload,
    )


@router.get(
    "/builders/{slug}", response_model=BuilderReputationResponse, summary="Get builder reputation"
)
async def get_builder(slug: str, db: AsyncSession = Depends(get_db)):
    """Get builder reputation details by slug."""
    projects_result = await db.execute(
        select(ReraProject).where(ReraProject.developer_slug == slug)
    )
    projects = projects_result.scalars().all()
    if not projects:
        raise HTTPException(status_code=404, detail="Builder not found")

    total_projects = len(projects)
    builder_name = projects[0].developer_name or slug

    complaint_count_result = await db.execute(
        select(func.count()).select_from(ReraComplaint).where(ReraComplaint.builder_slug == slug)
    )
    total_complaints = complaint_count_result.scalar_one()

    complaints_result = await db.execute(
        select(ReraComplaint)
        .where(ReraComplaint.builder_slug == slug)
        .order_by(ReraComplaint.order_date.desc())
        .limit(20)
    )
    complaints = complaints_result.scalars().all()

    score = calculate_builder_score(total_complaints, total_projects)

    return BuilderReputationResponse(
        builder_name=builder_name,
        slug=slug,
        total_projects=total_projects,
        total_complaints=total_complaints,
        builder_score=score,
        rera_projects=list(projects),  # type: ignore[arg-type]
        recent_complaints=list(complaints),  # type: ignore[arg-type]
    )
