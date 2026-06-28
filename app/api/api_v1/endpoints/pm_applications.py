from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.api_v1.dependencies.auth import get_current_active_user
from app.core.database import get_db
from app.models.enums import TenantStatus, UserRole
from app.schemas.pagination import CursorPage, CursorParams, build_cursor_page
from app.schemas.pm_application import (
    PublicRentalApplicationForm,
    RentalApplication,
    RentalApplicationDecision,
    RentalApplicationForm,
    RentalApplicationFormCreate,
    RentalApplicationSubmit,
)
from app.schemas.user import User as UserSchema
from app.services.pm_applications import (
    create_application_form,
    decide_application,
    get_application,
    get_application_form,
    get_public_application_form_by_slug,
    list_application_forms,
    list_applications,
    submit_public_application,
)

router = APIRouter()
public_router = APIRouter()


@router.post("/forms", response_model=RentalApplicationForm, summary="Create application form")
async def create_form(
    payload: RentalApplicationFormCreate,
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Create application form."""
    target_owner_id = current_user.id
    if payload.owner_id is not None:
        if current_user.role in (UserRole.admin.value, UserRole.agent.value):
            target_owner_id = payload.owner_id
        else:
            from app.core.exceptions import InsufficientPermissionsError

            raise InsufficientPermissionsError("Only admins/agents can set owner_id")

    form = await create_application_form(
        db,
        actor=current_user,  # type: ignore[arg-type]
        owner_id=target_owner_id,
        title=payload.title,
        description=payload.description,
        property_id=payload.property_id,
        application_fee_amount=payload.application_fee_amount,
        required_document_types=payload.required_document_types,
        questions=payload.questions,
        config=payload.config,
    )
    return RentalApplicationForm.model_validate(form)


@router.get("/forms", response_model=CursorPage[RentalApplicationForm], summary="List application forms")
async def list_forms(
    owner_id: int | None = Query(None, description="Owner id (agent/admin only)"),
    property_id: int | None = Query(None),
    q: str | None = Query(None, description="Search by title"),
    page: CursorParams = Depends(),
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """List application forms."""
    rows, next_payload, count_total = await list_application_forms(
        db,
        actor=current_user,  # type: ignore[arg-type]
        owner_id=owner_id,
        property_id=property_id,
        q=q,
        cursor_payload=page.decoded(),
        limit=page.limit,
        with_total=page.include_total,
    )
    items = [RentalApplicationForm.model_validate(f) for f in rows]
    return build_cursor_page(items, limit=page.limit, next_payload=next_payload, total=count_total)


@router.get("/forms/{form_id}", response_model=RentalApplicationForm, summary="Get application form")
async def get_form(
    form_id: int,
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Get application form."""
    form = await get_application_form(db, actor=current_user, form_id=form_id)  # type: ignore[arg-type]
    return RentalApplicationForm.model_validate(form)


@router.get("", response_model=CursorPage[RentalApplication], summary="List applications inbox")
async def list_inbox(
    owner_id: int | None = Query(None, description="Owner id (agent/admin only)"),
    property_id: int | None = Query(None),
    status: TenantStatus | None = Query(None),
    submitted_from: datetime | None = Query(None),
    submitted_to: datetime | None = Query(None),
    page: CursorParams = Depends(),
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """List applications inbox."""
    rows, next_payload, count_total = await list_applications(
        db,
        actor=current_user,  # type: ignore[arg-type]
        owner_id=owner_id,
        property_id=property_id,
        status=status,
        submitted_from=submitted_from,
        submitted_to=submitted_to,
        cursor_payload=page.decoded(),
        limit=page.limit,
        with_total=page.include_total,
    )
    items = [RentalApplication.model_validate(a) for a in rows]
    return build_cursor_page(items, limit=page.limit, next_payload=next_payload, total=count_total)


@router.get("/{application_id}", response_model=RentalApplication, summary="Get application detail")
async def get_application_detail(
    application_id: int,
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Get application detail."""
    app = await get_application(db, actor=current_user, application_id=application_id)  # type: ignore[arg-type]
    return RentalApplication.model_validate(app)


@public_router.get("/applications/{slug}", response_model=PublicRentalApplicationForm, summary="Get public application form")
async def get_public_form(slug: str, db: AsyncSession = Depends(get_db)):
    """Get public application form."""
    form = await get_public_application_form_by_slug(db, slug=slug)
    return PublicRentalApplicationForm.model_validate(form)


@public_router.post("/applications/{slug}/submit", response_model=RentalApplication, summary="Submit public application")
async def submit_public_form(
    slug: str,
    payload: RentalApplicationSubmit,
    db: AsyncSession = Depends(get_db),
):
    """Submit public application."""
    application = await submit_public_application(
        db,
        slug=slug,
        property_id=payload.property_id,
        applicant_full_name=payload.applicant_full_name,
        applicant_phone=payload.applicant_phone,
        applicant_email=payload.applicant_email,
        answers=payload.answers,
        application_data=payload.application_data,
        emergency_contacts=payload.emergency_contacts,
    )
    return RentalApplication.model_validate(application)


@router.post("/{application_id}/decision", response_model=RentalApplication, summary="Decide on application")
async def decide(
    application_id: int,
    payload: RentalApplicationDecision,
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    # Only approve/reject are supported decisions in MVP
    """Decide on application."""
    if payload.decision not in {TenantStatus.approved, TenantStatus.rejected}:
        from app.core.exceptions import BadRequestException

        raise BadRequestException(detail="decision must be approved or rejected")

    application = await decide_application(
        db,
        actor=current_user,  # type: ignore[arg-type]
        application_id=application_id,
        decision=payload.decision,
    )
    return RentalApplication.model_validate(application)
