from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, File, Form, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.api_v1.dependencies.auth import get_current_active_user
from app.core.database import get_db
from app.models.enums import DocumentType, UserRole
from app.schemas.pm_document import Document as DocumentSchema, DocumentDownload, DocumentUpdate
from app.schemas.user import User as UserSchema
from app.services.pm_documents import create_document, list_documents, update_document
from app.services.storage import storage_service

router = APIRouter()


@router.post("/upload", response_model=DocumentSchema)
async def upload_document(
    file: UploadFile = File(...),
    document_type: DocumentType = Form(...),
    title: str = Form(...),
    owner_id: Optional[int] = Form(None),
    user_id: Optional[int] = Form(None),
    property_id: Optional[int] = Form(None),
    lease_id: Optional[int] = Form(None),
    maintenance_request_id: Optional[int] = Form(None),
    rental_application_id: Optional[int] = Form(None),
    shared_with_tenant: bool = Form(False),
    shared_with_agent: bool = Form(False),
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    target_owner_id = current_user.id
    if owner_id is not None:
        if current_user.role in (UserRole.admin.value, UserRole.agent.value):
            target_owner_id = owner_id
        else:
            from app.core.exceptions import InsufficientPermissionsError

            raise InsufficientPermissionsError("Only admins/agents can set owner_id")

    upload_res = await storage_service.upload_document(
        file, folder=f"pm/{target_owner_id}", user_id=target_owner_id
    )

    doc = await create_document(
        db,
        actor=current_user,
        owner_id=target_owner_id,
        document_type=document_type,
        title=title,
        file_url=upload_res["public_url"],
        file_path=upload_res["file_path"],
        mime_type=upload_res.get("content_type"),
        file_size=upload_res.get("file_size"),
        user_id=user_id,
        property_id=property_id,
        lease_id=lease_id,
        maintenance_request_id=maintenance_request_id,
        rental_application_id=rental_application_id,
        shared_with_tenant=shared_with_tenant,
        shared_with_agent=shared_with_agent,
    )
    return DocumentSchema.model_validate(doc)


@router.get("", response_model=list[DocumentSchema])
async def get_documents(
    owner_id: Optional[int] = None,
    property_id: Optional[int] = None,
    lease_id: Optional[int] = None,
    user_id: Optional[int] = None,
    maintenance_request_id: Optional[int] = None,
    rental_application_id: Optional[int] = None,
    document_type: Optional[DocumentType] = None,
    limit: int = 50,
    offset: int = 0,
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    docs = await list_documents(
        db,
        actor=current_user,
        owner_id=owner_id,
        property_id=property_id,
        lease_id=lease_id,
        user_id=user_id,
        maintenance_request_id=maintenance_request_id,
        rental_application_id=rental_application_id,
        document_type=document_type,
        limit=limit,
        offset=offset,
    )
    return [DocumentSchema.model_validate(d) for d in docs]


@router.patch("/{document_id}", response_model=DocumentSchema)
async def patch_document(
    document_id: int,
    payload: DocumentUpdate,
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    doc = await update_document(
        db,
        actor=current_user,
        document_id=document_id,
        title=payload.title,
        shared_with_tenant=payload.shared_with_tenant,
        shared_with_agent=payload.shared_with_agent,
    )
    return DocumentSchema.model_validate(doc)


@router.get("/{document_id}/download", response_model=DocumentDownload)
async def download_document(
    document_id: int,
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    # MVP: return stored file_url; private buckets can be added later via signed URLs.
    from app.services.pm_documents import assert_can_access_document

    doc = await assert_can_access_document(db, actor=current_user, document_id=document_id)
    return DocumentDownload(url=doc.file_url)
