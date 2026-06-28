from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

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
    tour_id: str | None = None
    filename: str
    original_filename: str | None = None
    file_url: str
    thumbnail_url: str | None = None
    cdn_url: str | None = None
    file_size: int
    mime_type: str
    width: int | None = None
    height: int | None = None
    duration: int | None = None
    folder: str | None = None
    visibility: str
    is_processed: bool
    processing_metadata: dict[str, Any] | list[Any] | None = None
    created_at: datetime
    expires_at: datetime | None = None
    # New tracking fields
    upload_status: str | None = "complete"
    bucket_name: str | None = None
    storage_path: str | None = None

    model_config = ConfigDict(from_attributes=True)


class MediaUpdateRequest(BaseModel):
    thumbnail_url: str | None = Field(default=None, max_length=512)
    cdn_url: str | None = Field(default=None, max_length=512)
    visibility: str | None = None
    is_processed: bool | None = None
    processing_metadata: dict[str, Any] | None = None
    expires_at: datetime | None = None


class PresignedUploadItem(BaseModel):
    """Request item for presigned upload URL generation.

    Specify folder_type to determine the storage path structure.
    """
    filename: str = Field(..., description="Original filename including extension", examples=["living-room.jpg"])
    content_type: str | None = Field(default=None, description="MIME type of the file", examples=["image/jpeg"])
    file_size: int | None = Field(default=None, description="File size in bytes", examples=[102400])
    folder_type: StorageFolderType = Field(default=StorageFolderType.GENERIC, description="Storage folder determining the path structure", examples=["property_image"])
    # Context IDs needed for specific folder types
    property_id: int | None = Field(default=None, description="Required for property_* folder types", examples=[1])  # Required for property_* folder types
    tour_id: str | None = Field(default=None, description="Required for tour/scene folder types", examples=["tour_abc123"])  # Required for tour/scene folder types
    scene_id: str | None = Field(default=None, description="Required for scene folder type", examples=["scene_xyz789"])  # Required for scene folder type
    visibility: str | None = Field(default="private", description="Object visibility (public or private)", examples=["private"])

    # Deprecated: Use folder_type instead
    folder: str | None = None


class PresignedUploadRequest(BaseModel):
    files: list[PresignedUploadItem]


class PresignedUploadResponseItem(BaseModel):
    """Response item with signed URL for direct client upload.

    The upload_id can be used to confirm the upload after completion.
    The client should POST a multipart form to ``signed_url`` with the
    file plus ``api_key``, ``signature``, ``timestamp``, and ``public_id``
    fields.
    """
    upload_id: str  # MediaFile ID for confirmation
    signed_url: str
    token: str  # Cloudinary upload signature
    api_key: str | None = None
    timestamp: int | None = None
    public_id: str | None = None
    path: str
    public_url: str


class PresignedUploadResponse(BaseModel):
    items: list[PresignedUploadResponseItem]


class UploadConfirmRequest(BaseModel):
    """Request to confirm a client-side upload completed."""
    pass  # upload_id comes from URL path


class UploadConfirmResponse(BaseModel):
    """Response after confirming an upload."""
    media: MediaFileResponse
    message: str = "Upload confirmed successfully"


class BatchDeleteRequest(BaseModel):
    """Request payload for bulk media deletion."""
    media_ids: list[str] = Field(
        ...,
        min_length=1,
        max_length=50,
        description="Media file IDs to delete (max 50)",
    )


class BatchDeleteResponse(BaseModel):
    """Response payload for bulk media deletion."""
    deleted: list[str] = Field(default_factory=list, description="IDs successfully deleted")
    failed: list[str] = Field(
        default_factory=list,
        description="IDs that could not be deleted (not found or not owned by the caller)",
    )
    storage_warnings: list[str] = Field(
        default_factory=list,
        description="IDs whose DB record was deleted but the underlying storage object could not be removed",
    )
