from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.api_v1.dependencies.auth import get_current_active_user
from app.core.database import get_db
from app.models.tours import MediaFile
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
    MediaFileResponse,
    MediaUpdateRequest,
    PresignedUploadRequest,
    PresignedUploadResponse,
    StorageFolderType,
    UploadConfirmResponse,
)
from app.schemas.user import User as UserSchema
from app.services.storage import storage_service
from app.services.storage_paths import StorageFolder

router = APIRouter()


def _resolve_folder_type(folder_type: StorageFolderType) -> StorageFolder:
    """Map client-facing folder type to internal StorageFolder enum."""
    mapping = {
        StorageFolderType.AVATAR: StorageFolder.AVATAR,
        StorageFolderType.PROPERTY_IMAGE: StorageFolder.PROPERTY_IMAGE,
        StorageFolderType.PROPERTY_VIDEO: StorageFolder.PROPERTY_VIDEO,
        StorageFolderType.PROPERTY_DOCUMENT: StorageFolder.PROPERTY_DOCUMENT,
        StorageFolderType.TOUR: StorageFolder.TOUR_THUMBNAIL,
        StorageFolderType.SCENE: StorageFolder.SCENE_ORIGINAL,
        StorageFolderType.DOCUMENT_LEASE: StorageFolder.DOCUMENT_LEASE,
        StorageFolderType.DOCUMENT_MAINTENANCE: StorageFolder.DOCUMENT_MAINTENANCE,
        StorageFolderType.DOCUMENT_GENERAL: StorageFolder.DOCUMENT_GENERAL,
        StorageFolderType.GENERIC: StorageFolder.GENERIC_UPLOAD,
    }
    return mapping.get(folder_type, StorageFolder.GENERIC_UPLOAD)


@router.post("", response_model=dict[str, Any], summary="Upload file")
async def upload_file(
    file: UploadFile = File(...),
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
    folder: str = Form("uploads"),
    tour_id: str | None = Form(None),
    visibility: str = Form("private"),
):
    """Upload a single file with MediaFile tracking.

    Files are uploaded to user-scoped paths: users/{user_id}/...
    """
    result = await storage_service.upload_and_track(
        file,
        db=db,
        user_id=current_user.id,
        folder=folder,
        tour_id=tour_id,
        visibility=visibility,
    )
    media = result.get("media")
    if media:
        result["media"] = MediaFileResponse.model_validate(media)
    return result


@router.post("/batch", response_model=dict[str, Any], summary="Upload files in batch")
async def upload_batch(
    files: list[UploadFile] = File(..., max_length=20),
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
    folder: str = Form("uploads"),
    tour_id: str | None = Form(None),
    visibility: str = Form("private"),
):
    """Upload multiple files in a single request.

    Files are uploaded to user-scoped paths: users/{user_id}/...
    """
    items = await storage_service.upload_batch(
        files,
        db=db,
        user_id=current_user.id,
        folder=folder,
        tour_id=tour_id,
        visibility=visibility,
    )
    for item in items:
        media = item.get("media")
        if media:
            item["media"] = MediaFileResponse.model_validate(media)
    return {"items": items}


