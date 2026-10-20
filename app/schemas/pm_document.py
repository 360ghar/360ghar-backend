from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict

from app.models.enums import DocumentType
from app.schemas.base import NotNullable, PatchModel, UtcDateTime


class DocumentUpdate(PatchModel):
    title: Annotated[str | None, NotNullable] = None
    shared_with_tenant: Annotated[bool | None, NotNullable] = None
    shared_with_agent: Annotated[bool | None, NotNullable] = None


class Document(BaseModel):
    """A document row. ``file_url`` is set only for viewers who may open the file; otherwise null."""

    id: int
    owner_id: int
    user_id: int | None = None
    property_id: int | None = None
    lease_id: int | None = None
    maintenance_request_id: int | None = None
    rental_application_id: int | None = None
    document_type: DocumentType
    title: str
    file_url: str | None = None
    mime_type: str | None = None
    file_size: int | None = None
    shared_with_tenant: bool
    shared_with_agent: bool
    created_by_user_id: int | None = None
    created_at: UtcDateTime
    updated_at: UtcDateTime | None = None

    model_config = ConfigDict(from_attributes=True)


class DocumentDownload(BaseModel):
    url: str
