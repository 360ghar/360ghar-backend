"""generate_tour completion path (review item 1, tours-web-0, be-tours-19).

The worker writes ``generated`` as a list. update_job_status validates a completed
result against the job type, so the stored job must be ``completed``, not ``failed``.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.models.enums import AIJobStatus, AIJobType, TourStatus, TourVisibility
from app.models.tours import Scene, Tour
from app.services.tour import get_tour
from app.services.tour_ai.jobs import create_ai_job, update_job_status


async def _worker_result(db_session, user, *, generated) -> dict:
    """Build the result exactly as _run_tour_generation does after the last scene write."""
    tour_row = Tour(
        id="11111111-1111-1111-1111-111111111111",
        user_id=user.id,
        title="Generated",
        status=TourStatus.draft,
        is_public=False,
        visibility=TourVisibility.private,
    )
    scene_row = Scene(
        id="22222222-2222-2222-2222-222222222222",
        tour_id=tour_row.id,
        title="Kitchen",
        image_url="https://res.cloudinary.com/demo/image/upload/kitchen.jpg",
        order_index=0,
    )
    db_session.add_all([tour_row, scene_row])
    await db_session.commit()

    tour = await get_tour(db_session, tour_row.id, user.id, include_scenes=True)
    scenes_summary = [
        {
            "id": s.id,
            "title": s.title,
            "description": s.description,
            "image_url": s.image_url,
            "thumbnail_url": s.thumbnail_url,
            "hotspot_count": len(s.hotspots or []),
        }
        for s in (tour.scenes or [])
    ]
    return {
        "tour_id": tour.id,
        "tour": {
            "id": tour.id,
            "user_id": tour.user_id,
            "title": tour.title,
            "description": tour.description,
            "status": tour.status,
            "is_public": tour.is_public,
            "visibility": tour.visibility,
            "settings": tour.settings,
            "is_featured": tour.is_featured,
            "view_count": tour.view_count,
            "like_count": tour.like_count,
            "share_count": tour.share_count,
            "thumbnail_url": tour.thumbnail_url,
            "published_at": tour.published_at,
            "archived_at": tour.archived_at,
            "created_at": tour.created_at.isoformat() if tour.created_at else None,
            "updated_at": tour.updated_at.isoformat() if tour.updated_at else None,
            "deleted_at": None,
            "scene_count": len(tour.scenes or []),
        },
        "generated": generated,
        "created_hotspots": [],
        "scenes": scenes_summary,
    }


@pytest.mark.asyncio
async def test_generate_tour_completion_with_a_list_of_results_is_completed(db_session, test_user):
    job = await create_ai_job(db_session, test_user.id, AIJobType.generate_tour)
    generated = [
        {
            "scene_id": "22222222-2222-2222-2222-222222222222",
            "title": "Kitchen",
            "room_type": "kitchen",
        }
    ]
    result = await _worker_result(db_session, test_user, generated=generated)

    updated = await update_job_status(db_session, job.id, "completed", 100, result=result)

    assert updated.status == AIJobStatus.completed.value
    assert updated.error_message is None
    assert updated.result["generated"] == generated
    assert updated.result["tour"]["id"] == "11111111-1111-1111-1111-111111111111"
    assert updated.result["scenes"][0]["title"] == "Kitchen"


@pytest.mark.asyncio
async def test_generate_tour_completion_with_an_empty_list_is_completed(db_session, test_user):
    job = await create_ai_job(db_session, test_user.id, AIJobType.generate_tour)
    result = await _worker_result(db_session, test_user, generated=[])

    updated = await update_job_status(db_session, job.id, "completed", 100, result=result)

    assert updated.status == "completed"
    assert updated.result["generated"] == []


@pytest.mark.asyncio
async def test_generate_tour_completion_rejects_a_dict_generated(db_session, test_user):
    """The old shape (a dict) is no longer valid. The schema is the list."""
    job = await create_ai_job(db_session, test_user.id, AIJobType.generate_tour)
    result = await _worker_result(db_session, test_user, generated={})

    with pytest.raises(ValidationError):
        await update_job_status(db_session, job.id, "completed", 100, result=result)
