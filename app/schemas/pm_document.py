from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import DocumentType


class DocumentCreate(BaseModel):
    owner_id: int | None = Field(default=None, description="Owner id (agent/admin only)")
    document_type: DocumentType
    title: str
    user_id: int | None = None
    property_id: int | None = None
    lease_id: int | None = None
    maintenance_request_id: int | None = None
    rental_application_id: int | None = None
    shared_with_tenant: bool = False
    shared_with_agent: bool = False


class Document(BaseModel):
    id: int
    owner_id: int
    user_id: int | None = None
    property_id: int | None = None
    lease_id: int | None = None
    maintenance_request_id: int | None = None
    rental_application_id: int | None = None
    document_type: DocumentType
    title: str
    file_url: str
    file_path: str | None = None
    mime_type: str | None = None
    file_size: int | None = None
    shared_with_tenant: bool
    shared_with_agent: bool
    version: int
    replaces_document_id: int | None = None
    created_by_user_id: int | None = None
    created_at: datetime
    updated_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class DocumentUpdate(BaseModel):
    title: str | None = None
    shared_with_tenant: bool | None = None
    shared_with_agent: bool | None = None


class DocumentDownload(BaseModel):
    url: str

