from __future__ import annotations

import secrets
from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Literal

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BadRequestException, InsufficientPermissionsError, NotFoundException
from app.models.enums import RentalApplicationStatus, UserRole
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
from app.services.pm.rent_rules import money
from app.services.pm_authz import assert_can_manage_owner_portfolio


def _new_slug() -> str:
    # URL-safe, short, non-guessable token (public endpoint identifier)
    return secrets.token_urlsafe(8).rstrip("=")


def _now() -> datetime:
    return datetime.now(UTC)


async def _attach_property_labels(db: AsyncSession, objs: Sequence[Any]) -> None:
    """Set transient ``property_name`` and ``property_address`` from one query."""
    ids = {o.property_id for o in objs if getattr(o, "property_id", None) is not None}
    if not ids:
        for o in objs:
            o.property_name = None
            o.property_address = None
        return
    rows = (
        await db.execute(
            select(Property.id, Property.title, Property.full_address).where(Property.id.in_(ids))
        )
    ).all()
    labels = {pid: (title, address) for pid, title, address in rows}
    for o in objs:
        name, address = labels.get(o.property_id, (None, None))
        o.property_name = name
        o.property_address = address


async def create_application_form(
    db: AsyncSession,
    *,
    actor: User,
    owner_id: int,
    title: str,
    description: str | None = None,
    property_id: int | None = None,
    application_fee_amount: Decimal | float | None = None,
    required_document_types: dict | None = None,
    custom_fields: list[dict] | None = None,
    is_active: bool = True,
    expires_at: datetime | None = None,
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
        is_active=is_active,
        expires_at=expires_at,
        application_fee_amount=None
        if application_fee_amount is None
        else money(application_fee_amount),
        required_document_types=required_document_types,
        # Stored as the questions JSON column. The API name is custom_fields.
        questions=custom_fields,
        config=config,
    )
    db.add(form)
    await db.flush()
    await db.refresh(form)
    await _attach_property_labels(db, [form])
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
    await _attach_property_labels(db, [form])
    return form


def _is_open(form: RentalApplicationForm) -> bool:
    return form.is_active and (form.expires_at is None or form.expires_at > _now())


async def get_public_application_form_by_slug(
    db: AsyncSession,
    *,
    slug: str,
) -> RentalApplicationForm:
    stmt = select(RentalApplicationForm).where(RentalApplicationForm.slug == slug)
    res = await db.execute(stmt)
    form = res.scalar_one_or_none()
    if not form or not _is_open(form):
        raise NotFoundException(detail="Application form not found")
    await _attach_property_labels(db, [form])
    return form


def _check_required_answers(form: RentalApplicationForm, answers: dict[str, Any] | None) -> None:
    for field in form.questions or []:
        if not isinstance(field, dict) or not field.get("is_required"):
            continue
        value = (answers or {}).get(str(field.get("id")))
        if value is None or (isinstance(value, str) and not value.strip()):
            raise BadRequestException(detail=f"Answer required: {field.get('id')}")


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
    """Record an anonymous application.

    A form tied to a property ignores ``property_id`` from the request. An untied
    form needs a ``property_id`` that exists and belongs to the form owner. Otherwise
    the answer is 404, the same for unknown and foreign ids.
    """
    form = await get_public_application_form_by_slug(db, slug=slug)

    if form.property_id is not None:
        effective_property_id = form.property_id
    else:
        if property_id is None:
            raise BadRequestException(detail="property_id is required for this form")
        prop = await db.get(Property, property_id)
        if prop is None or prop.owner_id != form.owner_id:
            raise NotFoundException(detail="Property not found")
        effective_property_id = prop.id

    _check_required_answers(form, answers)

    application = RentalApplication(
        form_id=form.id,
        property_id=effective_property_id,
        owner_id=form.owner_id,
        status=RentalApplicationStatus.applicant,
        applicant_full_name=applicant_full_name,
        applicant_phone=applicant_phone,
        applicant_email=applicant_email,
        answers=answers,
        application_data=application_data,
        emergency_contacts=emergency_contacts,
        submitted_at=_now(),
    )
    db.add(application)
    await db.flush()
    await db.refresh(application)
    await _attach_property_labels(db, [application])
    return application


async def decide_application(
    db: AsyncSession,
    *,
    actor: User,
    application_id: int,
    decision: Literal["approved", "rejected"],
    notes: str | None = None,
) -> RentalApplication:
    application = await db.get(RentalApplication, application_id)
    if not application:
        raise NotFoundException(detail="Application not found")

    await assert_can_manage_owner_portfolio(db, actor=actor, owner_id=application.owner_id)

    application.status = RentalApplicationStatus(decision)
    application.decision_at = _now()
    application.decided_by_user_id = actor.id
    application.decision_notes = notes
    await db.flush()
    await db.refresh(application)
    await _attach_property_labels(db, [application])
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
    await _attach_property_labels(db, rows)
    return rows, next_payload, count_total


async def list_applications(
    db: AsyncSession,
    *,
    actor: User,
    owner_id: int | None = None,
    property_id: int | None = None,
    form_id: int | None = None,
    status: RentalApplicationStatus | None = None,
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
    if form_id is not None:
        stmt = stmt.where(RentalApplication.form_id == form_id)
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
    await _attach_property_labels(db, rows)
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
    await _attach_property_labels(db, [application])
    return application
