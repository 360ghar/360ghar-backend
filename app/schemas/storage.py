from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class MediaFileResponse(BaseModel):
    id: str
    user_id: int
    tour_id: Optional[str] = None
    filename: str
    original_filename: Optional[str] = None
    file_url: str
    thumbnail_url: Optional[str] = None
    cdn_url: Optional[str] = None
    file_size: int
    mime_type: str
    width: Optional[int] = None
    height: Optional[int] = None
    duration: Optional[int] = None
    folder: Optional[str] = None
    visibility: str
    is_processed: bool
    processing_metadata: Optional[Dict[str, Any]] = None
    created_at: datetime
    expires_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class MediaListResponse(BaseModel):
    items: List[MediaFileResponse]
    total: int
    page: int
    page_size: int
    total_pages: int


class MediaUpdateRequest(BaseModel):
    thumbnail_url: Optional[str] = Field(default=None, max_length=512)
    cdn_url: Optional[str] = Field(default=None, max_length=512)
    visibility: Optional[str] = None
    is_processed: Optional[bool] = None
    processing_metadata: Optional[Dict[str, Any]] = None
    expires_at: Optional[datetime] = None


class PresignedUploadItem(BaseModel):
    filename: str
    content_type: Optional[str] = None
    file_size: Optional[int] = None
    folder: Optional[str] = None
    tour_id: Optional[str] = None
    visibility: Optional[str] = "private"


class PresignedUploadRequest(BaseModel):
    files: List[PresignedUploadItem]


class PresignedUploadResponseItem(BaseModel):
    signed_url: str
    token: str
    path: str
    public_url: str
    media: Optional[MediaFileResponse] = None


class PresignedUploadResponse(BaseModel):
    items: List[PresignedUploadResponseItem]
