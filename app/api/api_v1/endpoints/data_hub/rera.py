"""RERA project, complaint, and builder endpoints."""


from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.logging import get_logger
from app.models.data_hub import ReraComplaint, ReraProject
from app.schemas.data_hub import (
    BuilderReputationResponse,
    ReraProjectResponse,
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


@router.get("/rera-projects", response_model=CursorPage[ReraProjectResponse], summary="List RERA projects")
async def list_rera_projects(
    status: str | None = Query(None),
    q: str | None = Query(None, description="Search project name or developer"),
    page: CursorParams = Depends(),
    db: AsyncSession = Depends(get_db),
):
    """List RERA projects with optional status filter and text search."""
    filters = []
    if status:
        filters.append(ReraProject.status == status)
    if q:
        filters.append(
            ReraProject.project_name.ilike(f"%{q}%")
            | ReraProject.developer_name.ilike(f"%{q}%")
        )

    count_q = select(func.count()).select_from(ReraProject)
    data_q = select(ReraProject)
    if filters:
        count_q = count_q.where(and_(*filters))
        data_q = data_q.where(and_(*filters))

    cursor_payload = page.decoded()
    offset = read_offset(cursor_payload)
    rows, total = await _safe_list_query(
        db, ReraProject, count_q, data_q, offset, page.limit, with_total=page.include_total
    )

    has_more = len(rows) > page.limit
    items = rows[: page.limit]
    next_payload = offset_payload(offset + page.limit) if has_more else None
    return build_cursor_page(items, limit=page.limit, next_payload=next_payload, total=total)


@router.get("/rera-projects/verify/{rera_number}", summary="Verify RERA number")
async def verify_rera_project(rera_number: str, db: AsyncSession = Depends(get_db)):
    """Verify a RERA number — returns validity, status, and project name."""
    result = await db.execute(
        select(ReraProject).where(ReraProject.rera_number == rera_number)
    )
    row = result.scalar_one_or_none()
    if row is None:
        return {"valid": False, "status": None, "project_name": None}
    return {"valid": True, "status": row.status, "project_name": row.project_name}


@router.get("/rera-projects/{rera_number}", response_model=ReraProjectResponse, summary="Get RERA project")
async def get_rera_project(rera_number: str, db: AsyncSession = Depends(get_db)):
    """Get a single RERA project by its RERA number."""
    result = await db.execute(
        select(ReraProject).where(ReraProject.rera_number == rera_number)
    )
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="RERA project not found")
    return row


# ---------------------------------------------------------------------------
# Builders (aggregated from RERA data)
# ---------------------------------------------------------------------------


@router.get("/builders", response_model=CursorPage[BuilderReputationResponse], summary="List builders")
async def list_builders(
    q: str | None = Query(None, description="Search builder name"),
    order_by: str | None = Query(None, description="Set to 'score' to sort by builder score"),
    page: CursorParams = Depends(),
    db: AsyncSession = Depends(get_db),
):
    """List builders aggregated from RERA projects, with complaint counts and scores."""
    filters = []
    if q:
        filters.append(ReraProject.developer_name.ilike(f"%{q}%"))

    slug_q = (
        select(
            ReraProject.developer_slug.label("slug"),
            ReraProject.developer_name.label("builder_name"),
            func.count(ReraProject.id).label("total_projects"),
        )
        .where(ReraProject.developer_slug.isnot(None))
        .group_by(ReraProject.developer_slug, ReraProject.developer_name)
    )
    if filters:
        slug_q = slug_q.where(and_(*filters))

    try:
        all_rows = (await db.execute(slug_q)).all()
    except Exception as exc:
        logger.warning("Builders query failed: %s", exc)
        return build_cursor_page([], limit=page.limit, next_payload=None, total=0 if page.include_total else None)

    all_slugs = [r.slug for r in all_rows if r.slug]

    complaint_counts: dict[str, int] = {}
    if all_slugs:
        try:
            complaint_count_rows = (
                await db.execute(
                    select(ReraComplaint.builder_slug, func.count().label("cnt"))
                    .where(ReraComplaint.builder_slug.in_(all_slugs))
                    .group_by(ReraComplaint.builder_slug)
                )
            ).all()
            complaint_counts = {r.builder_slug: r.cnt for r in complaint_count_rows}
        except Exception as exc:
            logger.warning("Builders complaint counts failed: %s", exc)

    all_items: list[BuilderReputationResponse] = []
    for row in all_rows:
        builder_slug = row.slug
        builder_name = row.builder_name or builder_slug
        total_projects = row.total_projects
        total_complaints = complaint_counts.get(builder_slug, 0)
        score = calculate_builder_score(total_complaints, total_projects)
        all_items.append(
            BuilderReputationResponse(
                builder_name=builder_name,
                slug=builder_slug,
                total_projects=total_projects,
                total_complaints=total_complaints,
                builder_score=score,
                rera_projects=[],
                recent_complaints=[],
            )
        )

    if order_by == "score":
        all_items.sort(key=lambda x: x.builder_score, reverse=True)

    total = len(all_items)
    cursor_payload = page.decoded()
    offset = read_offset(cursor_payload)
    page_items = all_items[offset: offset + page.limit]

    page_slugs = [item.slug for item in page_items if item.slug]

    projects_by_slug: dict[str, list] = {s: [] for s in page_slugs}
    if page_slugs:
        try:
            proj_rows = (
                await db.execute(
                    select(ReraProject).where(ReraProject.developer_slug.in_(page_slugs))
                )
            ).scalars().all()
            for p in proj_rows:
                if p.developer_slug in projects_by_slug:
                    projects_by_slug[p.developer_slug].append(p)
        except Exception as exc:
            logger.warning("Builders project lookup failed: %s", exc)

    complaints_by_slug: dict[str, list] = {s: [] for s in page_slugs}
    if page_slugs:
        try:
            comp_rows = (
                await db.execute(
                    select(ReraComplaint)
                    .where(ReraComplaint.builder_slug.in_(page_slugs))
                    .order_by(ReraComplaint.order_date.desc())
                )
            ).scalars().all()
            for c in comp_rows:
                if c.builder_slug in complaints_by_slug:
                    complaints_by_slug[c.builder_slug].append(c)
        except Exception as exc:
            logger.warning("Builders complaint lookup failed: %s", exc)

    items = []
    for item in page_items:
        item.rera_projects = projects_by_slug.get(item.slug, [])[:5]
        item.recent_complaints = complaints_by_slug.get(item.slug, [])[:5]
        items.append(item)

    has_more = (offset + page.limit) < total
    next_payload = offset_payload(offset + page.limit) if has_more else None
    return build_cursor_page(items, limit=page.limit, next_payload=next_payload, total=total if page.include_total else None)


@router.get("/builders/{slug}", response_model=BuilderReputationResponse, summary="Get builder reputation")
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
        select(func.count()).select_from(ReraComplaint)
        .where(ReraComplaint.builder_slug == slug)
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
