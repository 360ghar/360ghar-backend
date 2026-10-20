from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.api_v1.dependencies.auth import get_current_active_user
from app.core.database import get_db
from app.core.exceptions import InsufficientPermissionsError
from app.middleware.rate_limit import EndpointRateLimiter
from app.models.enums import RentalApplicationStatus, UserRole
from app.schemas.pagination import CursorPage, CursorParams, build_cursor_page
from app.schemas.pm_application import (
    PublicRentalApplicationForm,
    PublicRentalApplicationSubmitted,
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

# Anonymous submits: 10 per client per minute on top of the global limit.
_public_submit_limiter = EndpointRateLimiter(calls=10, period=60)


async def _check_public_submit_rate_limit(request: Request) -> None:
    """FastAPI dependency for the anonymous submit route."""
    client_id = _public_submit_limiter.get_client_id(request)
    allowed = await _public_submit_limiter.check_rate_limit(
        client_id, "POST:/pm/public/applications/submit"
    )
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "code": "RATE_LIMITED",
                "message": "Too many applications. Try again later.",
            },
            headers={"Retry-After": str(_public_submit_limiter.period)},
        )


@router.post(
    "/forms",
    response_model=RentalApplicationForm,
    status_code=status.HTTP_201_CREATED,
    summary="Create application form",
)
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
        custom_fields=[f.model_dump() for f in payload.custom_fields]
        if payload.custom_fields is not None
        else None,
        is_active=payload.is_active,
        expires_at=payload.expires_at,
        config=payload.config,
    )
    return RentalApplicationForm.model_validate(form)


@router.get(
    "/forms", response_model=CursorPage[RentalApplicationForm], summary="List application forms"
)
async def list_forms(
    owner_id: int | None = Query(None, description="Owner id (agent/admin only)"),
    property_id: int | None = Query(None),
    q: str | None = Query(None, description="Search by title"),
    page: CursorParams = Depends(),
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """List application forms."""
    filters = {"owner_id": owner_id, "property_id": property_id, "q": q}
    rows, next_payload, count_total = await list_application_forms(
        db,
        actor=current_user,  # type: ignore[arg-type]
        owner_id=owner_id,
        property_id=property_id,
        q=q,
        cursor_payload=page.decoded(filters),
        limit=page.limit,
        with_total=page.include_total,
    )
    items = [RentalApplicationForm.model_validate(f) for f in rows]
    return build_cursor_page(
        items, limit=page.limit, next_payload=next_payload, total=count_total, filters=filters
    )


@router.get(
    "/forms/{form_id}", response_model=RentalApplicationForm, summary="Get application form"
)
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
    form_id: int | None = Query(None),
    status_filter: RentalApplicationStatus | None = Query(None, alias="status"),
    submitted_from: datetime | None = Query(None),
    submitted_to: datetime | None = Query(None),
    page: CursorParams = Depends(),
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """List applications inbox."""
    filters = {
        "owner_id": owner_id,
        "property_id": property_id,
        "form_id": form_id,
        "status": status_filter,
        "submitted_from": submitted_from,
        "submitted_to": submitted_to,
    }
    rows, next_payload, count_total = await list_applications(
        db,
        actor=current_user,  # type: ignore[arg-type]
        owner_id=owner_id,
        property_id=property_id,
        form_id=form_id,
        status=status_filter,
        submitted_from=submitted_from,
        submitted_to=submitted_to,
        cursor_payload=page.decoded(filters),
        limit=page.limit,
        with_total=page.include_total,
    )
    items = [RentalApplication.model_validate(a) for a in rows]
    return build_cursor_page(
        items, limit=page.limit, next_payload=next_payload, total=count_total, filters=filters
    )


@router.get("/{application_id}", response_model=RentalApplication, summary="Get application detail")
async def get_application_detail(
    application_id: int,
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Get application detail."""
    app = await get_application(db, actor=current_user, application_id=application_id)  # type: ignore[arg-type]
    return RentalApplication.model_validate(app)


@public_router.get(
    "/applications/{slug}",
    response_model=PublicRentalApplicationForm,
    summary="Get public application form",
)
async def get_public_form(slug: str, db: AsyncSession = Depends(get_db)):
    """Get public application form."""
    form = await get_public_application_form_by_slug(db, slug=slug)
    return PublicRentalApplicationForm.model_validate(form)


@public_router.post(
    "/applications/{slug}/submit",
    response_model=PublicRentalApplicationSubmitted,
    status_code=status.HTTP_201_CREATED,
    summary="Submit public application",
    dependencies=[Depends(_check_public_submit_rate_limit)],
)
async def submit_public_form(
    slug: str,
    payload: RentalApplicationSubmit,
    db: AsyncSession = Depends(get_db),
):
    """Submit public application. Returns only the id, status and submission time."""
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
    return PublicRentalApplicationSubmitted.model_validate(application)


@router.post(
    "/{application_id}/decision", response_model=RentalApplication, summary="Decide on application"
)
async def decide(
    application_id: int,
    payload: RentalApplicationDecision,
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Decide on application: approved or rejected, with optional notes."""
    application = await decide_application(
        db,
        actor=current_user,  # type: ignore[arg-type]
        application_id=application_id,
        decision=payload.decision,
        notes=payload.notes,
    )
    return RentalApplication.model_validate(application)
