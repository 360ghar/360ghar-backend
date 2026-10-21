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
from app.schemas.pagination import keyset_filter, keyset_sort_value, trim_keyset_lookahead

logger = get_logger(__name__)

# Terminal states. Nothing moves out of these.
_TERMINAL = {
    CaptureSessionStatus.ready,
    CaptureSessionStatus.failed,
    CaptureSessionStatus.cancelled,
}

# The whole state machine. Every path checks it: PATCH (client), complete (server
# or client) and cancel. Any non-terminal state may move to failed.
#
#   draft -> capturing -> review -> uploading -> processing -> ready
#                                   (complete_session drives processing -> ready)
#
# A client PATCH may move: draft->capturing, capturing->review, review->capturing,
# review->uploading, uploading->review, and any non-terminal state -> failed.
# processing and ready are server-owned.
_CLIENT_TRANSITIONS: dict[CaptureSessionStatus, frozenset[CaptureSessionStatus]] = {
    CaptureSessionStatus.draft: frozenset(
        {CaptureSessionStatus.capturing, CaptureSessionStatus.failed}
    ),
    CaptureSessionStatus.capturing: frozenset(
        {CaptureSessionStatus.review, CaptureSessionStatus.failed}
    ),
    CaptureSessionStatus.review: frozenset(
        {
            CaptureSessionStatus.capturing,
            CaptureSessionStatus.uploading,
            CaptureSessionStatus.failed,
        }
    ),
    CaptureSessionStatus.uploading: frozenset(
        {CaptureSessionStatus.review, CaptureSessionStatus.failed}
    ),
    CaptureSessionStatus.processing: frozenset({CaptureSessionStatus.failed}),
}

# States from which complete_session may start processing.
_COMPLETABLE = frozenset(
    {CaptureSessionStatus.capturing, CaptureSessionStatus.review, CaptureSessionStatus.uploading}
)


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


async def list_sessions_page(
    db: AsyncSession,
    user_id: int,
    *,
    status_filter: CaptureSessionStatus | None,
    cursor_payload: dict[str, Any],
    limit: int,
    include_total: bool = False,
) -> tuple[list[dict], dict[str, Any] | None, int | None]:
    """One keyset page of the user's sessions, newest first. total is set only with include_total."""
    base = select(CaptureSession).where(CaptureSession.user_id == user_id)
    if status_filter is not None:
        base = base.where(CaptureSession.status == status_filter)
    total: int | None = None
    if include_total:
        total = int(
            (await db.execute(select(func.count()).select_from(base.subquery()))).scalar_one()
        )

    # Correlated scalar subquery keeps the count work bounded to the page rows
    # (a global GROUP BY would aggregate every frame of every user).
    frame_count_expr = (
        select(func.count(CaptureFrame.id))
        .where(CaptureFrame.session_id == CaptureSession.id)
        .correlate(CaptureSession)
        .scalar_subquery()
    )

    stmt = base.add_columns(frame_count_expr.label("frame_count"))
    predicate = keyset_filter(
        CaptureSession.created_at, CaptureSession.id, cursor_payload, descending=True
    )
    if predicate is not None:
        stmt = stmt.where(predicate)
    stmt = stmt.order_by(CaptureSession.created_at.desc(), CaptureSession.id.desc()).limit(
        limit + 1
    )

    rows = (await db.execute(stmt)).all()
    page_rows, next_payload = trim_keyset_lookahead(
        rows,
        limit=limit,
        sort_value=lambda row: keyset_sort_value(row[0].created_at),
        item_id=lambda row: row[0].id,
    )
    items = [_session_to_dict(session, int(count or 0)) for session, count in page_rows]
    return items, next_payload, total


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
    if new_status is not None:
        # The terminal check runs for every PATCH that sends a status. A repeat of the
        # current terminal status returns the row unchanged, with no write.
        if session.status in _TERMINAL:
            if new_status == session.status:
                return await get_session_response(db, session_id, user_id)
            raise BadRequestException(
                detail=f"Session in status {session.status.value} cannot change status"
            )
        if new_status != session.status:
            allowed = _CLIENT_TRANSITIONS.get(session.status, frozenset())
            if new_status not in allowed:
                raise BadRequestException(
                    detail=(
                        f"Status transition {session.status.value} -> "
                        f"{new_status.value} is not allowed via PATCH"
                    )
                )

    updates = data.model_dump(exclude_unset=True)
    # error_message is only written with a transition to failed.
    updates.pop("error_message", None)
    if new_status == CaptureSessionStatus.failed:
        session.error_message = data.error_message or "Failed by client"
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
    if session.status not in _COMPLETABLE:
        raise BadRequestException(
            detail=f"Cannot complete a session in status {session.status.value}"
        )

    frame_count = len(session.frames or [])
    if frame_count == 0:
        raise BadRequestException(detail="Cannot complete a session with no frames")

    session.status = CaptureSessionStatus.processing
    session.progress = 50
    await db.commit()

    # Phase 0: no stitch worker yet, so park as ready without tour_id.
    # The stitch worker, when it lands, moves processing -> ready or failed.
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
