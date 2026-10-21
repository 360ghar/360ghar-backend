from __future__ import annotations

from typing import Any

from fastapi import UploadFile
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    BadRequestException,
    InsufficientPermissionsError,
    NotFoundException,
)
from app.models.enums import DocumentType, UserRole
from app.models.pm_documents import Document
from app.models.pm_leases import Lease
from app.models.pm_maintenance import MaintenanceRequest
from app.models.pm_tenants import RentalApplication
from app.models.properties import Property
from app.models.users import User
from app.schemas.pagination import offset_payload, read_offset
from app.services.cloudinary import get_cloudinary_service
from app.services.cloudinary.service import delivery_from_url, resource_type_for
from app.services.pm_authz import assert_can_manage_owner_portfolio, assert_owned_reference
from app.services.storage.helpers import (
    expected_type_from_content_type,
    is_valid_upload,
    read_upload_file_limited,
    validate_magic_bytes,
)
from app.services.storage_paths import StorageFolder, generate_cloudinary_public_id

# Documents are private Cloudinary uploads (type "authenticated"). Keep the limit in step with uploads.
PRIVATE_DOCUMENT_MAX_BYTES = 25 * 1024 * 1024


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


async def assert_owned_document(db: AsyncSession, *, document_id: int, owner_id: int) -> Document:
    """A referenced document must exist and belong to the same owner. Unknown ids give 404; foreign ids give 403."""
    return await assert_owned_reference(
        db, model=Document, ref_id=document_id, owner_id=owner_id, label="Document"
    )


async def store_private_document(file: UploadFile, *, owner_id: int) -> dict[str, Any]:
    """Validate and upload a document as a private Cloudinary asset.

    Returns the storage fields for ``create_document``: file_path (public id),
    file_url (the stored secure URL, not a delivery URL), mime_type and file_size.
    """
    if not is_valid_upload(file, allow_documents=True):
        raise BadRequestException(detail="Invalid file type", error_code="INVALID_FILE_TYPE")

    content = await read_upload_file_limited(file, PRIVATE_DOCUMENT_MAX_BYTES)
    expected_type = expected_type_from_content_type(file.content_type)
    if expected_type and not validate_magic_bytes(content, expected_type):
        raise BadRequestException(detail="Invalid file type", error_code="INVALID_FILE_TYPE")

    content_type = file.content_type or "application/octet-stream"
    public_id = generate_cloudinary_public_id(
        folder=StorageFolder.DOCUMENT_GENERAL,
        original_filename=file.filename,
        user_id=owner_id,
    )
    result = get_cloudinary_service().upload_file(
        file_bytes=content,
        public_id=public_id.split("/")[-1],
        folder="/".join(public_id.split("/")[:-1]),
        content_type=content_type,
        is_image=False,
        type="authenticated",
        # Explicit, so the upload never falls back to "auto" (PDFs would then land under image).
        resource_type=resource_type_for(content_type),
    )
    return {
        "file_path": result["public_id"],
        "file_url": result["secure_url"],
        "mime_type": content_type,
        "file_size": result.get("bytes") or len(content),
    }


async def viewer_file_url(db: AsyncSession, *, doc: Document, actor: User) -> str | None:
    """The file URL this viewer may see, or None. Owners and admins see every file.

    Agents see files shared with agents, and only for owners assigned to them. Tenants see
    files shared with tenants on their lease. The helper checks each rule itself, so it is safe
    to call without a prior access check.
    """
    if actor.role == UserRole.admin.value or doc.owner_id == actor.id:
        pass
    elif actor.role == UserRole.agent.value:
        if not doc.shared_with_agent or actor.agent_id is None:
            return None
        owner = await db.get(User, doc.owner_id)
        if owner is None or owner.agent_id != actor.agent_id:
            return None
    else:
        if not (doc.shared_with_tenant and doc.lease_id):
            return None
        lease = await db.get(Lease, doc.lease_id)
        if lease is None or lease.tenant_user_id != actor.id:
            return None

    # Sign with the resource type Cloudinary stored the asset under (read from its URL), so the
    # signed URL points at the same resource. Only authenticated assets are signed; older public
    # uploads keep their stored URL.
    stored = delivery_from_url(doc.file_url)
    if doc.file_path and stored is not None and stored[1] == "authenticated":
        return get_cloudinary_service().private_delivery_url(doc.file_path, resource_type=stored[0])
    return doc.file_url


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

    # Every linked record must exist and belong to the owner (404 unknown, 403 foreign).
    # A tenant may link a lease or request they are party to, so those checks also accept
    # the tenant on the record.
    if property_id is not None:
        await assert_owned_reference(
            db, model=Property, ref_id=property_id, owner_id=owner_id, label="Property"
        )
    if lease_id is not None:
        await assert_owned_reference(
            db,
            model=Lease,
            ref_id=lease_id,
            owner_id=owner_id,
            label="Lease",
            party_attr="tenant_user_id",
        )
    if maintenance_request_id is not None:
        await assert_owned_reference(
            db,
            model=MaintenanceRequest,
            ref_id=maintenance_request_id,
            owner_id=owner_id,
            label="Maintenance request",
            party_attr="tenant_user_id",
        )
    if rental_application_id is not None:
        await assert_owned_reference(
            db,
            model=RentalApplication,
            ref_id=rental_application_id,
            owner_id=owner_id,
            label="Rental application",
        )
    if user_id is not None and await db.get(User, user_id) is None:
        raise NotFoundException(detail="User not found")

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
    as_tenant: bool = False,
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
    if as_tenant:
        # Tenant view: documents the owner shared with the tenant, on leases the caller holds.
        if actor.role != UserRole.user.value:
            raise InsufficientPermissionsError("Only user role can view as tenant")
        effective_owner_id = None
    elif actor.role == UserRole.user.value:
        # In PM context, "owner list" means the caller's portfolio
        effective_owner_id = actor.id
    elif actor.role == UserRole.agent.value:
        if effective_owner_id is None:
            # Agents must filter by owner; otherwise they'd see too much.
            raise InsufficientPermissionsError("owner_id is required for agents")
    if effective_owner_id is not None:
        await assert_can_manage_owner_portfolio(db, actor=actor, owner_id=effective_owner_id)

    base_stmt = select(Document)
    if as_tenant:
        base_stmt = base_stmt.where(
            Document.shared_with_tenant.is_(True),
            Document.lease_id.in_(select(Lease.id).where(Lease.tenant_user_id == actor.id)),
        )
    if effective_owner_id is not None:
        base_stmt = base_stmt.where(Document.owner_id == effective_owner_id)
    if actor.role == UserRole.agent.value:
        # Agents see only the documents the owner shared with them.
        base_stmt = base_stmt.where(Document.shared_with_agent.is_(True))
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

    # Tenants can open shared documents but cannot change them. Owners, admins and agents
    # with share access can.
    if actor.role == UserRole.user.value and doc.owner_id != actor.id:
        raise InsufficientPermissionsError("Tenants cannot change document settings")

    if title is not None:
        doc.title = title
    if shared_with_tenant is not None:
        doc.shared_with_tenant = bool(shared_with_tenant)
    if shared_with_agent is not None:
        doc.shared_with_agent = bool(shared_with_agent)

    await db.flush()
    await db.refresh(doc)
    return doc
