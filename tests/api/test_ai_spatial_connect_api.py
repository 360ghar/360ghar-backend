"""API tests for POST /ai/tours/{tour_id}/connect-spatial.

The route only queues the work: it verifies ownership, creates a
`spatial_connect` AIJob and hands the heavy lifting to a background task. The
background task is dropped here (its own behaviour is covered by the spatial
unit tests), so these tests pin the route contract: path, response shape, job
type, tour scoping and the ownership check.
"""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import select

from app.models.enums import AIJobStatus, AIJobType, TourStatus, TourVisibility
from app.models.tours import AIJob, Tour

_IMG = "https://res.cloudinary.com/demo/image/upload/room.jpg"


async def _tour(db_session, owner) -> Tour:
    tour = Tour(
        id=str(uuid.uuid4()),
        user_id=owner.id,
        title="Spatial Tour",
        status=TourStatus.draft,
        is_public=False,
        visibility=TourVisibility.private,
    )
    db_session.add(tour)
    await db_session.flush()
    return tour


def _drop_background_task(coro):
    """Close the queued coroutine instead of running the pipeline."""
    coro.close()
    return None


@pytest.fixture
def queued_job_only():
    """Keep the route's real logic but never run the background pipeline.

    `_run_spatial_connect` is replaced with a sync mock so calling it creates no
    coroutine, and the task tracker is replaced so the outer coroutine is closed
    rather than scheduled.
    """
    with (
        patch("app.services.tour_ai.background._run_spatial_connect", new=MagicMock()),
        patch(
            "app.services.tour_ai.background._track_background_task",
            side_effect=_drop_background_task,
        ),
    ):
        yield


@pytest.mark.asyncio
async def test_connect_spatial_queues_a_spatial_connect_job(
    user_client, db_session, test_user, queued_job_only
):
    tour = await _tour(db_session, test_user)

    response = await user_client.post(f"/api/v1/ai/tours/{tour.id}/connect-spatial")

    assert response.status_code == 200, response.text
    job = response.json()["job"]
    assert job["job_type"] == "spatial_connect"
    assert job["status"] == "pending"
    assert job["tour_id"] == tour.id

    stored = (
        await db_session.execute(
            select(AIJob).where(AIJob.tour_id == tour.id, AIJob.user_id == test_user.id)
        )
    ).scalar_one()
    assert stored.job_type == AIJobType.spatial_connect
    assert stored.status == AIJobStatus.pending


@pytest.mark.asyncio
async def test_connect_spatial_is_scoped_to_the_owner(
    user_client, db_session, test_user_2, queued_job_only
):
    tour = await _tour(db_session, test_user_2)

    response = await user_client.post(f"/api/v1/ai/tours/{tour.id}/connect-spatial")

    assert response.status_code in (403, 404), response.text
    jobs = (await db_session.execute(select(AIJob).where(AIJob.tour_id == tour.id))).scalars().all()
    assert jobs == []


@pytest.mark.asyncio
async def test_connect_spatial_requires_authentication(client, db_session, test_user):
    tour = await _tour(db_session, test_user)

    response = await client.post(f"/api/v1/ai/tours/{tour.id}/connect-spatial")

    assert response.status_code in (401, 403), response.text
