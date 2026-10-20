from __future__ import annotations

from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import AfterValidator, BaseModel, ConfigDict, Field

from app.models.enums import StorageFolderType, TourVisibility, UploadStatus
from app.schemas.base import NotNullable, PatchModel, UtcDateTime, WriteModel


def _validate_absolute_url(value: str | None) -> str | None:
    """Accept an absolute http(s) URL, or null. Other schemes are rejected."""
    if value is None:
        return None
    parts = urlsplit(value)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise ValueError("URL must be an absolute http or https URL")
    return value


_AbsoluteUrl = AfterValidator(_validate_absolute_url)


class MediaFileResponse(BaseModel):
    """A media library entry. Storage internals (storage_path, bucket_name) are not exposed."""

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
    folder: str | None = None
    visibility: TourVisibility
    is_processed: bool
    created_at: UtcDateTime
    expires_at: UtcDateTime | None = None
    upload_status: UploadStatus = UploadStatus.complete

    model_config = ConfigDict(from_attributes=True)


class MediaUpdateRequest(PatchModel):
    """PATCH body. Only the sent keys change. Explicit null clears a nullable field."""

    thumbnail_url: Annotated[str | None, _AbsoluteUrl] = Field(default=None, max_length=512)
    cdn_url: Annotated[str | None, _AbsoluteUrl] = Field(default=None, max_length=512)
    visibility: Annotated[TourVisibility | None, NotNullable] = None
    is_processed: Annotated[bool | None, NotNullable] = None
    expires_at: UtcDateTime | None = None


class PresignedUploadItem(WriteModel):
    """One file to presign. file_size is required and is checked again on confirm."""

    filename: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="Original filename including extension",
        examples=["living-room.jpg"],
    )
    content_type: str | None = Field(
        default=None, max_length=100, description="MIME type of the file", examples=["image/jpeg"]
    )
    file_size: int = Field(..., ge=0, description="File size in bytes", examples=[102400])
    folder_type: StorageFolderType = Field(
        default=StorageFolderType.GENERIC,
        description="Storage folder determining the path structure",
        examples=["property_image"],
    )
    property_id: int | None = Field(
        default=None, description="Required for property_* folder types", examples=[1]
    )
    tour_id: str | None = Field(
        default=None,
        description="Required for tour_* and scene folder types",
        examples=["tour_abc123"],
    )
    scene_id: str | None = Field(
        default=None, description="Required for the scene folder type", examples=["scene_xyz789"]
    )
    visibility: TourVisibility = Field(
        default=TourVisibility.private, description="Media library visibility", examples=["private"]
    )


class PresignedUploadRequest(WriteModel):
    files: list[PresignedUploadItem] = Field(..., min_length=1, max_length=20)


class PresignedUploadResponseItem(BaseModel):
    """Signed parameters for a direct client upload. Confirm with ``upload_id`` when done."""

    upload_id: str
    signed_url: str
    signature: str = Field(
        description="Cloudinary upload signature for api_key, timestamp and public_id"
    )
    api_key: str
    timestamp: int
    public_id: str
    path: str
    public_url: str
    type: Literal["authenticated"] | None = Field(
        default=None,
        description=(
            "Cloudinary delivery type that the signature covers. Null means the default upload type "
            "and nothing is sent. Documents return authenticated, and the client must send type as a form field."
        ),
    )


class PresignedUploadResponse(BaseModel):
    items: list[PresignedUploadResponseItem]


class UploadResult(BaseModel):
    """Result of a server-side upload of one file."""

    file_path: str
    public_url: str
    file_type: str
    file_size: int
    content_type: str
    original_filename: str | None = None
    media: MediaFileResponse | None = None


class ErrorDetail(BaseModel):
    code: str
    message: str


class BatchUploadItem(BaseModel):
    """One result per submitted file, in request order."""

    index: int
    filename: str | None = None
    status: Literal["uploaded", "failed"]
    result: UploadResult | None = None
    error: ErrorDetail | None = None


class BatchUploadResponse(BaseModel):
    items: list[BatchUploadItem]


class UploadConfirmResponse(BaseModel):
    """Result of confirming a direct upload."""

    media: MediaFileResponse


class BatchDeleteRequest(WriteModel):
    """Request payload for bulk media deletion."""

    media_ids: list[str] = Field(
        ...,
        min_length=1,
        max_length=50,
        description="Media file IDs to delete (max 50)",
    )


class BatchDeleteResponse(BaseModel):
    """Per-ID outcome of a bulk delete."""

    deleted: list[str] = Field(default_factory=list, description="IDs successfully deleted")
    failed: list[str] = Field(
        default_factory=list,
        description="IDs that could not be deleted (not found or not owned by the caller)",
    )
    storage_warnings: list[str] = Field(
        default_factory=list,
        description="IDs whose DB record was deleted but the underlying storage object could not be removed",
    )


__all__ = [
    "BatchDeleteRequest",
    "BatchDeleteResponse",
    "BatchUploadItem",
    "BatchUploadResponse",
    "ErrorDetail",
    "MediaFileResponse",
    "MediaUpdateRequest",
    "PresignedUploadItem",
    "PresignedUploadRequest",
    "PresignedUploadResponse",
    "PresignedUploadResponseItem",
    "StorageFolderType",
    "UploadConfirmResponse",
    "UploadResult",
]
