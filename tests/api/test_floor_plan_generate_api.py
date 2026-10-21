"""API tests for POST /tours/{tour_id}/floor-plans/generate.

The endpoint is synchronous and deterministic: it reads the scenes' stored room
types and navigation hotspots, renders a schematic PNG (Pillow), uploads it
(mocked here), and saves or updates one floor-plan row.
"""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

import pytest

from app.models.enums import HotspotType, TourStatus, TourVisibility
from app.models.tours import Hotspot, Scene, Tour

_IMG = "https://res.cloudinary.com/demo/image/upload/room.jpg"
_GENERATED_URL = "https://res.cloudinary.com/demo/image/upload/generated_layout.png"


async def _tour(db_session, owner, *, settings=None) -> Tour:
    tour = Tour(
        id=str(uuid.uuid4()),
        user_id=owner.id,
        title="Layout Tour",
        status=TourStatus.draft,
        is_public=False,
        visibility=TourVisibility.private,
        settings=settings,
    )
    db_session.add(tour)
    await db_session.flush()
    return tour


async def _scene(db_session, tour: Tour, order_index: int, title: str, room_type=None) -> Scene:
    scene = Scene(
        id=str(uuid.uuid4()),
        tour_id=tour.id,
        title=title,
        image_url=_IMG,
        order_index=order_index,
        scene_metadata={"room_type": room_type} if room_type else None,
        is_processed=True,
    )
    db_session.add(scene)
    await db_session.flush()
    return scene


async def _nav(db_session, scene: Scene, target_scene_id: str, yaw: float) -> Hotspot:
    hotspot = Hotspot(
        id=str(uuid.uuid4()),
        scene_id=scene.id,
        type=HotspotType.navigation,
        position={"yaw": yaw, "pitch": -28.0},
        target_scene_id=target_scene_id,
        title="Go here",
        custom_data={"auto_generated": True, "spatial": True},
        order_index=0,
        is_active=True,
    )
    db_session.add(hotspot)
    await db_session.flush()
    return hotspot


def _mock_upload() -> MagicMock:
    upload = MagicMock()
    upload.upload_file.return_value = {"secure_url": _GENERATED_URL}
    return upload


@pytest.mark.asyncio
async def test_generate_creates_plan_with_markers_and_uploads_png(
    user_client, db_session, test_user
):
    tour = await _tour(db_session, test_user)
    living = await _scene(db_session, tour, 0, "Living room", "living_room")
    kitchen = await _scene(db_session, tour, 1, "Kitchen", "kitchen")
    tour.settings = {"initial_scene_id": living.id}
    await _nav(db_session, living, kitchen.id, -90.0)
    await _nav(db_session, kitchen, living.id, 90.0)
    await db_session.flush()

    upload = _mock_upload()
    with patch("app.services.tour.floor_plans.get_cloudinary_service", return_value=upload):
        response = await user_client.post(f"/api/v1/tours/{tour.id}/floor-plans/generate")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["name"] == "Estimated layout (AI)"
    assert body["image_url"] == _GENERATED_URL
    assert body["floor_number"] == 1
    assert {marker["scene_id"] for marker in body["markers"]} == {living.id, kitchen.id}
    for marker in body["markers"]:
        assert 0 <= marker["x"] <= 100
        assert 0 <= marker["y"] <= 100
        assert marker["label"]

    _, kwargs = upload.upload_file.call_args
    assert kwargs["content_type"] == "image/png"
    assert kwargs["file_bytes"].startswith(b"\x89PNG")
    assert kwargs["folder"] == f"tours/{tour.id}/floor-plans"


@pytest.mark.asyncio
async def test_regenerate_replaces_the_generated_plan(user_client, db_session, test_user):
    tour = await _tour(db_session, test_user)
    living = await _scene(db_session, tour, 0, "Living room", "living_room")
    kitchen = await _scene(db_session, tour, 1, "Kitchen", "kitchen")
    await _nav(db_session, living, kitchen.id, -90.0)

    upload = _mock_upload()
    with patch("app.services.tour.floor_plans.get_cloudinary_service", return_value=upload):
        first = await user_client.post(f"/api/v1/tours/{tour.id}/floor-plans/generate")
        second = await user_client.post(f"/api/v1/tours/{tour.id}/floor-plans/generate")

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert first.json()["id"] == second.json()["id"]

    listed = await user_client.get(f"/api/v1/tours/{tour.id}/floor-plans")
    assert listed.status_code == 200, listed.text
    generated = [
        plan for plan in listed.json()["items"] if plan["name"] == "Estimated layout (AI)"
    ]
    assert len(generated) == 1


@pytest.mark.asyncio
async def test_generate_needs_at_least_two_scenes(user_client, db_session, test_user):
    tour = await _tour(db_session, test_user)
    await _scene(db_session, tour, 0, "Only room", "living_room")

    response = await user_client.post(f"/api/v1/tours/{tour.id}/floor-plans/generate")
    assert response.status_code == 400, response.text


@pytest.mark.asyncio
async def test_generate_is_scoped_to_the_owner(user_client, db_session, test_user_2):
    tour = await _tour(db_session, test_user_2)
    await _scene(db_session, tour, 0, "Living", "living_room")
    await _scene(db_session, tour, 1, "Kitchen", "kitchen")

    response = await user_client.post(f"/api/v1/tours/{tour.id}/floor-plans/generate")
    assert response.status_code in (403, 404), response.text
