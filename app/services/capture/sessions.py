"""
Capture session CRUD and frame registration.

Phase 0: create / read / update / list / cancel + frame attach.
Processing (stitch → tour) is stubbed for later phases.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import BadRequestException, ForbiddenException, NotFoundException
from app.core.logging import get_logger
from app.models.capture import CaptureFrame, CaptureSession
from app.models.enums import CaptureSessionStatus
from app.models.tours import MediaFile
from app.schemas.capture import (
    CaptureFrameCreate,
    CaptureSessionCreate,
    CaptureSessionUpdate,
)

logger = get_logger(__name__)

# Terminal states that reject further mutation (except cancel is already terminal)
_TERMINAL = {
    CaptureSessionStatus.ready,
    CaptureSessionStatus.failed,
    CaptureSessionStatus.cancelled,
}

# Client-driven status transitions via PATCH. `ready` / `processing` / `failed`
# are server-controlled (complete_session and the future stitch worker), so a
# client can never mark a session complete-looking without going through the
# completion flow.
_CLIENT_TRANSITIONS: dict[CaptureSessionStatus, frozenset[CaptureSessionStatus]] = {
    CaptureSessionStatus.draft: frozenset({CaptureSessionStatus.capturing}),
    CaptureSessionStatus.capturing: frozenset({CaptureSessionStatus.review}),
    CaptureSessionStatus.review: frozenset(
        {CaptureSessionStatus.capturing, CaptureSessionStatus.uploading}
    ),
    CaptureSessionStatus.uploading: frozenset({CaptureSessionStatus.review}),
}


def _session_to_dict(session: CaptureSession, frame_count: int) -> dict[str, Any]:
    return {
        "id": session.id,
        "user_id": session.user_id,
        "title": session.title,
        "description": session.description,
        "status": session.status,
        "progress": session.progress,
        "plan": session.plan,
        "device_info": session.device_info,
        "tour_id": session.tour_id,
        "error_message": session.error_message,
        "frame_count": frame_count,
        "created_at": session.created_at,
        "updated_at": session.updated_at,
    }


def _frame_to_dict(frame: CaptureFrame) -> dict[str, Any]:
    return {
        "id": frame.id,
        "session_id": frame.session_id,
        "room_id": frame.room_id,
        "room_label": frame.room_label,
        "waypoint_id": frame.waypoint_id,
        "waypoint_index": frame.waypoint_index,
        "frame_index": frame.frame_index,
        "media_file_id": frame.media_file_id,
        "image_url": frame.image_url,
        "frame_metadata": frame.frame_metadata,
        "created_at": frame.created_at,
    }


async def create_session(
    db: AsyncSession,
    user_id: int,
    data: CaptureSessionCreate,
) -> dict:
    plan = data.plan.model_dump() if data.plan else {"template": None, "rooms": []}
    device_info = data.device_info.model_dump(exclude_none=True) if data.device_info else None

    session = CaptureSession(
        user_id=user_id,
        title=data.title,
        description=data.description,
        status=CaptureSessionStatus.draft,
        progress=0,
        plan=plan,
        device_info=device_info,
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)
    logger.info("capture_session_created: %s by user %s", session.id, user_id)
    return _session_to_dict(session, frame_count=0)


async def list_sessions(
    db: AsyncSession,
    user_id: int,
    *,
    status_filter: CaptureSessionStatus | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[dict], int]:
    base = select(CaptureSession).where(CaptureSession.user_id == user_id)
    if status_filter is not None:
        base = base.where(CaptureSession.status == status_filter)

    total = (
        await db.execute(select(func.count()).select_from(base.subquery()))
    ).scalar_one()

    # Correlated scalar subquery keeps the count work bounded to the page rows
    # (a global GROUP BY would aggregate every frame of every user).
    frame_count_expr = (
        select(func.count(CaptureFrame.id))
        .where(CaptureFrame.session_id == CaptureSession.id)
        .correlate(CaptureSession)
        .scalar_subquery()
    )

    stmt = (
        base.add_columns(frame_count_expr.label("frame_count"))
        .order_by(CaptureSession.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    rows = (await db.execute(stmt)).all()
    items = [_session_to_dict(session, int(count or 0)) for session, count in rows]
    return items, int(total)


async def get_session(
    db: AsyncSession,
    session_id: str,
    user_id: int,
    *,
    include_frames: bool = False,
) -> CaptureSession:
    query = select(CaptureSession).where(CaptureSession.id == session_id)
    if include_frames:
        query = query.options(selectinload(CaptureSession.frames))

    result = await db.execute(query)
    session = result.scalar_one_or_none()
    if session is None:
        raise NotFoundException(detail="Capture session not found")
    if session.user_id != user_id:
        raise ForbiddenException(detail="Not authorized to access this capture session")
    return session


async def get_session_response(
    db: AsyncSession,
    session_id: str,
    user_id: int,
    *,
    include_frames: bool = False,
) -> dict:
    session = await get_session(db, session_id, user_id, include_frames=include_frames)
    if include_frames:
        frame_count = len(session.frames or [])
    else:
        # Count explicitly instead of lazily touching session.frames — after a
        # commit/refresh the relationship is not loaded and lazy access would
        # raise outside an awaited ORM call.
        frame_count = (
            await db.execute(
                select(func.count())
                .select_from(CaptureFrame)
                .where(CaptureFrame.session_id == session.id)
            )
        ).scalar_one()
    payload = _session_to_dict(session, frame_count=int(frame_count))
    if include_frames:
        payload["frames"] = [_frame_to_dict(f) for f in (session.frames or [])]
    return payload


async def update_session(
    db: AsyncSession,
    session_id: str,
    user_id: int,
    data: CaptureSessionUpdate,
) -> dict:
    session = await get_session(db, session_id, user_id)

    new_status = data.status
    if new_status is not None and new_status != session.status:
        allowed = _CLIENT_TRANSITIONS.get(session.status)
        if allowed is None or new_status not in allowed:
            raise BadRequestException(
                detail=(
                    f"Status transition {session.status.value} → "
                    f"{new_status.value} is not allowed via PATCH"
                )
            )

    updates = data.model_dump(exclude_unset=True)
    # error_message is server-owned (completion / cancellation / stitch worker);
    # strip it defensively even if a future schema re-introduces it.
    updates.pop("error_message", None)
    if "plan" in updates and data.plan is not None:
        updates["plan"] = data.plan.model_dump()
    if "device_info" in updates and data.device_info is not None:
        updates["device_info"] = data.device_info.model_dump(exclude_none=True)

    for key, value in updates.items():
        setattr(session, key, value)

    await db.commit()
    await db.refresh(session)
    return await get_session_response(db, session_id, user_id)


async def cancel_session(
    db: AsyncSession,
    session_id: str,
    user_id: int,
) -> dict:
    session = await get_session(db, session_id, user_id)
    if session.status in {
        CaptureSessionStatus.ready,
        CaptureSessionStatus.failed,
    }:
        raise BadRequestException(
            detail=f"Cannot cancel a session in status {session.status.value}"
        )
    if session.status == CaptureSessionStatus.cancelled:
        return await get_session_response(db, session_id, user_id)

    session.status = CaptureSessionStatus.cancelled
    session.error_message = session.error_message or "Cancelled by user"
    await db.commit()
    await db.refresh(session)
    return await get_session_response(db, session_id, user_id)


async def add_frame(
    db: AsyncSession,
    session_id: str,
    user_id: int,
    data: CaptureFrameCreate,
) -> dict:
    session = await get_session(db, session_id, user_id)
    if session.status in {
        CaptureSessionStatus.ready,
        CaptureSessionStatus.failed,
        CaptureSessionStatus.cancelled,
        CaptureSessionStatus.processing,
    }:
        raise BadRequestException(
            detail=f"Cannot add frames to a session in status {session.status.value}"
        )

    if not data.image_url and not data.media_file_id:
        raise BadRequestException(detail="Either image_url or media_file_id is required")

    # Resolve the media reference so a frame can never point at a file that is
    # not this user's (or that never finished uploading).
    if data.media_file_id:
        media = (
            await db.execute(
                select(MediaFile).where(
                    MediaFile.id == data.media_file_id,
                    MediaFile.user_id == user_id,
                )
            )
        ).scalar_one_or_none()
        if media is None:
            raise BadRequestException(
                detail="media_file_id does not reference an uploaded file owned by this user"
            )
        if media.upload_status != "complete":
            raise BadRequestException(
                detail="media_file_id has not finished uploading (upload_status != complete)"
            )

    # Auto-advance draft → capturing on first frame
    if session.status == CaptureSessionStatus.draft:
        session.status = CaptureSessionStatus.capturing

    meta = data.metadata.model_dump(mode="json", exclude_none=True) if data.metadata else None
    # Upsert on the logical frame identity so a retry after a lost response
    # converges on the existing row instead of duplicating the frame.
    stmt = (
        pg_insert(CaptureFrame)
        .values(
            session_id=session.id,
            room_id=data.room_id,
            room_label=data.room_label,
            waypoint_id=data.waypoint_id,
            waypoint_index=data.waypoint_index,
            frame_index=data.frame_index,
            media_file_id=data.media_file_id,
            image_url=data.image_url,
            frame_metadata=meta,
        )
        .on_conflict_do_update(
            index_elements=[
                CaptureFrame.session_id,
                CaptureFrame.room_id,
                CaptureFrame.waypoint_id,
                CaptureFrame.frame_index,
            ],
            set_={
                "room_label": data.room_label,
                "waypoint_index": data.waypoint_index,
                "media_file_id": data.media_file_id,
                "image_url": data.image_url,
                "frame_metadata": meta,
            },
        )
        .returning(CaptureFrame)
    )
    frame = (await db.execute(stmt)).scalar_one()
    await db.commit()
    await db.refresh(frame)

    return _frame_to_dict(frame)


async def complete_session(
    db: AsyncSession,
    session_id: str,
    user_id: int,
) -> dict:
    """
    Mark session for processing.

    Phase 0 stub: moves to `processing` then immediately `ready` without
    creating a tour (tour bridge is Phase 5).
    """
    session = await get_session(db, session_id, user_id, include_frames=True)
    if session.status in _TERMINAL:
        raise BadRequestException(
            detail=f"Cannot complete a session in status {session.status.value}"
        )

    frame_count = len(session.frames or [])
    if frame_count == 0:
        raise BadRequestException(detail="Cannot complete a session with no frames")

    session.status = CaptureSessionStatus.processing
    session.progress = 50
    await db.commit()

    # Phase 0: no stitch worker yet — park as ready without tour_id
    session.status = CaptureSessionStatus.ready
    session.progress = 100
    await db.commit()
    await db.refresh(session)

    logger.info(
        "capture_session_complete_stub: %s frames=%s",
        session.id,
        frame_count,
    )
    return await get_session_response(db, session_id, user_id)


async def get_status(
    db: AsyncSession,
    session_id: str,
    user_id: int,
) -> dict:
    session = await get_session(db, session_id, user_id, include_frames=True)
    frame_count = len(session.frames or [])
    messages = {
        CaptureSessionStatus.draft: "Session created; start capturing",
        CaptureSessionStatus.capturing: "Capture in progress",
        CaptureSessionStatus.review: "Review captures before upload",
        CaptureSessionStatus.uploading: "Uploading frames",
        CaptureSessionStatus.processing: "Processing into tour",
        CaptureSessionStatus.ready: "Ready" + (f" — tour {session.tour_id}" if session.tour_id else " (no tour yet)"),
        CaptureSessionStatus.failed: session.error_message or "Processing failed",
        CaptureSessionStatus.cancelled: "Cancelled",
    }
    return {
        "id": session.id,
        "status": session.status,
        "progress": session.progress,
        "tour_id": session.tour_id,
        "error_message": session.error_message,
        "frame_count": frame_count,
        "message": messages.get(session.status),
    }
