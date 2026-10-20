"""API tests for the BE-tours fix round 2 (review items 12, 13, 14, 8, 9, 7).

The owner uses ``user_client``, another user ``other_user_client`` and an anonymous
viewer ``guest_client``. Rows are written with ``db_session``.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.models.enums import TourStatus, TourVisibility
from app.models.tours import Hotspot, Scene, Tour

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
    from app.schemas.user import SelfUser as UserSchema

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


async def _tour(db_session, owner, *, status, visibility) -> Tour:
    tour = Tour(
        id=str(uuid.uuid4()),
        user_id=owner.id,
        title="Round 2",
        status=status,
        is_public=visibility == TourVisibility.public,
        visibility=visibility,
    )
    db_session.add(tour)
    await db_session.flush()
    return tour


async def _scene(db_session, tour: Tour, *, metadata=None, error=None) -> Scene:
    scene = Scene(
        id=str(uuid.uuid4()),
        tour_id=tour.id,
        title="Room",
        image_url=_IMG,
        order_index=0,
        is_processed=True,
        scene_metadata=metadata,
        processing_error=error,
    )
    db_session.add(scene)
    await db_session.flush()
    return scene


def _hotspot(scene: Scene, *, title: str, is_active: bool) -> Hotspot:
    return Hotspot(
        id=str(uuid.uuid4()),
        scene_id=scene.id,
        type="info",
        position={"yaw": 0.0, "pitch": 0.0},
        title=title,
        order_index=0,
        is_active=is_active,
    )


# Review item 12: the owner shape is for the owner only.
@pytest.mark.asyncio
async def test_owner_gets_the_owner_shape_with_user_id(user_client, db_session, test_user):
    tour = await _tour(
        db_session, test_user, status=TourStatus.published, visibility=TourVisibility.public
    )
    await _scene(db_session, tour)
    response = await user_client.get(f"/api/v1/tours/{tour.id}")
    assert response.status_code == 200, response.text
    assert response.json()["user_id"] == test_user.id


@pytest.mark.asyncio
async def test_non_owner_of_a_published_tour_gets_the_public_shape(
    other_user_client, db_session, test_user
):
    tour = await _tour(
        db_session, test_user, status=TourStatus.published, visibility=TourVisibility.public
    )
    scene = await _scene(db_session, tour, error="raw failure text")
    db_session.add_all(
        [
            _hotspot(scene, title="Shown", is_active=True),
            _hotspot(scene, title="Hidden", is_active=False),
        ]
    )
    await db_session.flush()

    response = await other_user_client.get(f"/api/v1/tours/{tour.id}")
    assert response.status_code == 200, response.text
    body = response.json()
    assert "user_id" not in body
    assert body["main_scene_id"] == scene.id
    titles = [h["title"] for h in body["scenes"][0]["hotspots"]]
    assert titles == ["Shown"]
    assert "processing_error" not in body["scenes"][0]


@pytest.mark.asyncio
async def test_non_owner_of_a_foreign_draft_gets_404_not_403(
    other_user_client, db_session, test_user
):
    tour = await _tour(
        db_session, test_user, status=TourStatus.draft, visibility=TourVisibility.private
    )
    await _scene(db_session, tour)
    response = await other_user_client.get(f"/api/v1/tours/{tour.id}")
    assert response.status_code == 404, response.text
    assert response.json()["error"]["code"]


@pytest.mark.asyncio
async def test_anonymous_public_tour_has_no_user_id_and_no_exif(
    guest_client, db_session, test_user
):
    tour = await _tour(
        db_session, test_user, status=TourStatus.published, visibility=TourVisibility.public
    )
    await _scene(
        db_session,
        tour,
        metadata={"exif": {"camera": {"make": "Apple"}}, "room_type": "kitchen"},
        error="raw failure text",
    )
    response = await guest_client.get(f"/api/v1/public/tours/{tour.id}?track=false")
    assert response.status_code == 200, response.text
    body = response.json()
    assert "user_id" not in body
    assert "exif" not in body["scenes"][0]["scene_metadata"]
    assert body["scenes"][0]["scene_metadata"]["room_type"] == "kitchen"
    assert "processing_error" not in body["scenes"][0]


@pytest.mark.asyncio
async def test_public_scenes_list_uses_the_public_scene_shape(guest_client, db_session, test_user):
    tour = await _tour(
        db_session, test_user, status=TourStatus.published, visibility=TourVisibility.public
    )
    scene = await _scene(
        db_session, tour, metadata={"exif": {"camera": {"make": "Apple"}}}, error="raw"
    )
    db_session.add_all(
        [
            _hotspot(scene, title="Shown", is_active=True),
            _hotspot(scene, title="Hidden", is_active=False),
        ]
    )
    await db_session.flush()
    response = await guest_client.get(f"/api/v1/public/tours/{tour.id}/scenes")
    assert response.status_code == 200, response.text
    item = response.json()["items"][0]
    assert "processing_error" not in item
    assert "exif" not in (item["scene_metadata"] or {})
    assert [h["title"] for h in item["hotspots"]] == ["Shown"]


# Review item 8 and 9: the visibility rules hold across publish, unpublish and duplicate.
@pytest.mark.asyncio
async def test_unlisted_tour_stays_unlisted_through_unpublish_and_publish(
    user_client, db_session, test_user
):
    tour = await _tour(
        db_session, test_user, status=TourStatus.draft, visibility=TourVisibility.unlisted
    )
    await _scene(db_session, tour)

    published = await user_client.post(f"/api/v1/tours/{tour.id}/publish")
    assert published.status_code == 200, published.text
    assert published.json()["visibility"] == "unlisted"
    assert published.json()["is_public"] is False

    unpublished = await user_client.post(f"/api/v1/tours/{tour.id}/unpublish")
    assert unpublished.status_code == 200, unpublished.text
    assert unpublished.json()["visibility"] == "unlisted"

    again = await user_client.post(f"/api/v1/tours/{tour.id}/publish")
    assert again.status_code == 200, again.text
    assert again.json()["visibility"] == "unlisted"


@pytest.mark.asyncio
async def test_public_tour_unpublish_makes_it_private(user_client, db_session, test_user):
    tour = await _tour(
        db_session, test_user, status=TourStatus.published, visibility=TourVisibility.public
    )
    await _scene(db_session, tour)
    unpublished = await user_client.post(f"/api/v1/tours/{tour.id}/unpublish")
    assert unpublished.status_code == 200, unpublished.text
    assert unpublished.json()["visibility"] == "private"
    assert unpublished.json()["is_public"] is False


@pytest.mark.asyncio
async def test_duplicate_of_a_public_draft_has_is_public_in_sync(
    user_client, db_session, test_user
):
    tour = await _tour(
        db_session, test_user, status=TourStatus.draft, visibility=TourVisibility.public
    )
    await _scene(db_session, tour)
    response = await user_client.post(f"/api/v1/tours/{tour.id}/duplicate")
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["visibility"] == "public"
    assert body["is_public"] is True
    assert body["status"] == "draft"


# Review item 7: a repeat of the current terminal status returns the row unchanged.
@pytest.mark.asyncio
async def test_repeat_failed_patch_keeps_the_first_error_message(user_client):
    created = await user_client.post("/api/v1/capture-sessions", json={"title": "Capture"})
    assert created.status_code == 201, created.text
    session_id = created.json()["id"]

    first = await user_client.patch(
        f"/api/v1/capture-sessions/{session_id}",
        json={"status": "failed", "error_message": "first"},
    )
    assert first.status_code == 200, first.text
    assert first.json()["error_message"] == "first"

    repeat = await user_client.patch(
        f"/api/v1/capture-sessions/{session_id}",
        json={"status": "failed", "error_message": "second"},
    )
    assert repeat.status_code == 200, repeat.text
    assert repeat.json()["status"] == "failed"
    assert repeat.json()["error_message"] == "first"


@pytest.mark.asyncio
async def test_terminal_session_rejects_a_different_status(user_client):
    created = await user_client.post("/api/v1/capture-sessions", json={"title": "Capture"})
    session_id = created.json()["id"]
    failed = await user_client.patch(
        f"/api/v1/capture-sessions/{session_id}", json={"status": "failed"}
    )
    assert failed.status_code == 200, failed.text
    moved = await user_client.patch(
        f"/api/v1/capture-sessions/{session_id}", json={"status": "capturing"}
    )
    assert moved.status_code == 400, moved.text
