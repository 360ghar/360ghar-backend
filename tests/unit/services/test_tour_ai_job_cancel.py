"""AI job cancel and terminal-state tests (tours-web-25, branch-drift-29, tours-web-12)."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select, update

from app.models.enums import AIJobType
from app.models.tours import AIJob
from app.services.tour_ai.helpers import _run_with_semaphore
from app.services.tour_ai.jobs import AIJobCancelledError, create_ai_job, update_job_status


async def _job(db_session, user, status: str = "processing") -> AIJob:
    job = AIJob(
        id=str(uuid.uuid4()),
        user_id=user.id,
        job_type=AIJobType.generate_tour.value,
        status=status,
        progress=10,
    )
    db_session.add(job)
    await db_session.flush()
    return job


async def _stored_status(db_session, job_id: str) -> str:
    result = await db_session.execute(
        select(AIJob.status).where(AIJob.id == job_id).execution_options(populate_existing=True)
    )
    return result.scalar_one()


@pytest.mark.asyncio
async def test_write_to_a_cancelled_job_stops_the_worker(db_session, test_user):
    job = await _job(db_session, test_user, status="cancelled")
    with pytest.raises(AIJobCancelledError):
        await update_job_status(db_session, job.id, "processing", 50)
    assert await _stored_status(db_session, job.id) == "cancelled"


@pytest.mark.asyncio
async def test_cancel_from_another_session_is_seen_on_the_next_write(db_session, test_user):
    job = await _job(db_session, test_user, status="processing")
    # Load the row into the identity map, then cancel with a Core UPDATE that does not sync it.
    await update_job_status(db_session, job.id, "processing", 20)
    await db_session.execute(
        update(AIJob)
        .where(AIJob.id == job.id)
        .values(status="cancelled")
        .execution_options(synchronize_session=False)
    )
    with pytest.raises(AIJobCancelledError):
        await update_job_status(db_session, job.id, "processing", 60)


@pytest.mark.asyncio
async def test_late_write_cannot_move_a_completed_job(db_session, test_user):
    job = await _job(db_session, test_user, status="completed")
    returned = await update_job_status(db_session, job.id, "processing", 40)
    assert returned.status == "completed"
    assert await _stored_status(db_session, job.id) == "completed"


@pytest.mark.asyncio
async def test_create_ai_job_stores_the_enum_value(db_session, test_user):
    job = await create_ai_job(db_session, test_user.id, AIJobType.suggest_tour_hotspots)
    assert job.job_type == "suggest_tour_hotspots"


@pytest.mark.asyncio
async def test_background_runner_stops_quietly_when_the_job_is_cancelled():
    async def _cancelled_worker():
        raise AIJobCancelledError("job")

    await _run_with_semaphore(_cancelled_worker())
