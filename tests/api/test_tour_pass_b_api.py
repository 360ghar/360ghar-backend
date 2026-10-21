"""API tests for the BE-tours pass B contract fixes.

Each test names the ledger item it guards. Setup rows are written with
``db_session``; routes are called with ``user_client`` (owner) or
``guest_client`` (anonymous viewer).
"""

from __future__ import annotations

import uuid

import pytest

from app.models.enums import TourStatus, TourVisibility
from app.models.tours import FloorPlan, Hotspot, Scene, Tour

_IMG = "https://res.cloudinary.com/demo/image/upload/room.jpg"


async def _tour(
    db_session, owner, *, status=TourStatus.published, visibility=TourVisibility.public
):
    tour = Tour(
        id=str(uuid.uuid4()),
        user_id=owner.id,
        title="Pass B Tour",
        status=status,
        is_public=visibility == TourVisibility.public,
        visibility=visibility,
    )
    db_session.add(tour)
    await db_session.flush()
    return tour


async def _scene(db_session, tour: Tour) -> Scene:
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
    return scene


def _hotspot(scene: Scene, *, title: str, is_active: bool = True) -> Hotspot:
    return Hotspot(
        id=str(uuid.uuid4()),
        scene_id=scene.id,
        type="info",
        position={"yaw": 0.0, "pitch": 0.0},
        title=title,
        order_index=0,
        is_active=is_active,
    )


# r2-route-matrix-23: routes with no client caller are removed.
@pytest.mark.asyncio
async def test_get_scene_by_id_route_is_removed(user_client, db_session, test_user):
    tour = await _tour(
        db_session, test_user, status=TourStatus.draft, visibility=TourVisibility.private
    )
    scene = await _scene(db_session, tour)
    response = await user_client.get(f"/api/v1/scenes/{scene.id}")
    assert response.status_code == 405, response.text


@pytest.mark.asyncio
async def test_get_hotspot_by_id_route_is_removed(user_client, db_session, test_user):
    tour = await _tour(
        db_session, test_user, status=TourStatus.draft, visibility=TourVisibility.private
    )
    scene = await _scene(db_session, tour)
    hotspot = _hotspot(scene, title="Gone")
    db_session.add(hotspot)
    await db_session.flush()
    response = await user_client.get(f"/api/v1/hotspots/{hotspot.id}")
    assert response.status_code == 405, response.text


@pytest.mark.asyncio
async def test_capture_status_route_is_removed(user_client):
    response = await user_client.get(f"/api/v1/capture-sessions/{uuid.uuid4()}/status")
    assert response.status_code == 404, response.text


# be-tours-17: public viewers do not receive inactive hotspots.
@pytest.mark.asyncio
async def test_public_tour_hides_inactive_hotspots(guest_client, db_session, test_user):
    tour = await _tour(db_session, test_user)
    scene = await _scene(db_session, tour)
    db_session.add(_hotspot(scene, title="Visible"))
    db_session.add(_hotspot(scene, title="Hidden", is_active=False))
    await db_session.flush()
    response = await guest_client.get(f"/api/v1/public/tours/{tour.id}", params={"track": "false"})
    assert response.status_code == 200, response.text
    titles = [h["title"] for h in response.json()["scenes"][0]["hotspots"]]
    assert titles == ["Visible"]


@pytest.mark.asyncio
async def test_public_scenes_list_hides_inactive_hotspots(guest_client, db_session, test_user):
    tour = await _tour(db_session, test_user)
    scene = await _scene(db_session, tour)
    db_session.add(_hotspot(scene, title="Hidden", is_active=False))
    await db_session.flush()
    response = await guest_client.get(f"/api/v1/public/tours/{tour.id}/scenes")
    assert response.status_code == 200, response.text
    assert response.json()["items"][0]["hotspots"] == []


# tours-web-31: PATCH null on custom_data is a 422, not a silent clear.
@pytest.mark.asyncio
async def test_hotspot_patch_null_custom_data_is_422(user_client, db_session, test_user):
    tour = await _tour(
        db_session, test_user, status=TourStatus.draft, visibility=TourVisibility.private
    )
    scene = await _scene(db_session, tour)
    hotspot = _hotspot(scene, title="Edit me")
    db_session.add(hotspot)
    await db_session.flush()
    response = await user_client.patch(f"/api/v1/hotspots/{hotspot.id}", json={"custom_data": None})
    assert response.status_code == 422, response.text


# tours-web-30: an unknown branding enum value is rejected on write.
@pytest.mark.asyncio
async def test_tour_patch_rejects_unknown_button_style(user_client, db_session, test_user):
    tour = await _tour(
        db_session, test_user, status=TourStatus.draft, visibility=TourVisibility.private
    )
    response = await user_client.patch(
        f"/api/v1/tours/{tour.id}",
        json={"settings": {"branding": {"button_style": "round"}}},
    )
    assert response.status_code == 422, response.text


# Floor-plan markers: unknown keys are rejected on the markers route.
@pytest.mark.asyncio
async def test_floor_plan_markers_put_rejects_unknown_marker_keys(
    user_client, db_session, test_user
):
    tour = await _tour(
        db_session, test_user, status=TourStatus.draft, visibility=TourVisibility.private
    )
    scene = await _scene(db_session, tour)
    plan = FloorPlan(
        id=str(uuid.uuid4()),
        tour_id=tour.id,
        name="Ground",
        image_url=_IMG,
        floor_number=1,
        markers=[],
    )
    db_session.add(plan)
    await db_session.flush()
    response = await user_client.put(
        f"/api/v1/tours/{tour.id}/floor-plans/{plan.id}/markers",
        json=[{"scene_id": scene.id, "x": 10, "y": 20, "bogus": True}],
    )
    assert response.status_code == 422, response.text
