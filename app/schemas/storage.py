from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class StorageFolderType(str, Enum):
    """Client-facing folder type options for uploads.

    Maps to internal StorageFolder enum in storage_paths.py.
    """
    AVATAR = "avatar"
    PROPERTY_IMAGE = "property_image"
    PROPERTY_VIDEO = "property_video"
    PROPERTY_DOCUMENT = "property_document"
    TOUR = "tour"
    SCENE = "scene"
    DOCUMENT_LEASE = "document_lease"
    DOCUMENT_MAINTENANCE = "document_maintenance"
    DOCUMENT_GENERAL = "document_general"
    GENERIC = "generic"


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
    # New tracking fields
    upload_status: Optional[str] = "complete"
    bucket_name: Optional[str] = None
    storage_path: Optional[str] = None

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
    """Request item for presigned upload URL generation.

    Specify folder_type to determine the storage path structure.
    """
    filename: str
    content_type: Optional[str] = None
    file_size: Optional[int] = None
    folder_type: StorageFolderType = StorageFolderType.GENERIC
    # Context IDs needed for specific folder types
    property_id: Optional[int] = None  # Required for property_* folder types
    tour_id: Optional[str] = None  # Required for tour/scene folder types
    scene_id: Optional[str] = None  # Required for scene folder type
    visibility: Optional[str] = "private"

    # Deprecated: Use folder_type instead
    folder: Optional[str] = None


class PresignedUploadRequest(BaseModel):
    files: List[PresignedUploadItem]


class PresignedUploadResponseItem(BaseModel):
    """Response item with signed URL for direct client upload.

    The upload_id can be used to confirm the upload after completion.
    """
    upload_id: str  # MediaFile ID for confirmation
    signed_url: str
    token: str
    path: str
    public_url: str


class PresignedUploadResponse(BaseModel):
    items: List[PresignedUploadResponseItem]


class UploadConfirmRequest(BaseModel):
    """Request to confirm a client-side upload completed."""
    pass  # upload_id comes from URL path


class UploadConfirmResponse(BaseModel):
    """Response after confirming an upload."""
    media: MediaFileResponse
    message: str = "Upload confirmed successfully"
