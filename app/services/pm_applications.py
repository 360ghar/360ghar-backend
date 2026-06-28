from __future__ import annotations

import secrets
from datetime import datetime, timezone

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BadRequestException, InsufficientPermissionsError, NotFoundException
from app.models.enums import TenantStatus, UserRole
from app.models.pm_tenants import RentalApplication, RentalApplicationForm
from app.models.properties import Property
from app.models.users import User
from app.schemas.pagination import (
    keyset_filter,
    keyset_payload,
    keyset_sort_value,
    offset_payload,
    read_offset,
)
from app.services.pm_authz import assert_can_manage_owner_portfolio


def _new_slug() -> str:
    # URL-safe, short, non-guessable token (public endpoint identifier)
    return secrets.token_urlsafe(8).rstrip("=")


async def create_application_form(
    db: AsyncSession,
    *,
    actor: User,
    owner_id: int,
    title: str,
    description: str | None = None,
    property_id: int | None = None,
    application_fee_amount: float | None = None,
    required_document_types: dict | None = None,
    questions: dict | None = None,
    config: dict | None = None,
) -> RentalApplicationForm:
    await assert_can_manage_owner_portfolio(db, actor=actor, owner_id=owner_id)

    if property_id is not None:
        prop = await db.get(Property, property_id)
        if not prop:
            raise NotFoundException(detail="Property not found")
        if prop.owner_id != owner_id and actor.role != UserRole.admin.value:
            raise BadRequestException(detail="property_id does not belong to owner_id")

    form = RentalApplicationForm(
        owner_id=owner_id,
        property_id=property_id,
        title=title,
        description=description,
        slug=_new_slug(),
        is_active=True,
        application_fee_amount=application_fee_amount,
        required_document_types=required_document_types,
        questions=questions,
        config=config,
    )
    db.add(form)
    await db.flush()
    await db.refresh(form)
    return form


async def get_application_form(
    db: AsyncSession,
    *,
    actor: User,
    form_id: int,
) -> RentalApplicationForm:
    form = await db.get(RentalApplicationForm, form_id)
    if not form:
        raise NotFoundException(detail="Application form not found")
    await assert_can_manage_owner_portfolio(db, actor=actor, owner_id=form.owner_id)
    return form


async def get_public_application_form_by_slug(
    db: AsyncSession,
    *,
    slug: str,
) -> RentalApplicationForm:
    stmt = select(RentalApplicationForm).where(RentalApplicationForm.slug == slug)
    res = await db.execute(stmt)
    form = res.scalar_one_or_none()
    if not form or not form.is_active:
        raise NotFoundException(detail="Application form not found")
    return form


async def submit_public_application(
    db: AsyncSession,
    *,
    slug: str,
    property_id: int | None = None,
    applicant_full_name: str | None = None,
    applicant_phone: str | None = None,
    applicant_email: str | None = None,
    answers: dict | None = None,
    application_data: dict | None = None,
    emergency_contacts: dict | None = None,
) -> RentalApplication:
    form = await get_public_application_form_by_slug(db, slug=slug)

    effective_property_id = property_id or form.property_id
    if effective_property_id is None:
        raise BadRequestException(detail="property_id is required for this form")

    application = RentalApplication(
        form_id=form.id,
        property_id=effective_property_id,
        owner_id=form.owner_id,
        status=TenantStatus.applicant,
        applicant_full_name=applicant_full_name,
        applicant_phone=applicant_phone,
        applicant_email=applicant_email,
        answers=answers,
        application_data=application_data,
        emergency_contacts=emergency_contacts,
        submitted_at=datetime.now(timezone.utc),
    )
    db.add(application)
    await db.flush()
    await db.refresh(application)
    return application


async def decide_application(
    db: AsyncSession,
    *,
    actor: User,
    application_id: int,
    decision: TenantStatus,
) -> RentalApplication:
    if decision not in {TenantStatus.approved, TenantStatus.rejected}:
        raise BadRequestException(detail="decision must be approved or rejected")

    application = await db.get(RentalApplication, application_id)
    if not application:
        raise NotFoundException(detail="Application not found")

    await assert_can_manage_owner_portfolio(db, actor=actor, owner_id=application.owner_id)

    application.status = decision
    application.decision_at = datetime.now(timezone.utc)
    application.decided_by_user_id = actor.id
    await db.flush()
    await db.refresh(application)
    return application


