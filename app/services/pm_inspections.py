from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BadRequestException, InsufficientPermissionsError, NotFoundException
from app.models.enums import InspectionType, UserRole
from app.models.pm_documents import Document
from app.models.pm_inspections import InspectionChecklist
from app.models.pm_leases import Lease
from app.models.users import User
from app.schemas.pagination import keyset_filter, keyset_payload, keyset_sort_value
from app.services.pm_authz import (
    assert_can_access_lease,
    assert_can_manage_owner_portfolio,
    assert_owned_reference,
)


async def create_inspection_checklist(
    db: AsyncSession,
    *,
    actor: User,
    owner_id: int,
    lease_id: int,
    inspection_type: InspectionType,
    rooms_data: dict | None = None,
    overall_notes: str | None = None,
    conducted_at: datetime | None = None,
) -> InspectionChecklist:
    await assert_can_manage_owner_portfolio(db, actor=actor, owner_id=owner_id)
    lease = await assert_can_access_lease(db, actor=actor, lease_id=lease_id)
    if lease.owner_id != owner_id and actor.role != UserRole.admin.value:
        raise BadRequestException(detail="lease_id does not belong to owner_id")

    checklist = InspectionChecklist(
        property_id=lease.property_id,
        lease_id=lease.id,
        owner_id=owner_id,
        inspection_type=inspection_type,
        conducted_by_user_id=actor.id,
        conducted_at=conducted_at or datetime.now(timezone.utc),
        rooms_data=rooms_data,
        overall_notes=overall_notes,
    )
    db.add(checklist)
    await db.flush()
    await db.refresh(checklist)
    return checklist


async def list_inspections(
    db: AsyncSession,
    *,
    actor: User,
    as_tenant: bool = False,
    owner_id: int | None = None,
    lease_id: int | None = None,
    property_id: int | None = None,
    cursor_payload: dict,
    limit: int = 20,
    with_total: bool = False,
) -> tuple[list[InspectionChecklist], dict | None, int | None]:
    if as_tenant:
        # Checklists on leases where the caller is the tenant.
        if actor.role != UserRole.user.value:
            raise InsufficientPermissionsError("Only user role can view as tenant")
        owner_id = None
    elif actor.role == UserRole.user.value:
        owner_id = actor.id
    elif actor.role == UserRole.agent.value:
        if owner_id is None:
            raise InsufficientPermissionsError("owner_id is required for agents")
    if owner_id is not None:
        await assert_can_manage_owner_portfolio(db, actor=actor, owner_id=owner_id)

    stmt = select(InspectionChecklist)
    if as_tenant:
        stmt = stmt.where(
            InspectionChecklist.lease_id.in_(
                select(Lease.id).where(Lease.tenant_user_id == actor.id)
            )
        )
    if owner_id is not None:
        stmt = stmt.where(InspectionChecklist.owner_id == owner_id)
    if lease_id is not None:
        stmt = stmt.where(InspectionChecklist.lease_id == lease_id)
    if property_id is not None:
        stmt = stmt.where(InspectionChecklist.property_id == property_id)

    count_total = None
    if with_total:
        count_stmt = select(func.count()).select_from(stmt.subquery())
        count_total = (await db.execute(count_stmt)).scalar_one()

    predicate = keyset_filter(
        InspectionChecklist.conducted_at, InspectionChecklist.id, cursor_payload, descending=True
    )
    if predicate is not None:
        stmt = stmt.where(predicate)

    stmt = stmt.order_by(
        InspectionChecklist.conducted_at.desc(), InspectionChecklist.id.desc()
    ).limit(limit + 1)
    rows = list((await db.execute(stmt)).scalars().all())

    next_payload = None
    if len(rows) > limit:
        rows = rows[:limit]
        last = rows[-1]
        next_payload = keyset_payload(keyset_sort_value(last.conducted_at), last.id)
    return rows, next_payload, count_total


async def get_inspection(
    db: AsyncSession,
    *,
    actor: User,
    inspection_id: int,
) -> InspectionChecklist:
    checklist = await db.get(InspectionChecklist, inspection_id)
    if not checklist:
        raise NotFoundException(detail="Inspection checklist not found")

    if actor.role == UserRole.admin.value:
        return checklist

    # The tenant on the lease can read the checklist they are asked to sign.
    lease = await db.get(Lease, checklist.lease_id)
    if lease is not None and lease.tenant_user_id == actor.id:
        return checklist

    await assert_can_manage_owner_portfolio(db, actor=actor, owner_id=checklist.owner_id)
    return checklist


async def sign_inspection(
    db: AsyncSession,
    *,
    actor: User,
    inspection_id: int,
    tenant_signature_document_id: int | None = None,
    owner_signature_document_id: int | None = None,
) -> InspectionChecklist:
    checklist = await db.get(InspectionChecklist, inspection_id)
    if not checklist:
        raise NotFoundException(detail="Inspection checklist not found")

    lease = await db.get(Lease, checklist.lease_id)
    if not lease:
        raise NotFoundException(detail="Lease not found")

    now = datetime.now(timezone.utc)

    # Tenant can only attach tenant signature; owner can attach owner signature.
    if tenant_signature_document_id is not None:
        if lease.tenant_user_id != actor.id:
            raise InsufficientPermissionsError("Only the tenant can sign as tenant")
        # The tenant signs with a document the tenant uploaded.
        await assert_owned_reference(
            db,
            model=Document,
            ref_id=tenant_signature_document_id,
            owner_id=actor.id,
            label="Document",
        )
        checklist.tenant_signature_document_id = tenant_signature_document_id
        checklist.signed_by_tenant_at = now

    if owner_signature_document_id is not None:
        await assert_can_manage_owner_portfolio(db, actor=actor, owner_id=checklist.owner_id)
        await assert_owned_reference(
            db,
            model=Document,
            ref_id=owner_signature_document_id,
            owner_id=checklist.owner_id,
            label="Document",
        )
        checklist.owner_signature_document_id = owner_signature_document_id
        checklist.signed_by_owner_at = now

    if tenant_signature_document_id is None and owner_signature_document_id is None:
        # Empty sign: the acting party signs without a document. The tenant on the lease signs
        # as tenant. Anyone else must manage the owner's portfolio and signs as owner.
        if lease.tenant_user_id == actor.id:
            checklist.signed_by_tenant_at = now
        else:
            await assert_can_manage_owner_portfolio(db, actor=actor, owner_id=checklist.owner_id)
            checklist.signed_by_owner_at = now

    await db.flush()
    await db.refresh(checklist)
    return checklist
