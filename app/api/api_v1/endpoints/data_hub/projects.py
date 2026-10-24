"""Project intelligence endpoints: list, detail, nearby, price history, documents, FAQ.

Every route is gated on ``settings.HRERA_DATA_ENABLED`` through the shared
``_require_hrera_enabled`` helper, so turning the HRERA surface off turns these
off too, with the same 503 payload.

A project card mixes the register row (``rera_projects``) with the filing profile
(``rera_project_profiles``), so responses are built by an explicit factory instead
of ORM validation. Provenance still comes from the shared provenance service.

Projects without a slug are excluded everywhere: the public contract types ``slug``
as a non-null string, and a row with a null slug has no addressable detail page.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import Select, and_, func, or_, select
from sqlalchemy.exc import OperationalError, ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.core.database import get_db
from app.core.exceptions import ServiceUnavailableException
from app.core.logging import get_logger
from app.models.data_hub import (
    ProjectPriceHistory,
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
from app.models.enums import ProjectStage
from app.schemas.data_hub import (
    BankAccountResponse,
    DataHubProvenanceSummary,
    FacilityResponse,
    FaqItemResponse,
    LandUsageResponse,
    NocResponse,
    PricePointResponse,
    ProjectCostResponse,
    ProjectDetailResponse,
    ProjectDocumentResponse,
    ProjectFaqResponse,
    ProjectPersonResponse,
    ProjectProfileResponse,
    ProjectSummaryResponse,
    QuarterlyExpenditureResponse,
    SpecificationResponse,
    StatutoryApprovalResponse,
    UnitConfigResponse,
)
from app.schemas.pagination import (
    CursorPage,
    CursorParams,
    build_cursor_page,
    offset_payload,
    read_offset,
)
from app.services.data_hub.provenance import get_public_provenance_summaries

from .rera import _require_hrera_enabled

router = APIRouter()
logger = get_logger(__name__)

# Nearby projects are a small "you may also like" strip, not a page of results.
NEARBY_PROJECT_LIMIT = 12
_SQM_PER_ACRE = 4046.8564224
_UNAVAILABLE_DETAIL = "Project data is temporarily unavailable"


async def execute_safe(db: AsyncSession, stmt: Select[Any], *, mode: str = "all") -> Any:
    """Run one read statement. A database error raises 503, matching the data-hub helpers.

    ``mode`` selects the result shape: ``all`` (row tuples), ``scalars`` (list of
    entities), ``first`` / ``one_or_none`` (one row or entity), ``scalar`` (one value).
    """
    try:
        result = await db.execute(stmt)
        if mode == "scalars":
            return list(result.scalars().all())
        if mode == "scalar":
            return result.scalar_one()
        if mode == "one_or_none":
            return result.scalar_one_or_none()
        if mode == "first":
            return result.first()
        return list(result.all())
    except (ProgrammingError, OperationalError) as exc:
        logger.error("Project intelligence query failed: %s", exc)
        raise ServiceUnavailableException(
            detail=_UNAVAILABLE_DETAIL,
            error_code="DATA_UNAVAILABLE",
        ) from exc


def _as_float(value: Any) -> float | None:
    return None if value is None else float(value)


def _acres_from_sqm(value: Any) -> float | None:
    if value is None:
        return None
    return round(float(value) / _SQM_PER_ACRE, 4)


def _land_area_acres(project: ReraProject, profile: ReraProjectProfile | None) -> float | None:
    """Filed acres first, then the filed land area converted, then the register's area."""
    if profile is not None:
        if profile.licensed_land_acres is not None:
            return round(float(profile.licensed_land_acres), 4)
        if profile.land_area_sqm is not None:
            return _acres_from_sqm(profile.land_area_sqm)
    return _acres_from_sqm(project.total_area_sqm)


def _total_units(project: ReraProject, profile: ReraProjectProfile | None) -> int | None:
    """The filing's apartment count wins; the register row is the fallback."""
    if profile is not None and profile.total_units is not None:
        return profile.total_units
    return project.total_units