@router.post(
    "/presigned",
    response_model=PresignedUploadResponse,
    summary="Create presigned uploads",
    openapi_extra={
        "requestBody": {
            "content": {
                "application/json": {
                    "examples": {
                        "property_image": {
                            "value": {
                                "files": [
                                    {
                                        "filename": "living-room.jpg",
                                        "content_type": "image/jpeg",
                                        "file_size": 102400,
                                        "folder_type": "property_image",
                                        "property_id": 1,
                                        "visibility": "public",
                                    }
                                ]
                            }
                        },
                        "avatar": {
                            "value": {
                                "files": [
                                    {
                                        "filename": "avatar.png",
                                        "content_type": "image/png",
                                        "folder_type": "avatar",
                                        "visibility": "public",
                                    }
                                ]
                            }
                        },
                    }
                }
            }
        }
    },
)
async def create_presigned_uploads(
    payload: PresignedUploadRequest,
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Create presigned upload URLs for direct client-side uploads.

    Returns signed URLs that clients can use to upload files directly to storage.
    After uploading, clients should call POST /upload/confirm/{upload_id} to
    confirm the upload completed successfully.

    Files are stored in user-scoped paths based on folder_type:
    - AVATAR: users/{user_id}/avatars/
    - PROPERTY_IMAGE: users/{user_id}/properties/{property_id}/images/
    - PROPERTY_VIDEO: users/{user_id}/properties/{property_id}/videos/
    - TOUR/SCENE: users/{user_id}/tours/{tour_id}/scenes/{scene_id}/
    - DOCUMENT_*: users/{user_id}/documents/{type}/
    - GENERIC: users/{user_id}/uploads/
    """
    items = []
    for item in payload.files:
        # Map folder_type to internal StorageFolder enum
        folder = _resolve_folder_type(item.folder_type)

        result = await storage_service.create_presigned_upload(
            filename=item.filename,
            content_type=item.content_type,
            file_size=item.file_size,
            db=db,
            user_id=current_user.id,
            folder=folder,
            property_id=item.property_id,
            tour_id=item.tour_id,
            scene_id=item.scene_id,
            visibility=item.visibility or "private",
        )
        items.append({
            "upload_id": result["upload_id"],
            "signed_url": result["signed_url"],
            "token": result["token"],
            "api_key": result.get("api_key"),
            "timestamp": result.get("timestamp"),
            "public_id": result.get("public_id"),
            "path": result["path"],
            "public_url": result["public_url"],
        })
    return {"items": items}


@router.post("/confirm/{upload_id}", response_model=UploadConfirmResponse, summary="Confirm upload")
async def confirm_upload(
    upload_id: str,
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Confirm a client-side upload completed successfully.

    Call this endpoint after uploading a file directly to storage using
    the signed URL from /presigned. This verifies the file exists and
    updates the MediaFile record status from 'pending' to 'complete'.
    """
    media = await storage_service.confirm_upload(
        db=db,
        upload_id=upload_id,
        user_id=current_user.id,
    )
    return {
        "media": MediaFileResponse.model_validate(media),
        "message": "Upload confirmed successfully",
    }


@router.get("/media", response_model=CursorPage[MediaFileResponse], summary="List media files")
async def list_media(
    page: CursorParams = Depends(),
    tour_id: str | None = Query(None),
    folder: str | None = Query(None),
    mime_type: str | None = Query(None),
    visibility: str | None = Query(None),
    is_processed: bool | None = Query(None),
    upload_status: str | None = Query(None, description="Filter by upload status: pending, complete, failed"),
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """List uploaded media files for the current user."""
    cursor_payload = page.decoded()

    stmt = select(MediaFile).where(MediaFile.user_id == current_user.id)
    if tour_id:
        stmt = stmt.where(MediaFile.tour_id == tour_id)
    if folder:
        stmt = stmt.where(MediaFile.folder == folder)
    if mime_type:
        stmt = stmt.where(MediaFile.mime_type == mime_type)
    if visibility:
        stmt = stmt.where(MediaFile.visibility == visibility)
    if is_processed is not None:
        stmt = stmt.where(MediaFile.is_processed == is_processed)
    if upload_status:
        stmt = stmt.where(MediaFile.upload_status == upload_status)

    count_total = None
    if page.include_total:
        count_total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()

    predicate = keyset_filter(MediaFile.created_at, MediaFile.id, cursor_payload, descending=True)
    if predicate is not None:
        stmt = stmt.where(predicate)

    stmt = stmt.order_by(MediaFile.created_at.desc(), MediaFile.id.desc()).limit(page.limit + 1)
    items = list((await db.execute(stmt)).scalars().all())

    next_payload = None
    if len(items) > page.limit:
        items = items[:page.limit]
        next_payload = keyset_payload(keyset_sort_value(items[-1].created_at), items[-1].id)

    return build_cursor_page(
        [MediaFileResponse.model_validate(item) for item in items],
        limit=page.limit,
        next_payload=next_payload,
        total=count_total,
    )


@router.post(
    "/media/batch-delete",
    response_model=BatchDeleteResponse,
    summary="Bulk delete media files",
)
async def batch_delete_media(
    payload: BatchDeleteRequest,
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete up to 50 media files in a single request.

    Only media owned by the current user are deleted. IDs that are not found or
    are owned by another user are returned in the ``failed`` list.
    """
    return await storage_service.delete_batch(db, payload.media_ids, current_user)


@router.get("/media/{media_id}", response_model=MediaFileResponse, summary="Get media file")
async def get_media(
    media_id: str,
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Get a single media file for the current user."""
    query = select(MediaFile).where(
        MediaFile.id == media_id,
        MediaFile.user_id == current_user.id,
    )
    result = await db.execute(query)
    media = result.scalar_one_or_none()
    if not media:
        raise HTTPException(status_code=404, detail="Media file not found")
    return MediaFileResponse.model_validate(media)


@router.delete("/media/{media_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete media file")
async def delete_media(
    media_id: str,
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete a media file and attempt to remove the underlying object from storage."""
    query = select(MediaFile).where(
        MediaFile.id == media_id,
        MediaFile.user_id == current_user.id,
    )
    result = await db.execute(query)
    media = result.scalar_one_or_none()
    if not media:
        raise HTTPException(status_code=404, detail="Media file not found")

    # Use storage_path if available, otherwise construct from folder/filename
    file_path: str | None = media.storage_path
    if not file_path and media.filename:
        file_path = f"{media.folder}/{media.filename}" if media.folder else media.filename

    if file_path:
        bucket_name = media.bucket_name if media.bucket_name else None
        storage_service.delete_file(file_path, bucket_name=bucket_name)

    await db.delete(media)
    await db.flush()
    return None


@router.patch("/media/{media_id}", response_model=MediaFileResponse, summary="Update media file")
async def update_media(
    media_id: str,
    payload: MediaUpdateRequest,
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Update media processing status or URLs."""
    query = select(MediaFile).where(
        MediaFile.id == media_id,
        MediaFile.user_id == current_user.id,
    )
    result = await db.execute(query)
    media = result.scalar_one_or_none()
    if not media:
        raise HTTPException(status_code=404, detail="Media file not found")

    update_data = payload.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(media, field, value)

    await db.flush()
    await db.refresh(media)

    return MediaFileResponse.model_validate(media)
