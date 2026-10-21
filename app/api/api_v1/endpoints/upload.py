from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.api_v1.dependencies.auth import (
    get_current_active_user,
    get_current_cached_active_user,
)
from app.config import settings
from app.core.database import get_db
from app.core.db_resilience import (
    apply_statement_timeout,
    execute_with_transient_retry,
    raise_read_service_unavailable,
)
from app.core.logging import get_logger
from app.models.enums import StorageFolderType, TourVisibility, UploadStatus
from app.models.tours import MediaFile
from app.schemas.base import PatchModel
from app.schemas.pagination import (
    CursorPage,
    CursorParams,
    build_cursor_page,
    keyset_filter,
    keyset_payload,
    keyset_sort_value,
)
from app.schemas.storage import (
    BatchDeleteRequest,
    BatchDeleteResponse,
    BatchUploadItem,
    BatchUploadResponse,
    ErrorDetail,
    MediaFileResponse,
    MediaUpdateRequest,
    PresignedUploadRequest,
    PresignedUploadResponse,
    PresignedUploadResponseItem,
    UploadConfirmResponse,
    UploadResult,
)
from app.schemas.user import User as UserSchema
from app.services.auth_user_cache import AuthUserSnapshot
from app.services.storage import storage_service
from app.services.storage.access import assert_upload_targets
from app.services.storage_paths import StorageFolder

router = APIRouter()
logger = get_logger(__name__)

_FOLDER_MAP: dict[StorageFolderType, StorageFolder] = {
    StorageFolderType.AVATAR: StorageFolder.AVATAR,
    StorageFolderType.PROPERTY_IMAGE: StorageFolder.PROPERTY_IMAGE,
    StorageFolderType.PROPERTY_VIDEO: StorageFolder.PROPERTY_VIDEO,
    StorageFolderType.PROPERTY_DOCUMENT: StorageFolder.PROPERTY_DOCUMENT,
    StorageFolderType.TOUR_THUMBNAIL: StorageFolder.TOUR_THUMBNAIL,
    StorageFolderType.TOUR_ORIGINAL: StorageFolder.TOUR_ORIGINAL,
    StorageFolderType.SCENE: StorageFolder.SCENE_ORIGINAL,
    StorageFolderType.DOCUMENT_LEASE: StorageFolder.DOCUMENT_LEASE,
    StorageFolderType.DOCUMENT_MAINTENANCE: StorageFolder.DOCUMENT_MAINTENANCE,
    StorageFolderType.DOCUMENT_GENERAL: StorageFolder.DOCUMENT_GENERAL,
    StorageFolderType.GENERIC: StorageFolder.GENERIC_UPLOAD,
}


def _resolve_folder_type(folder_type: StorageFolderType) -> StorageFolder:
    """Map the client folder type to the internal StorageFolder. Every value is mapped."""
    return _FOLDER_MAP[folder_type]


# /upload and /upload/batch take no property or scene id. These folder types need one,
# so they are rejected here. Use /upload/presigned for them.
_FORM_FOLDER_TYPES = frozenset(
    {
        StorageFolderType.AVATAR,
        StorageFolderType.DOCUMENT_LEASE,
        StorageFolderType.DOCUMENT_MAINTENANCE,
        StorageFolderType.DOCUMENT_GENERAL,
        StorageFolderType.GENERIC,
        StorageFolderType.TOUR_THUMBNAIL,
        StorageFolderType.TOUR_ORIGINAL,
    }
)
_TOUR_FOLDER_TYPES = frozenset({StorageFolderType.TOUR_THUMBNAIL, StorageFolderType.TOUR_ORIGINAL})