def project_summary(
    project: ReraProject,
    profile: ReraProjectProfile | None,
    provenance: DataHubProvenanceSummary | None = None,
) -> ProjectSummaryResponse:
    """Build one project card from the register row and its filing profile."""
    # Every query that builds a summary filters on ``_addressable()``, so a row
    # without a slug never reaches here. Asserting it states the invariant and
    # fails loudly if a caller ever drops that filter, instead of publishing a
    # card with a null URL key.
    if project.slug is None:
        raise ValueError(f"project {project.id} has no slug and cannot be published")
    return ProjectSummaryResponse(
        id=project.id,
        slug=project.slug,
        rera_number=project.rera_number,
        project_name=project.project_name,
        developer_name=project.developer_name,
        developer_slug=project.developer_slug,
        location=project.location,
        district=project.district,
        stage=profile.stage if profile is not None else None,
        total_units=_total_units(project, profile),
        towers=profile.towers if profile is not None else None,
        land_area_acres=_land_area_acres(project, profile),
        proposed_far=_as_float(profile.proposed_far) if profile is not None else None,
        proposed_completion_date=(
            profile.proposed_completion_date if profile is not None else None
        ),
        current_price_per_sqft=(
            _as_float(profile.current_price_per_sqft) if profile is not None else None
        ),
        possession_date=project.possession_date,
        status=project.status,
        complaint_count=project.complaint_count or 0,
        source_url=project.source_url,
        updated_at=project.updated_at,
        provenance=provenance,
    )


def project_summary_query() -> Select[Any]:
    """Project rows joined to their filing profile. The profile may be missing."""
    return select(ReraProject, ReraProjectProfile).outerjoin(
        ReraProjectProfile, ReraProjectProfile.rera_project_id == ReraProject.id
    )


def _addressable() -> ColumnElement[bool]:
    return ReraProject.slug.isnot(None)


async def serialize_summaries(
    db: AsyncSession, rows: list[Any]
) -> list[ProjectSummaryResponse]:
    """Attach provenance to a page of ``(project, profile)`` rows in one extra query."""
    projects = [project for project, _profile in rows]
    summaries = await get_public_provenance_summaries(db, "rera_project", projects)
    return [
        project_summary(project, profile, summaries.get(project.id))
        for project, profile in rows
    ]


def _project_units_expr() -> Any:
    return func.coalesce(ReraProjectProfile.total_units, ReraProject.total_units)


def build_project_faq(
    project: ReraProject,
    profile: ReraProjectProfile | None,
    cost: ReraProjectCost | None,
    documents: list[Any],
) -> list[FaqItemResponse]:
    """Deterministic FAQ from filed values. No model call, no invented answer.

    A question appears only when its answer exists. A project with no filing
    profile has no filed detail to summarise, so it gets no questions at all
    rather than a list of questions with null answers.
    """
    if profile is None:
        return []

    name = project.project_name
    items: list[FaqItemResponse] = []

    if project.rera_number:
        items.append(
            FaqItemResponse(
                question=f"What is the RERA registration number of {name}?",
                answer=project.rera_number,
            )
        )
    if project.developer_name:
        items.append(
            FaqItemResponse(
                question=f"Who is the developer of {name}?",
                answer=project.developer_name,
            )
        )
    units = _total_units(project, profile)
    if units:
        items.append(
            FaqItemResponse(
                question=f"How many units does {name} have?",
                answer=f"{units:,} units as filed with the authority",
            )
        )
    if profile.towers:
        items.append(
            FaqItemResponse(
                question=f"How many towers does {name} have?",
                answer=f"{profile.towers} towers as filed with the authority",
            )
        )
    acres = _land_area_acres(project, profile)
    if acres is not None:
        items.append(
            FaqItemResponse(
                question=f"What is the land area of {name}?",
                answer=f"{acres:,.4f} acres as filed with the authority",
            )
        )
    if project.possession_date is not None:
        items.append(
            FaqItemResponse(
                question=f"When is possession expected for {name}?",
                answer=project.possession_date.isoformat(),
            )
        )
    if profile.proposed_completion_date is not None:
        items.append(
            FaqItemResponse(
                question=f"When is {name} expected to be completed?",
                answer=profile.proposed_completion_date.isoformat(),
            )
        )
    if cost is not None and cost.total_cost is not None:
        items.append(
            FaqItemResponse(
                question=f"What is the estimated cost of {name}?",
                answer=f"INR {float(cost.total_cost):,.0f} as filed with the authority",
            )
        )
    if documents:
        items.append(
            FaqItemResponse(
                question=f"How many documents are on file for {name}?",
                answer=f"{len(documents)}",
            )
        )
    return items


