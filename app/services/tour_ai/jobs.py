"""
AI Job management for tour AI operations.

Provides CRUD operations for AI processing jobs, including creation,
status updates with WebSocket broadcasting, retrieval, and cancellation.
"""
from __future__ import annotations

from typing import Any
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundException
from app.core.logging import get_logger
from app.core.utils import utc_now
from app.core.websocket import manager as ws_manager
from app.models.tours import AIJob
from app.schemas.pagination import keyset_filter, keyset_payload, keyset_sort_value

logger = get_logger(__name__)


async def create_ai_job(
    db: AsyncSession,
    user_id: int,
    job_type: str,
    tour_id: str | None = None,
    scene_id: str | None = None
) -> AIJob:
    """Create a new AI processing job."""
    job = AIJob(
        id=str(uuid4()),
        user_id=user_id,
        tour_id=tour_id,
        scene_id=scene_id,
        job_type=job_type,
        status="pending",
        progress=0
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)
    logger.info("AI job created: %s (type: %s)", job.id, job_type)
    return job


async def update_job_status(
    db: AsyncSession,
    job_id: str,
    status: str,
    progress: int = 0,
    result: dict[str, Any] | None = None,
    error_message: str | None = None,
    increment_retry: bool = False
) -> AIJob:
    """Update an AI job's status and broadcast via WebSocket."""
    query = select(AIJob).where(AIJob.id == job_id)
    db_result = await db.execute(query)
    job = db_result.scalar_one_or_none()

    if not job:
        raise NotFoundException(detail="AI job not found")

    job.status = status
    job.progress = progress

    if increment_retry:
        job.retry_count = (job.retry_count or 0) + 1

    if status == "processing" and not job.started_at:
        job.started_at = utc_now()

    if status in ("completed", "failed", "cancelled"):
        job.completed_at = utc_now()

    if result:
        job.result = result

    if error_message:
        job.error_message = error_message

    await db.commit()
    await db.refresh(job)

    # Broadcast update via WebSocket
    try:
        ws_update = {
            "status": status,
            "progress": progress,
            "result": result,
            "error_message": error_message,
        }
        await ws_manager.send_job_update(job_id, ws_update)

        # Send completion/error notifications to user
        if status == "completed" and result:
            await ws_manager.broadcast_job_completion(job_id, job.user_id, result)
        elif status == "failed" and error_message:
            await ws_manager.broadcast_job_error(job_id, job.user_id, error_message)
    except Exception as e:
        # Don't fail the job update if WebSocket broadcast fails
        logger.warning("Failed to broadcast job update via WebSocket: %s", e)

    return job


async def get_ai_job(
    db: AsyncSession,
    job_id: str,
    user_id: int | None = None
) -> AIJob:
    """Get an AI job by ID."""
    query = select(AIJob).where(AIJob.id == job_id)

    if user_id is not None:
        query = query.where(AIJob.user_id == user_id)

    result = await db.execute(query)
    job = result.scalar_one_or_none()

    if not job:
        raise NotFoundException(detail="AI job not found")

    return job


async def get_user_ai_jobs(
    db: AsyncSession,
    user_id: int,
    status_filter: str | None = None,
    *,
    cursor_payload: dict | None = None,
    limit: int = 20,
    with_total: bool = False,
) -> tuple[list[AIJob], dict | None, int | None]:
    """Get AI jobs for a user (keyset pagination on created_at)."""
    if cursor_payload is None:
        cursor_payload = {}

    stmt = select(AIJob).where(AIJob.user_id == user_id)

    if status_filter:
        stmt = stmt.where(AIJob.status == status_filter)

    count_total: int | None = None
    if with_total:
        count_total = (
            await db.execute(select(func.count()).select_from(stmt.subquery()))
        ).scalar_one()

    predicate = keyset_filter(AIJob.created_at, AIJob.id, cursor_payload, descending=True)
    if predicate is not None:
        stmt = stmt.where(predicate)

    stmt = stmt.order_by(AIJob.created_at.desc(), AIJob.id.desc()).limit(limit + 1)
    rows = list((await db.execute(stmt)).scalars().all())

    next_pg: dict | None = None
    if len(rows) > limit:
        rows = rows[:limit]
        next_pg = keyset_payload(keyset_sort_value(rows[-1].created_at), rows[-1].id)

    return rows, next_pg, count_total


async def cancel_ai_job(
    db: AsyncSession,
    job_id: str,
    user_id: int
) -> bool:
    """Cancel an AI job."""
    job = await get_ai_job(db, job_id, user_id)

    if job.status in ("completed", "failed", "cancelled"):
        return False

    job.status = "cancelled"
    job.completed_at = utc_now()
    await db.commit()

    logger.info("AI job cancelled: %s", job_id)
    return True
