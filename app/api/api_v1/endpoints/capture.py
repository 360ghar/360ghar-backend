"""
Guided capture session API.

Mobile capture app uses these endpoints to create sessions, attach
uploaded frames with pose metadata, and complete processing.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.api_v1.dependencies.auth import get_current_active_user
from app.core.database import get_db
from app.models.enums import CaptureSessionStatus
from app.schemas.capture import (
    CaptureFrameCreate,
    CaptureFrameResponse,
    CaptureSessionCreate,
    CaptureSessionDetail,
    CaptureSessionListResponse,
    CaptureSessionResponse,
    CaptureSessionStatusResponse,
    CaptureSessionUpdate,
)
from app.schemas.user import User as UserSchema
from app.services.capture import session_service

router = APIRouter()


@router.post(
    "",
    response_model=CaptureSessionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create capture session",
)
async def create_capture_session(
    data: CaptureSessionCreate,
    db: AsyncSession = Depends(get_db),
    current_user: UserSchema = Depends(get_current_active_user),
):
    """Create a new guided-capture session (draft)."""
    return await session_service.create_session(db, current_user.id, data)


@router.get(
    "",
    response_model=CaptureSessionListResponse,
    summary="List capture sessions",
)
async def list_capture_sessions(
    status_filter: CaptureSessionStatus | None = Query(
        None, alias="status", description="Filter by session status"
    ),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: UserSchema = Depends(get_current_active_user),
):
    """List the current user's capture sessions (newest first)."""
    items, total = await session_service.list_sessions(
        db,
        current_user.id,
        status_filter=status_filter,
        limit=limit,
        offset=offset,
    )
    return {"items": items, "total": total}


@router.get(
    "/{session_id}",
    response_model=CaptureSessionDetail,
    summary="Get capture session",
)
async def get_capture_session(
    session_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: UserSchema = Depends(get_current_active_user),
):
    """Get a capture session with registered frames."""
    return await session_service.get_session_response(
        db, session_id, current_user.id, include_frames=True
    )


@router.patch(
    "/{session_id}",
    response_model=CaptureSessionResponse,
    summary="Update capture session",
)
async def update_capture_session(
    session_id: str,
    data: CaptureSessionUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: UserSchema = Depends(get_current_active_user),
):
    """Update plan, status, progress, or metadata for a session."""
    return await session_service.update_session(db, session_id, current_user.id, data)


@router.get(
    "/{session_id}/status",
    response_model=CaptureSessionStatusResponse,
    summary="Get capture session status",
)
async def get_capture_session_status(
    session_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: UserSchema = Depends(get_current_active_user),
):
    """Lightweight status poll for upload / processing UI."""
    return await session_service.get_status(db, session_id, current_user.id)


@router.post(
    "/{session_id}/frames",
    response_model=CaptureFrameResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register capture frame",
)
async def register_capture_frame(
    session_id: str,
    data: CaptureFrameCreate,
    db: AsyncSession = Depends(get_db),
    current_user: UserSchema = Depends(get_current_active_user),
):
    """
    Attach an already-uploaded image to the session.

    Upload the binary via POST /upload or the presigned flow first, then
    register the public URL / media_file_id here with pose metadata.
    """
    return await session_service.add_frame(db, session_id, current_user.id, data)


@router.post(
    "/{session_id}/complete",
    response_model=CaptureSessionResponse,
    summary="Complete capture session",
)
async def complete_capture_session(
    session_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: UserSchema = Depends(get_current_active_user),
):
    """
    Mark the session complete and enqueue processing.

    Phase 0: transitions to ready without tour generation (Phase 5).
    """
    return await session_service.complete_session(db, session_id, current_user.id)


@router.post(
    "/{session_id}/cancel",
    response_model=CaptureSessionResponse,
    summary="Cancel capture session",
)
async def cancel_capture_session(
    session_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: UserSchema = Depends(get_current_active_user),
):
    """Cancel an in-progress capture session."""
    return await session_service.cancel_session(db, session_id, current_user.id)