async def _load_project_row(db: AsyncSession, slug: str) -> Any:
    row = await execute_safe(
        db,
        project_summary_query().where(ReraProject.slug == slug),
        mode="first",
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return row


async def _nearby_rows(db: AsyncSession, project: ReraProject) -> list[Any]:
    # The portal scan stores the state name when a filing names no district. That
    # marker is not a place, so it has no neighbours.
    from app.services.data_hub.rera_portal_scan import _DEFAULT_DISTRICT

    if not project.district or project.district == _DEFAULT_DISTRICT:
        return []
    rows: list[Any] = await execute_safe(
        db,
        project_summary_query()
        .where(
            ReraProject.district == project.district,
            ReraProject.id != project.id,
            _addressable(),
        )
        .order_by(ReraProject.id)
        .limit(NEARBY_PROJECT_LIMIT),
    )
    return rows


@router.get(
    "/projects",
    response_model=CursorPage[ProjectSummaryResponse],
    summary="List projects",
    responses={503: {"description": "HRERA surface turned off by configuration"}},
)
async def list_projects(
    district: str | None = Query(None, description="Exact district match"),
    stage: ProjectStage | None = Query(None, description="Filed lifecycle stage"),
    developer_slug: str | None = Query(None),
    q: str | None = Query(None, description="Search project name or developer"),
    min_units: int | None = Query(None, ge=0, description="Minimum total units"),
    max_units: int | None = Query(None, ge=0, description="Maximum total units"),
    page: CursorParams = Depends(),
    db: AsyncSession = Depends(get_db),
):
    """List projects with cursor paging, ordered by primary key."""
    _require_hrera_enabled()
    filters_payload = {
        "district": district,
        "stage": stage.value if stage is not None else None,
        "developer_slug": developer_slug,
        "q": q,
        "min_units": min_units,
        "max_units": max_units,
    }
    filters: list[ColumnElement[bool]] = [_addressable()]
    if district:
        filters.append(ReraProject.district == district)
    if stage is not None:
        filters.append(ReraProjectProfile.stage == stage)
    if developer_slug:
        filters.append(ReraProject.developer_slug == developer_slug)
    if q:
        filters.append(
            or_(
                ReraProject.project_name.ilike(f"%{q}%"),
                ReraProject.developer_name.ilike(f"%{q}%"),
            )
        )
    units_expr = _project_units_expr()
    if min_units is not None:
        filters.append(units_expr >= min_units)
    if max_units is not None:
        filters.append(units_expr <= max_units)

    cursor_payload = page.decoded(filters_payload)
    offset = read_offset(cursor_payload)

    total: int | None = None
    if page.include_total:
        count_q = (
            select(func.count())
            .select_from(ReraProject)
            .outerjoin(ReraProjectProfile, ReraProjectProfile.rera_project_id == ReraProject.id)
            .where(and_(*filters))
        )
        total = await execute_safe(db, count_q, mode="scalar")

    data_q = project_summary_query().where(and_(*filters)).order_by(ReraProject.id)
    rows = await execute_safe(db, data_q.offset(offset).limit(page.limit + 1))

    has_more = len(rows) > page.limit
    page_rows = rows[: page.limit]
    items = await serialize_summaries(db, page_rows)
    next_payload = offset_payload(offset + page.limit) if has_more else None
    return build_cursor_page(
        items,
        limit=page.limit,
        next_payload=next_payload,
        total=total,
        filters=filters_payload,
    )


@router.get(
    "/projects/{slug}",
    response_model=ProjectDetailResponse,
    summary="Get project detail",
    responses={503: {"description": "HRERA surface turned off by configuration"}},
)
async def get_project(slug: str, db: AsyncSession = Depends(get_db)):
    """Return the full filed project. A fixed number of queries; no lazy loads."""
    _require_hrera_enabled()
    row = await _load_project_row(db, slug)
    project, profile = row
    project_id = project.id

    # The three one-to-one tables are joined in a single round trip. Each has a
    # UNIQUE constraint on rera_project_id, so the join cannot multiply rows.
    one_to_one = await execute_safe(
        db,
        select(ReraProjectCost, ReraStatutoryApproval, ReraProjectBankAccount)
        .select_from(ReraProject)
        .outerjoin(ReraProjectCost, ReraProjectCost.rera_project_id == ReraProject.id)
        .outerjoin(
            ReraStatutoryApproval, ReraStatutoryApproval.rera_project_id == ReraProject.id
        )
        .outerjoin(
            ReraProjectBankAccount, ReraProjectBankAccount.rera_project_id == ReraProject.id
        )
        .where(ReraProject.id == project_id),
        mode="first",
    )
    cost, statutory, bank_account = one_to_one

    land_usage = await execute_safe(
        db,
        select(ReraLandUsage)
        .where(ReraLandUsage.rera_project_id == project_id)
        .order_by(ReraLandUsage.particular, ReraLandUsage.id),
        mode="scalars",
    )
    expenditure = await execute_safe(
        db,
        select(ReraQuarterlyExpenditure)
        .where(ReraQuarterlyExpenditure.rera_project_id == project_id)
        .order_by(
            ReraQuarterlyExpenditure.year,
            ReraQuarterlyExpenditure.quarter,
            ReraQuarterlyExpenditure.category,
            ReraQuarterlyExpenditure.particular,
            ReraQuarterlyExpenditure.id,
        ),
        mode="scalars",
    )
    documents = await execute_safe(
        db,
        select(ReraProjectDocument)
        .where(ReraProjectDocument.rera_project_id == project_id)
        .order_by(ReraProjectDocument.ordinal, ReraProjectDocument.id),
        mode="scalars",
    )
    facilities = await execute_safe(
        db,
        select(ReraProjectFacility)
        .where(ReraProjectFacility.rera_project_id == project_id)
        .order_by(ReraProjectFacility.facility, ReraProjectFacility.id),
        mode="scalars",
    )
    nocs = await execute_safe(
        db,
        select(ReraProjectNoc)
        .where(ReraProjectNoc.rera_project_id == project_id)
        .order_by(ReraProjectNoc.facility, ReraProjectNoc.id),
        mode="scalars",
    )
    people = await execute_safe(
        db,
        select(ReraProjectPerson)
        .where(ReraProjectPerson.rera_project_id == project_id)
        .order_by(ReraProjectPerson.role, ReraProjectPerson.name, ReraProjectPerson.id),
        mode="scalars",
    )
    unit_configs = await execute_safe(
        db,
        select(ReraProjectUnitConfig)
        .where(ReraProjectUnitConfig.rera_project_id == project_id)
        .order_by(ReraProjectUnitConfig.ordinal, ReraProjectUnitConfig.id),
        mode="scalars",
    )
    specifications = await execute_safe(
        db,
        select(ReraProjectSpecification)
        .where(ReraProjectSpecification.rera_project_id == project_id)
        .order_by(
            ReraProjectSpecification.scope,
            ReraProjectSpecification.unit_type,
            ReraProjectSpecification.spec_key,
            ReraProjectSpecification.id,
        ),
        mode="scalars",
    )
    price_history = await execute_safe(
        db,
        select(ProjectPriceHistory)
        .where(ProjectPriceHistory.rera_project_id == project_id)
        .order_by(
            ProjectPriceHistory.quarter,
            ProjectPriceHistory.unit_type,
            ProjectPriceHistory.id,
        ),
        mode="scalars",
    )
    nearby_rows = await _nearby_rows(db, project)

    # One provenance query covers the detail row and every nearby card.
    provenance_rows = [row, *nearby_rows]
    summaries = await get_public_provenance_summaries(
        db, "rera_project", [entity for entity, _profile in provenance_rows]
    )
    summary = project_summary(project, profile, summaries.get(project.id))
    nearby = [
        project_summary(nearby_project, nearby_profile, summaries.get(nearby_project.id))
        for nearby_project, nearby_profile in nearby_rows
    ]

    return ProjectDetailResponse(
        **summary.model_dump(),
        profile=ProjectProfileResponse.model_validate(profile) if profile is not None else None,
        land_usage=[LandUsageResponse.model_validate(row) for row in land_usage],
        cost=ProjectCostResponse.model_validate(cost) if cost is not None else None,
        expenditure=[
            QuarterlyExpenditureResponse.model_validate(row) for row in expenditure
        ],
        documents=[ProjectDocumentResponse.model_validate(row) for row in documents],
        statutory=(
            StatutoryApprovalResponse.model_validate(statutory)
            if statutory is not None
            else None
        ),
        facilities=[FacilityResponse.model_validate(row) for row in facilities],
        nocs=[NocResponse.model_validate(row) for row in nocs],
        people=[ProjectPersonResponse.model_validate(row) for row in people],
        bank_account=(
            BankAccountResponse.model_validate(bank_account)
            if bank_account is not None
            else None
        ),
        unit_configs=[UnitConfigResponse.model_validate(row) for row in unit_configs],
        specifications=[SpecificationResponse.model_validate(row) for row in specifications],
        nearby=nearby,
        price_history=[PricePointResponse.model_validate(row) for row in price_history],
        faq=build_project_faq(project, profile, cost, documents),
    )


@router.get(
    "/projects/{slug}/nearby",
    response_model=list[ProjectSummaryResponse],
    summary="List projects near a project",
    responses={503: {"description": "HRERA surface turned off by configuration"}},
)
async def list_nearby_projects(slug: str, db: AsyncSession = Depends(get_db)):
    """Projects in the same district, excluding the project itself, capped at a constant."""
    _require_hrera_enabled()
    row = await _load_project_row(db, slug)
    project, _profile = row
    return await serialize_summaries(db, await _nearby_rows(db, project))


@router.get(
    "/projects/{slug}/price-history",
    response_model=list[PricePointResponse],
    summary="List project price history",
    responses={503: {"description": "HRERA surface turned off by configuration"}},
)
async def list_project_price_history(slug: str, db: AsyncSession = Depends(get_db)):
    """Price points for one project, oldest quarter first."""
    _require_hrera_enabled()
    row = await _load_project_row(db, slug)
    project, _profile = row
    rows = await execute_safe(
        db,
        select(ProjectPriceHistory)
        .where(ProjectPriceHistory.rera_project_id == project.id)
        .order_by(
            ProjectPriceHistory.quarter,
            ProjectPriceHistory.unit_type,
            ProjectPriceHistory.id,
        ),
        mode="scalars",
    )
    return [PricePointResponse.model_validate(price_point) for price_point in rows]


@router.get(
    "/projects/{slug}/documents",
    response_model=list[ProjectDocumentResponse],
    summary="List project documents",
    responses={503: {"description": "HRERA surface turned off by configuration"}},
)
async def list_project_documents(slug: str, db: AsyncSession = Depends(get_db)):
    """Documents filed for one project, in filing order."""
    _require_hrera_enabled()
    row = await _load_project_row(db, slug)
    project, _profile = row
    rows = await execute_safe(
        db,
        select(ReraProjectDocument)
        .where(ReraProjectDocument.rera_project_id == project.id)
        .order_by(ReraProjectDocument.ordinal, ReraProjectDocument.id),
        mode="scalars",
    )
    return [ProjectDocumentResponse.model_validate(document) for document in rows]


@router.get(
    "/projects/{slug}/faq",
    response_model=ProjectFaqResponse,
    summary="Get project FAQ",
    responses={503: {"description": "HRERA surface turned off by configuration"}},
)
async def get_project_faq(slug: str, db: AsyncSession = Depends(get_db)):
    """Deterministic FAQ built from filed values. A question without an answer is dropped."""
    _require_hrera_enabled()
    row = await _load_project_row(db, slug)
    project, profile = row
    cost = await execute_safe(
        db,
        select(ReraProjectCost).where(ReraProjectCost.rera_project_id == project.id),
        mode="one_or_none",
    )
    document_ids = await execute_safe(
        db,
        select(ReraProjectDocument.id).where(ReraProjectDocument.rera_project_id == project.id),
        mode="scalars",
    )
    return ProjectFaqResponse(items=build_project_faq(project, profile, cost, document_ids))
