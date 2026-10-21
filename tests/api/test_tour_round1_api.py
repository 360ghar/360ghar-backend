"""API tests for the BE-tours fix round 1 (review items 2, 12, 16, 19).

Owner, other-user and anonymous viewers are separate clients. The fixtures set
dependency overrides on the shared test app, so one test uses one client.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from app.models.enums import TourStatus, TourVisibility
from app.models.tours import Scene, Tour, TourAnalyticsEvent

_IMG = "https://res.cloudinary.com/demo/image/upload/room.jpg"


@pytest_asyncio.fixture
async def other_user_client(test_app, test_user_2):
    """Authenticated as a user who does not own the tour."""
    from app.api.api_v1.dependencies.auth import (
        get_current_active_user,
        get_current_cached_active_user,
        get_current_user,
        get_current_user_optional,
    )
    from app.schemas.user import User as UserSchema

    schema = UserSchema.model_validate(test_user_2, from_attributes=True)

    async def _user():
        return schema

    test_app.dependency_overrides[get_current_user] = _user
    test_app.dependency_overrides[get_current_active_user] = _user
    test_app.dependency_overrides[get_current_cached_active_user] = _user
    test_app.dependency_overrides[get_current_user_optional] = _user
    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test", timeout=60.0) as ac:
        yield ac
    test_app.dependency_overrides.clear()


async def _published_tour(db_session, owner) -> tuple[Tour, Scene]:
    tour = Tour(
        id=str(uuid.uuid4()),
        user_id=owner.id,
        title="Round 1",
        status=TourStatus.published,
        is_public=True,
        visibility=TourVisibility.public,
    )
    db_session.add(tour)
    await db_session.flush()
    scene = Scene(
        id=str(uuid.uuid4()),
        tour_id=tour.id,
        title="Room",
        image_url=_IMG,
        order_index=0,
        is_processed=True,
    )
    db_session.add(scene)
    await db_session.flush()
    return tour, scene


# Review item 2: the heatmap is owner only, even for a published tour.
@pytest.mark.asyncio
async def test_heatmap_of_a_published_tour_is_403_for_a_non_owner(
    other_user_client, db_session, test_user
):
    tour, _ = await _published_tour(db_session, test_user)
    response = await other_user_client.get(f"/api/v1/tours/{tour.id}/heatmap")
    assert response.status_code == 403, response.text


@pytest.mark.asyncio
async def test_heatmap_of_a_published_tour_is_200_for_the_owner(user_client, db_session, test_user):
    tour, _ = await _published_tour(db_session, test_user)
    response = await user_client.get(f"/api/v1/tours/{tour.id}/heatmap")
    assert response.status_code == 200, response.text
    assert response.json() == {"tour_id": tour.id, "heatmap": []}


# Review item 19: the public tour response does not carry the owner's user_id.
@pytest.mark.asyncio
async def test_public_tour_response_has_no_user_id(guest_client, db_session, test_user):
    tour, _ = await _published_tour(db_session, test_user)
    response = await guest_client.get(f"/api/v1/public/tours/{tour.id}", params={"track": "false"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert "user_id" not in body
    assert body["main_scene_id"] is not None


# Review item 16 (a): the events route refuses view.
@pytest.mark.asyncio
async def test_public_events_route_refuses_view(guest_client, db_session, test_user):
    tour, _ = await _published_tour(db_session, test_user)
    response = await guest_client.post(
        f"/api/v1/public/tours/{tour.id}/events", json={"event_type": "view"}
    )
    assert response.status_code == 422, response.text


# Review item 16 (b): a random session id does not bypass the per-viewer dedupe.
@pytest.mark.asyncio
async def test_scene_view_dedupe_ignores_a_changing_session_id(guest_client, db_session, test_user):
    tour, scene = await _published_tour(db_session, test_user)
    body = {
        "event_type": "scene_view",
        "scene_id": scene.id,
        "event_data": {"yaw": 10, "pitch": 0},
    }
    for session_id in ("random-a", "random-b", "random-c"):
        response = await guest_client.post(
            f"/api/v1/public/tours/{tour.id}/events",
            json={**body, "session_id": session_id},
        )
        assert response.status_code == 204, response.text

    stored = (
        await db_session.execute(
            select(func.count())
            .select_from(TourAnalyticsEvent)
            .where(TourAnalyticsEvent.tour_id == tour.id, TourAnalyticsEvent.scene_id == scene.id)
        )
    ).scalar_one()
    assert stored == 1


@pytest.mark.asyncio
async def test_like_counts_once_when_the_session_id_changes(guest_client, db_session, test_user):
    tour, _ = await _published_tour(db_session, test_user)
    counts = []
    for session_id in ("liker-1", "liker-2"):
        response = await guest_client.post(
            f"/api/v1/public/tours/{tour.id}/like", headers={"x-session-id": session_id}
        )
        assert response.status_code == 200, response.text
        counts.append(response.json()["like_count"])
    assert counts == [1, 1]


# Review item 12: a nested capture write key that is not declared gives 422.
@pytest.mark.asyncio
async def test_capture_session_create_rejects_an_unknown_nested_key(user_client):
    response = await user_client.post(
        "/api/v1/capture-sessions",
        json={
            "title": "Flat",
            "plan": {"rooms": [{"id": "r1", "label": "Hall", "not_a_key": 1}]},
        },
    )
    assert response.status_code == 422, response.text
