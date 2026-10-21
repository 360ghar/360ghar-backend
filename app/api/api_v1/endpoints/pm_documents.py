from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.api_v1.dependencies.auth import get_current_active_user
from app.core.database import get_db
from app.core.exceptions import InsufficientPermissionsError
from app.models.enums import DocumentType, UserRole
from app.models.pm_documents import Document as DocumentModel
from app.models.users import User
from app.schemas.pagination import CursorPage, CursorParams, build_cursor_page
from app.schemas.pm_document import Document as DocumentSchema
from app.schemas.pm_document import DocumentDownload, DocumentUpdate
from app.services.pm_documents import (
    assert_can_access_document,
    create_document,
    list_documents,
    store_private_document,
    update_document,
    viewer_file_url,
)

router = APIRouter()


async def _to_schema(db: AsyncSession, doc: DocumentModel, actor: User) -> DocumentSchema:
    """Document response with file_url only for viewers who may open the file."""
    out = DocumentSchema.model_validate(doc)
    return out.model_copy(update={"file_url": await viewer_file_url(db, doc=doc, actor=actor)})


@router.post(
    "/upload",
    response_model=DocumentSchema,
    status_code=status.HTTP_201_CREATED,
    summary="Upload property document",
)
async def upload_document(
    file: UploadFile = File(...),
    document_type: DocumentType = Form(...),
    title: str | None = Form(None, description="Defaults to the file name"),
    owner_id: int | None = Form(None),
    user_id: int | None = Form(None),
    property_id: int | None = Form(None),
    lease_id: int | None = Form(None),
    maintenance_request_id: int | None = Form(None),
    rental_application_id: int | None = Form(None),
    shared_with_tenant: bool = Form(False),
    shared_with_agent: bool = Form(False),
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Upload a private property document. The file is stored as an authenticated Cloudinary asset."""
    target_owner_id = current_user.id
    if owner_id is not None:
        if current_user.role in (UserRole.admin.value, UserRole.agent.value):
            target_owner_id = owner_id
        else:
            raise InsufficientPermissionsError("Only admins/agents can set owner_id")

    stored = await store_private_document(file, owner_id=target_owner_id)
    doc = await create_document(
        db,
        actor=current_user,
        owner_id=target_owner_id,
        document_type=document_type,
        title=title or file.filename or document_type.value,
        file_url=stored["file_url"],
        file_path=stored["file_path"],
        mime_type=stored["mime_type"],
        file_size=stored["file_size"],
        user_id=user_id,
        property_id=property_id,
        lease_id=lease_id,
        maintenance_request_id=maintenance_request_id,
        rental_application_id=rental_application_id,
        shared_with_tenant=shared_with_tenant,
        shared_with_agent=shared_with_agent,
    )
    return await _to_schema(db, doc, current_user)


@router.get("", response_model=CursorPage[DocumentSchema], summary="List property documents")
async def get_documents(
    as_tenant: bool = Query(
        False, description="If true, return documents shared with the caller on leases they hold"
    ),
    owner_id: int | None = Query(None),
    property_id: int | None = Query(None),
    lease_id: int | None = Query(None),
    user_id: int | None = Query(None),
    maintenance_request_id: int | None = Query(None),
    rental_application_id: int | None = Query(None),
    document_type: DocumentType | None = Query(None),
    page: CursorParams = Depends(),
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """List property documents. Agents see only documents shared with them."""
    filters = {
        "as_tenant": as_tenant,
        "owner_id": owner_id,
        "property_id": property_id,
        "lease_id": lease_id,
        "user_id": user_id,
        "maintenance_request_id": maintenance_request_id,
        "rental_application_id": rental_application_id,
        "document_type": document_type,
    }
    docs, next_payload, total = await list_documents(
        db,
        actor=current_user,
        as_tenant=as_tenant,
        owner_id=owner_id,
        property_id=property_id,
        lease_id=lease_id,
        user_id=user_id,
        maintenance_request_id=maintenance_request_id,
        rental_application_id=rental_application_id,
        document_type=document_type,
        cursor_payload=page.decoded(filters),
        limit=page.limit,
        with_total=page.include_total,
    )
    items = [await _to_schema(db, d, current_user) for d in docs]
    return build_cursor_page(
        items, limit=page.limit, next_payload=next_payload, total=total, filters=filters
    )


@router.get("/{document_id}", response_model=DocumentSchema, summary="Get property document")
async def get_document(
    document_id: int,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Get property document metadata."""
    doc = await assert_can_access_document(db, actor=current_user, document_id=document_id)
    return await _to_schema(db, doc, current_user)


@router.patch(
    "/{document_id}", response_model=DocumentSchema, summary="Update property document metadata"
)
async def patch_document(
    document_id: int,
    payload: DocumentUpdate,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Update property document metadata. Tenants get 403."""
    doc = await update_document(
        db,
        actor=current_user,
        document_id=document_id,
        title=payload.title,
        shared_with_tenant=payload.shared_with_tenant,
        shared_with_agent=payload.shared_with_agent,
    )
    return await _to_schema(db, doc, current_user)


@router.get(
    "/{document_id}/download", response_model=DocumentDownload, summary="Download property document"
)
async def download_document(
    document_id: int,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Get a delivery URL for a document the caller may open."""
    doc = await assert_can_access_document(db, actor=current_user, document_id=document_id)
    url = await viewer_file_url(db, doc=doc, actor=current_user)
    if url is None:
        raise InsufficientPermissionsError("Not authorized to access this document")
    return DocumentDownload(url=url)