async def list_application_forms(
    db: AsyncSession,
    *,
    actor: User,
    owner_id: int | None = None,
    property_id: int | None = None,
    q: str | None = None,
    cursor_payload: dict,
    limit: int = 20,
    with_total: bool = False,
) -> tuple[list[RentalApplicationForm], dict | None, int | None]:
    if actor.role == UserRole.user.value:
        owner_id = actor.id
    elif actor.role == UserRole.agent.value:
        if owner_id is None:
            raise InsufficientPermissionsError("owner_id is required for agents")
    if owner_id is not None:
        await assert_can_manage_owner_portfolio(db, actor=actor, owner_id=owner_id)

    stmt = select(RentalApplicationForm)
    if owner_id is not None:
        stmt = stmt.where(RentalApplicationForm.owner_id == owner_id)
    if property_id is not None:
        stmt = stmt.where(RentalApplicationForm.property_id == property_id)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(RentalApplicationForm.title.ilike(like))

    count_total: int | None = None
    if with_total:
        count_stmt = select(func.count()).select_from(stmt.subquery())
        count_total = (await db.execute(count_stmt)).scalar_one()

    predicate = keyset_filter(
        RentalApplicationForm.created_at,
        RentalApplicationForm.id,
        cursor_payload,
        descending=True,
    )
    if predicate is not None:
        stmt = stmt.where(predicate)

    stmt = stmt.order_by(
        desc(RentalApplicationForm.created_at),
        desc(RentalApplicationForm.id),
    ).limit(limit + 1)
    rows = list((await db.execute(stmt)).scalars().all())

    next_payload: dict | None = None
    if len(rows) > limit:
        rows = rows[:limit]
        last = rows[-1]
        next_payload = keyset_payload(keyset_sort_value(last.created_at), last.id)
    return rows, next_payload, count_total


async def list_applications(
    db: AsyncSession,
    *,
    actor: User,
    owner_id: int | None = None,
    property_id: int | None = None,
    status: TenantStatus | None = None,
    submitted_from: datetime | None = None,
    submitted_to: datetime | None = None,
    cursor_payload: dict,
    limit: int = 20,
    with_total: bool = False,
) -> tuple[list[RentalApplication], dict | None, int | None]:
    if actor.role == UserRole.user.value:
        owner_id = actor.id
    elif actor.role == UserRole.agent.value:
        if owner_id is None:
            raise InsufficientPermissionsError("owner_id is required for agents")
    if owner_id is not None:
        await assert_can_manage_owner_portfolio(db, actor=actor, owner_id=owner_id)

    stmt = select(RentalApplication)
    if owner_id is not None:
        stmt = stmt.where(RentalApplication.owner_id == owner_id)
    if property_id is not None:
        stmt = stmt.where(RentalApplication.property_id == property_id)
    if status is not None:
        stmt = stmt.where(RentalApplication.status == status)
    if submitted_from is not None:
        stmt = stmt.where(RentalApplication.submitted_at >= submitted_from)
    if submitted_to is not None:
        stmt = stmt.where(RentalApplication.submitted_at <= submitted_to)

    count_total: int | None = None
    if with_total:
        count_stmt = select(func.count()).select_from(stmt.subquery())
        count_total = (await db.execute(count_stmt)).scalar_one()

    offset = read_offset(cursor_payload)
    stmt = (
        stmt.order_by(desc(RentalApplication.submitted_at), desc(RentalApplication.created_at))
        .offset(offset)
        .limit(limit + 1)
    )
    rows = list((await db.execute(stmt)).scalars().all())
    next_p = offset_payload(offset + limit) if len(rows) > limit else None
    rows = rows[:limit]
    return rows, next_p, count_total


async def get_application(
    db: AsyncSession,
    *,
    actor: User,
    application_id: int,
) -> RentalApplication:
    application = await db.get(RentalApplication, application_id)
    if not application:
        raise NotFoundException(detail="Application not found")
    await assert_can_manage_owner_portfolio(db, actor=actor, owner_id=application.owner_id)
    return application