def _check_form_folder(folder_type: StorageFolderType, tour_id: str | None) -> None:
    """422 for a folder type this route cannot place, or a tour folder without a tour_id."""
    if folder_type not in _FORM_FOLDER_TYPES:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "FOLDER_TYPE_NOT_ALLOWED",
                "message": f"folder_type '{folder_type.value}' needs a property or scene id. "
                "Use POST /upload/presigned for it.",
            },
        )
    if folder_type in _TOUR_FOLDER_TYPES and not tour_id:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "TOUR_ID_REQUIRED",
                "message": f"folder_type '{folder_type.value}' needs tour_id.",
            },
        )


def _escape_like(term: str) -> str:
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _upload_result(item: dict) -> UploadResult:
    """Build the public upload result from the service dict. Splits off the media row."""
    media = item.pop("media", None)
    return UploadResult(
        **item,
        media=MediaFileResponse.model_validate(media) if media is not None else None,
    )


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=UploadResult,
    summary="Upload file",
)
async def upload_file(
    file: UploadFile = File(...),
    folder_type: StorageFolderType = Form(StorageFolderType.GENERIC),
    tour_id: str | None = Form(None),
    visibility: TourVisibility = Form(TourVisibility.private),
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> UploadResult:
    """Upload a single file and record it in the media library.

    The file is stored under the caller's folder for ``folder_type``.
    """
    _check_form_folder(folder_type, tour_id)
    await assert_upload_targets(db, actor=current_user, tour_id=tour_id)
    result = await storage_service.upload_and_track(
        file,
        db=db,
        user_id=current_user.id,
        folder=_resolve_folder_type(folder_type),
        tour_id=tour_id,
        visibility=visibility.value,
    )
    return _upload_result(result)


@router.post(
    "/batch",
    status_code=status.HTTP_201_CREATED,
    response_model=BatchUploadResponse,
    summary="Upload files in batch",
)
async def upload_batch(
    files: list[UploadFile] = File(...),
    folder_type: StorageFolderType = Form(StorageFolderType.GENERIC),
    tour_id: str | None = Form(None),
    visibility: TourVisibility = Form(TourVisibility.private),
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> BatchUploadResponse:
    """Upload up to 20 files. Returns one result per file, in request order.

    Any invalid file rejects the whole batch with 400 before the first upload.
    A storage failure on one file is reported for that file only.
    """
    _check_form_folder(folder_type, tour_id)
    await assert_upload_targets(db, actor=current_user, tour_id=tour_id)
    results = await storage_service.upload_batch(
        files,
        db=db,
        user_id=current_user.id,
        folder=_resolve_folder_type(folder_type),
        tour_id=tour_id,
        visibility=visibility.value,
    )
    items: list[BatchUploadItem] = []
    for entry in results:
        if entry["status"] == "uploaded":
            items.append(
                BatchUploadItem(
                    index=entry["index"],
                    filename=entry["filename"],
                    status="uploaded",
                    result=_upload_result(entry["result"]),
                )
            )
        else:
            items.append(
                BatchUploadItem(
                    index=entry["index"],
                    filename=entry["filename"],
                    status="failed",
                    error=ErrorDetail(**entry["error"]),
                )
            )
    return BatchUploadResponse(items=items)


@router.post(
    "/presigned",
    status_code=status.HTTP_201_CREATED,
    response_model=PresignedUploadResponse,
    summary="Create presigned uploads",
)
async def create_presigned_uploads(
    payload: PresignedUploadRequest,
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> PresignedUploadResponse:
    """Create signed upload parameters for direct client uploads.

    ``file_size`` is required. After the upload, call ``POST /upload/confirm/{upload_id}``.
    The confirm step checks the stored size against ``file_size``.
    """
    items: list[PresignedUploadResponseItem] = []
    for item in payload.files:
        await assert_upload_targets(
            db,
            actor=current_user,
            property_id=item.property_id,
            tour_id=item.tour_id,
            scene_id=item.scene_id,
        )
        result = await storage_service.create_presigned_upload(
            filename=item.filename,
            content_type=item.content_type,
            file_size=item.file_size,
            db=db,
            user_id=current_user.id,
            folder=_resolve_folder_type(item.folder_type),
            property_id=item.property_id,
            tour_id=item.tour_id,
            scene_id=item.scene_id,
            visibility=item.visibility.value,
        )
        items.append(
            PresignedUploadResponseItem(
                upload_id=result["upload_id"],
                signed_url=result["signed_url"],
                signature=result["signature"],
                api_key=result["api_key"],
                timestamp=result["timestamp"],
                public_id=result["public_id"],
                path=result["path"],
                public_url=result["public_url"],
                type=result["type"],
            )
        )
    return PresignedUploadResponse(items=items)


@router.post("/confirm/{upload_id}", response_model=UploadConfirmResponse, summary="Confirm upload")
async def confirm_upload(
    upload_id: str,
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> UploadConfirmResponse:
    """Confirm a direct upload. Calling it again on a complete upload returns the same media."""
    media = await storage_service.confirm_upload(
        db=db,
        upload_id=upload_id,
        user_id=current_user.id,
    )
    return UploadConfirmResponse(media=MediaFileResponse.model_validate(media))


@router.get("/media", response_model=CursorPage[MediaFileResponse], summary="List media files")
async def list_media(
    page: CursorParams = Depends(),
    tour_id: str | None = Query(None),
    mime_type: str | None = Query(None),
    visibility: TourVisibility | None = Query(None),
    is_processed: bool | None = Query(None),
    upload_status: UploadStatus | None = Query(None),
    search: str | None = Query(
        None, min_length=1, max_length=100, description="Substring of the original filename"
    ),
    current_user: AuthUserSnapshot = Depends(get_current_cached_active_user),
    db: AsyncSession = Depends(get_db),
) -> CursorPage[MediaFileResponse]:
    """List the caller's media files, newest first."""
    filters = {
        "tour_id": tour_id,
        "mime_type": mime_type,
        "visibility": visibility.value if visibility else None,
        "is_processed": is_processed,
        "upload_status": upload_status.value if upload_status else None,
        "search": search,
    }
    try:
        await apply_statement_timeout(db, settings.DB_READ_STATEMENT_TIMEOUT_MS)
        cursor_payload = page.decoded(filters)

        stmt = select(MediaFile).where(MediaFile.user_id == current_user.id)
        if tour_id:
            stmt = stmt.where(MediaFile.tour_id == tour_id)
        if mime_type:
            stmt = stmt.where(MediaFile.mime_type == mime_type)
        if visibility:
            stmt = stmt.where(MediaFile.visibility == visibility.value)
        if is_processed is not None:
            stmt = stmt.where(MediaFile.is_processed == is_processed)
        if upload_status:
            stmt = stmt.where(MediaFile.upload_status == upload_status.value)
        if search:
            stmt = stmt.where(
                MediaFile.original_filename.ilike(f"%{_escape_like(search)}%", escape="\\")
            )

        count_total = None
        if page.include_total:
            count_stmt = select(func.count()).select_from(stmt.subquery())
            count_result = await execute_with_transient_retry(
                db,
                lambda: db.execute(count_stmt),
                operation_name="media_list_count",
            )
            count_total = count_result.scalar_one()

        predicate = keyset_filter(
            MediaFile.created_at, MediaFile.id, cursor_payload, descending=True
        )
        if predicate is not None:
            stmt = stmt.where(predicate)

        stmt = stmt.order_by(MediaFile.created_at.desc(), MediaFile.id.desc()).limit(page.limit + 1)
        result = await execute_with_transient_retry(
            db,
            lambda: db.execute(stmt),
            operation_name="media_list_query",
        )
        items = list(result.scalars().all())

        next_payload = None
        if len(items) > page.limit:
            items = items[: page.limit]
            next_payload = keyset_payload(keyset_sort_value(items[-1].created_at), items[-1].id)

        return CursorPage[MediaFileResponse](
            **build_cursor_page(
                [MediaFileResponse.model_validate(item) for item in items],
                limit=page.limit,
                next_payload=next_payload,
                total=count_total,
                filters=filters,
            )
        )
    except Exception as exc:
        raise_read_service_unavailable(
            exc,
            endpoint="media_list",
            detail="Media files are temporarily unavailable. Please retry shortly.",
            extra={"user": current_user.id},
        )
        raise


@router.post(
    "/media/batch-delete", response_model=BatchDeleteResponse, summary="Bulk delete media files"
)
async def batch_delete_media(
    payload: BatchDeleteRequest,
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> BatchDeleteResponse:
    """Delete up to 50 media files. Reports ``failed`` IDs and ``storage_warnings`` IDs."""
    result = await storage_service.delete_batch(db, payload.media_ids, current_user)
    return BatchDeleteResponse(**result)


@router.get("/media/{media_id}", response_model=MediaFileResponse, summary="Get media file")
async def get_media(
    media_id: str,
    current_user: AuthUserSnapshot = Depends(get_current_cached_active_user),
    db: AsyncSession = Depends(get_db),
) -> MediaFileResponse:
    """Get one media file of the caller."""
    try:
        await apply_statement_timeout(db, settings.DB_READ_STATEMENT_TIMEOUT_MS)
        query = select(MediaFile).where(
            MediaFile.id == media_id,
            MediaFile.user_id == current_user.id,
        )
        result = await execute_with_transient_retry(
            db,
            lambda: db.execute(query),
            operation_name="media_get",
        )
        media = result.scalar_one_or_none()
        if not media:
            raise HTTPException(status_code=404, detail="Media file not found")
        return MediaFileResponse.model_validate(media)
    except HTTPException:
        raise
    except Exception as exc:
        raise_read_service_unavailable(
            exc,
            endpoint="media_get",
            detail="Media file is temporarily unavailable. Please retry shortly.",
            extra={"user": current_user.id},
        )
        raise


@router.delete(
    "/media/{media_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete media file"
)
async def delete_media(
    media_id: str,
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete a media file. A storage failure returns 503 and keeps the row for a retry."""
    query = select(MediaFile).where(
        MediaFile.id == media_id,
        MediaFile.user_id == current_user.id,
    )
    result = await db.execute(query)
    media = result.scalar_one_or_none()
    if not media:
        raise HTTPException(status_code=404, detail="Media file not found")

    file_path: str | None = media.storage_path
    if not file_path and media.filename:
        file_path = f"{media.folder}/{media.filename}" if media.folder else media.filename

    if file_path and not storage_service.delete_file(
        file_path,
        bucket_name=media.bucket_name or None,
        **storage_service.delivery_kwargs(media),
    ):
        # Keep the row so the client can retry. Removing it now would leave the stored
        # object with no record that points to it.
        logger.warning("Storage object not removed for media %s", media.id)
        raise HTTPException(
            status_code=503,
            detail={
                "code": "STORAGE_DELETE_FAILED",
                "message": "The stored file could not be removed. Retry the request.",
            },
            headers={"Retry-After": "30"},
        )

    await db.delete(media)
    await db.flush()


@router.patch("/media/{media_id}", response_model=MediaFileResponse, summary="Update media file")
async def update_media(
    media_id: str,
    payload: MediaUpdateRequest,
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> MediaFileResponse:
    """Update processing status, URLs or visibility. Only the sent keys change."""
    query = select(MediaFile).where(
        MediaFile.id == media_id,
        MediaFile.user_id == current_user.id,
    )
    result = await db.execute(query)
    media = result.scalar_one_or_none()
    if not media:
        raise HTTPException(status_code=404, detail="Media file not found")

    update_data = payload.model_dump(exclude_unset=True)
    if (
        isinstance(payload, PatchModel)
        and "visibility" in update_data
        and update_data["visibility"] is not None
    ):
        update_data["visibility"] = update_data["visibility"].value
    for field, value in update_data.items():
        setattr(media, field, value)

    await db.flush()
    await db.refresh(media)

    return MediaFileResponse.model_validate(media)
