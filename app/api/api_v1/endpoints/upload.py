from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.api_v1.dependencies.auth import get_current_active_user
from app.core.database import get_db
from app.models.tours import MediaFile
from app.schemas.storage import (
    MediaFileResponse,
    MediaListResponse,
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


@router.post("", response_model=Dict[str, Any])
async def upload_file(
    file: UploadFile = File(...),
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
    folder: str = Form("uploads"),
    tour_id: Optional[str] = Form(None),
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


@router.post("/batch", response_model=Dict[str, Any])
async def upload_batch(
    files: List[UploadFile] = File(...),
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
    folder: str = Form("uploads"),
    tour_id: Optional[str] = Form(None),
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


@router.post("/presigned", response_model=PresignedUploadResponse)
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
            "path": result["path"],
            "public_url": result["public_url"],
        })
    return {"items": items}


@router.post("/confirm/{upload_id}", response_model=UploadConfirmResponse)
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


@router.get("/media", response_model=MediaListResponse)
async def list_media(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    tour_id: Optional[str] = Query(None),
    folder: Optional[str] = Query(None),
    mime_type: Optional[str] = Query(None),
    visibility: Optional[str] = Query(None),
    is_processed: Optional[bool] = Query(None),
    upload_status: Optional[str] = Query(None, description="Filter by upload status: pending, complete, failed"),
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """List uploaded media files for the current user."""
    query = select(MediaFile).where(MediaFile.user_id == current_user.id)
    if tour_id:
        query = query.where(MediaFile.tour_id == tour_id)
    if folder:
        query = query.where(MediaFile.folder == folder)
    if mime_type:
        query = query.where(MediaFile.mime_type == mime_type)
    if visibility:
        query = query.where(MediaFile.visibility == visibility)
    if is_processed is not None:
        query = query.where(MediaFile.is_processed == is_processed)
    if upload_status:
        query = query.where(MediaFile.upload_status == upload_status)

    count_query = select(func.count()).select_from(query.subquery())
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0
    total_pages = (total + page_size - 1) // page_size

    query = query.order_by(MediaFile.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    items = list(result.scalars().all())

    return {
        "items": [MediaFileResponse.model_validate(item) for item in items],
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages,
    }


@router.get("/media/{media_id}", response_model=MediaFileResponse)
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


@router.delete("/media/{media_id}", status_code=status.HTTP_204_NO_CONTENT)
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
    file_path: Optional[str] = media.storage_path
    if not file_path and media.filename:
        file_path = f"{media.folder}/{media.filename}" if media.folder else media.filename

    if file_path:
        bucket_name = media.bucket_name if media.bucket_name else None
        storage_service.delete_file(file_path, bucket_name=bucket_name)

    await db.delete(media)
    await db.flush()
    return None


@router.patch("/media/{media_id}", response_model=MediaFileResponse)
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
