from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.api_v1.dependencies.auth import get_current_active_user
from app.core.database import get_db
from app.models.enums import TenantStatus, UserRole
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


@router.post("/forms", response_model=RentalApplicationForm)
async def create_form(
    payload: RentalApplicationFormCreate,
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    target_owner_id = current_user.id
    if payload.owner_id is not None:
        if current_user.role in (UserRole.admin.value, UserRole.agent.value):
            target_owner_id = payload.owner_id
        else:
            from app.core.exceptions import InsufficientPermissionsError

            raise InsufficientPermissionsError("Only admins/agents can set owner_id")

    form = await create_application_form(
        db,
        actor=current_user,
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


@router.get("/forms", response_model=list[RentalApplicationForm])
async def list_forms(
    owner_id: int | None = Query(None, description="Owner id (agent/admin only)"),
    property_id: int | None = Query(None),
    q: str | None = Query(None, description="Search by title"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    forms = await list_application_forms(
        db,
        actor=current_user,
        owner_id=owner_id,
        property_id=property_id,
        q=q,
        limit=limit,
        offset=offset,
    )
    return [RentalApplicationForm.model_validate(f) for f in forms]


@router.get("/forms/{form_id}", response_model=RentalApplicationForm)
async def get_form(
    form_id: int,
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    form = await get_application_form(db, actor=current_user, form_id=form_id)
    return RentalApplicationForm.model_validate(form)


@router.get("", response_model=list[RentalApplication])
async def list_inbox(
    owner_id: int | None = Query(None, description="Owner id (agent/admin only)"),
    property_id: int | None = Query(None),
    status: TenantStatus | None = Query(None),
    submitted_from: datetime | None = Query(None),
    submitted_to: datetime | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    apps = await list_applications(
        db,
        actor=current_user,
        owner_id=owner_id,
        property_id=property_id,
        status=status,
        submitted_from=submitted_from,
        submitted_to=submitted_to,
        limit=limit,
        offset=offset,
    )
    return [RentalApplication.model_validate(a) for a in apps]


@router.get("/{application_id}", response_model=RentalApplication)
async def get_application_detail(
    application_id: int,
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    app = await get_application(db, actor=current_user, application_id=application_id)
    return RentalApplication.model_validate(app)


@public_router.get("/applications/{slug}", response_model=PublicRentalApplicationForm)
async def get_public_form(slug: str, db: AsyncSession = Depends(get_db)):
    form = await get_public_application_form_by_slug(db, slug=slug)
    return PublicRentalApplicationForm.model_validate(form)


@public_router.post("/applications/{slug}/submit", response_model=RentalApplication)
async def submit_public_form(
    slug: str,
    payload: RentalApplicationSubmit,
    db: AsyncSession = Depends(get_db),
):
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


@router.post("/{application_id}/decision", response_model=RentalApplication)
async def decide(
    application_id: int,
    payload: RentalApplicationDecision,
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    # Only approve/reject are supported decisions in MVP
    if payload.decision not in {TenantStatus.approved, TenantStatus.rejected}:
        from app.core.exceptions import BadRequestException

        raise BadRequestException(detail="decision must be approved or rejected")

    application = await decide_application(
        db,
        actor=current_user,
        application_id=application_id,
        decision=payload.decision,
    )
    return RentalApplication.model_validate(application)
