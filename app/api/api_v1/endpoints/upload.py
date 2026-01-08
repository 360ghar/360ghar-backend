from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
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
)
from app.schemas.user import User as UserSchema
from app.services.storage import storage_service

router = APIRouter()

@router.post("/", response_model=Dict[str, Any])
async def upload_file(
    file: UploadFile = File(...),
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
    folder: str = Form("uploads"),
    tour_id: Optional[str] = Form(None),
    visibility: str = Form("private"),
):
    # For now, upload to a generic folder. Frontend can associate URL later.
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
    """Upload multiple files in a single request."""
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
    """Create presigned upload URLs for direct-to-storage uploads."""
    items = []
    for item in payload.files:
        result = await storage_service.create_presigned_upload(
            filename=item.filename,
            content_type=item.content_type,
            file_size=item.file_size,
            db=db,
            user_id=current_user.id,
            folder=item.folder or "uploads",
            tour_id=item.tour_id,
            visibility=item.visibility or "private",
        )
        media = result.get("media")
        items.append(
            {
                "signed_url": result["signed_url"],
                "token": result["token"],
                "path": result["path"],
                "public_url": result["public_url"],
                "media": MediaFileResponse.model_validate(media) if media else None,
            }
        )
    return {"items": items}


@router.get("/media", response_model=MediaListResponse)
async def list_media(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    tour_id: Optional[str] = Query(None),
    folder: Optional[str] = Query(None),
    visibility: Optional[str] = Query(None),
    is_processed: Optional[bool] = Query(None),
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """List uploaded media files for the current user."""
    query = select(MediaFile).where(MediaFile.user_id == current_user.id)
    if tour_id:
        query = query.where(MediaFile.tour_id == tour_id)
    if folder:
        query = query.where(MediaFile.folder == folder)
    if visibility:
        query = query.where(MediaFile.visibility == visibility)
    if is_processed is not None:
        query = query.where(MediaFile.is_processed == is_processed)

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
