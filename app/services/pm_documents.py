from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import InsufficientPermissionsError, NotFoundException
from app.models.enums import DocumentType, UserRole
from app.models.pm_documents import Document
from app.models.pm_leases import Lease
from app.models.users import User
from app.schemas.pagination import offset_payload, read_offset
from app.services.pm_authz import assert_can_manage_owner_portfolio


async def assert_can_access_document(
    db: AsyncSession,
    *,
    actor: User,
    document_id: int,
) -> Document:
    doc = await db.get(Document, document_id)
    if not doc:
        raise NotFoundException(detail="Document not found")

    if actor.role == UserRole.admin.value:
        return doc

    # Owner access (portfolio owner context)
    if doc.owner_id == actor.id:
        return doc

    # Agent access: owner must be assigned to this agent
    if actor.role == UserRole.agent.value:
        if actor.agent_id is None:
            raise InsufficientPermissionsError("Agent is not linked to an agent profile")
        owner = await db.get(User, doc.owner_id)
        if owner and owner.agent_id == actor.agent_id and doc.shared_with_agent:
            return doc
        raise InsufficientPermissionsError("Not authorized to access this document")

    # Tenant access: only if explicitly shared and actor is the tenant on the linked lease
    if doc.shared_with_tenant and doc.lease_id:
        lease = await db.get(Lease, doc.lease_id)
        if lease and lease.tenant_user_id == actor.id:
            return doc

    raise InsufficientPermissionsError("Not authorized to access this document")


async def create_document(
    db: AsyncSession,
    *,
    actor: User,
    owner_id: int,
    document_type: DocumentType,
    title: str,
    file_url: str,
    file_path: str | None = None,
    mime_type: str | None = None,
    file_size: int | None = None,
    user_id: int | None = None,
    property_id: int | None = None,
    lease_id: int | None = None,
    maintenance_request_id: int | None = None,
    rental_application_id: int | None = None,
    shared_with_tenant: bool = False,
    shared_with_agent: bool = False,
) -> Document:
    await assert_can_manage_owner_portfolio(db, actor=actor, owner_id=owner_id)

    doc = Document(
        owner_id=owner_id,
        user_id=user_id,
        property_id=property_id,
        lease_id=lease_id,
        maintenance_request_id=maintenance_request_id,
        rental_application_id=rental_application_id,
        document_type=document_type,
        title=title,
        file_url=file_url,
        file_path=file_path,
        mime_type=mime_type,
        file_size=file_size,
        shared_with_tenant=bool(shared_with_tenant),
        shared_with_agent=bool(shared_with_agent),
        created_by_user_id=getattr(actor, "id", None),
    )
    db.add(doc)
    await db.flush()
    await db.refresh(doc)
    return doc


async def list_documents(
    db: AsyncSession,
    *,
    actor: User,
    owner_id: int | None = None,
    property_id: int | None = None,
    lease_id: int | None = None,
    user_id: int | None = None,
    maintenance_request_id: int | None = None,
    rental_application_id: int | None = None,
    document_type: DocumentType | None = None,
    cursor_payload: dict,
    limit: int = 20,
    with_total: bool = False,
) -> tuple[list[Document], dict | None, int | None]:
    # Determine effective owner scope
    effective_owner_id = owner_id
    if actor.role == UserRole.user.value:
        # In PM context, "owner list" means the caller's portfolio
        effective_owner_id = actor.id
    elif actor.role == UserRole.agent.value:
        if effective_owner_id is None:
            # Agents must filter by owner; otherwise they'd see too much.
            raise InsufficientPermissionsError("owner_id is required for agents")
    if effective_owner_id is not None:
        await assert_can_manage_owner_portfolio(db, actor=actor, owner_id=effective_owner_id)

    base_stmt = select(Document)
    if effective_owner_id is not None:
        base_stmt = base_stmt.where(Document.owner_id == effective_owner_id)
    if property_id is not None:
        base_stmt = base_stmt.where(Document.property_id == property_id)
    if lease_id is not None:
        base_stmt = base_stmt.where(Document.lease_id == lease_id)
    if user_id is not None:
        base_stmt = base_stmt.where(Document.user_id == user_id)
    if maintenance_request_id is not None:
        base_stmt = base_stmt.where(Document.maintenance_request_id == maintenance_request_id)
    if rental_application_id is not None:
        base_stmt = base_stmt.where(Document.rental_application_id == rental_application_id)
    if document_type is not None:
        base_stmt = base_stmt.where(Document.document_type == document_type)

    total: int | None = None
    if with_total:
        total = (
            await db.execute(select(func.count()).select_from(base_stmt.subquery()))
        ).scalar_one()

    offset = read_offset(cursor_payload)
    stmt = base_stmt.order_by(Document.created_at.desc()).offset(offset).limit(limit + 1)
    res = await db.execute(stmt)
    rows = list(res.scalars().all())

    has_more = len(rows) > limit
    rows = rows[:limit]
    next_payload = offset_payload(offset + limit) if has_more else None
    return rows, next_payload, total


async def update_document(
    db: AsyncSession,
    *,
    actor: User,
    document_id: int,
    title: str | None = None,
    shared_with_tenant: bool | None = None,
    shared_with_agent: bool | None = None,
) -> Document:
    doc = await assert_can_access_document(db, actor=actor, document_id=document_id)

    # Only owners/admin/agents with agent-share may update share flags
    if actor.role not in {UserRole.admin.value, UserRole.user.value, UserRole.agent.value}:
        raise InsufficientPermissionsError("Not authorized to update documents")

    if title is not None:
        doc.title = title
    if shared_with_tenant is not None:
        doc.shared_with_tenant = bool(shared_with_tenant)
    if shared_with_agent is not None:
        doc.shared_with_agent = bool(shared_with_agent)

    await db.flush()
    await db.refresh(doc)
    return doc
