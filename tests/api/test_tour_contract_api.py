"""API tests for the tour contract fixes (BE-tours slice).

Each test names the ledger item it guards. Setup rows are written with
``db_session`` and the routes are called through ``user_client`` (the owner)
and ``guest_client`` (anonymous viewers).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select

from app.models.enums import TourStatus, TourVisibility
from app.models.tours import (
    FloorPlan,
    Hotspot,
    MediaFile,
    Scene,
    Tour,
    TourAnalyticsEvent,
    TourLike,
)

_IMG = "https://res.cloudinary.com/demo/image/upload/room.jpg"


async def _tour(
    db_session,
    owner,
    *,
    status=TourStatus.published,
    visibility=TourVisibility.public,
    settings=None,
    short_code=None,
) -> Tour:
    tour = Tour(
        id=str(uuid.uuid4()),
        user_id=owner.id,
        title="Contract Tour",
        status=status,
        is_public=visibility == TourVisibility.public,
        visibility=visibility,
        short_code=short_code,
        settings=settings,
    )
    db_session.add(tour)
    await db_session.flush()
    return tour


async def _scene(db_session, tour: Tour, order_index: int = 0, metadata=None) -> Scene:
    scene = Scene(
        id=str(uuid.uuid4()),
        tour_id=tour.id,
        title=f"Room {order_index}",
        image_url=_IMG,
        order_index=order_index,
        scene_metadata=metadata,
        is_processed=True,
    )
    db_session.add(scene)
    await db_session.flush()
    return scene


# -----------------------------------------------------------------------------
# Tours (be-tours-2, be-tours-3, be-tours-4, tours-web-23)
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_rows_carry_short_code(user_client, db_session, test_user):
    """be-tours-2: list rows return the short code."""
    await _tour(db_session, test_user, short_code="abc234")
    response = await user_client.get("/api/v1/tours")
    assert response.status_code == 200, response.text
    items = response.json()["items"]
    assert any(item["short_code"] == "abc234" for item in items)


@pytest.mark.asyncio
async def test_list_total_is_null_unless_requested(user_client, db_session, test_user):
    await _tour(db_session, test_user)
    plain = (await user_client.get("/api/v1/tours")).json()
    assert plain["total"] is None
    counted = (await user_client.get("/api/v1/tours", params={"include_total": "true"})).json()
    assert counted["total"] >= 1


@pytest.mark.asyncio
async def test_patch_tour_status_is_rejected(user_client, db_session, test_user):
    """be-tours-4: status changes go through publish, unpublish and delete only."""
    tour = await _tour(
        db_session, test_user, status=TourStatus.draft, visibility=TourVisibility.private
    )
    response = await user_client.patch(f"/api/v1/tours/{tour.id}", json={"status": "published"})
    assert response.status_code == 422
    assert "status" in str(response.json()["error"]["details"])


@pytest.mark.asyncio
async def test_publish_keeps_unlisted_visibility(user_client, db_session, test_user):
    """be-tours-3: publish does not turn an unlisted tour public."""
    tour = await _tour(
        db_session, test_user, status=TourStatus.draft, visibility=TourVisibility.unlisted
    )
    await _scene(db_session, tour)
    response = await user_client.post(f"/api/v1/tours/{tour.id}/publish")
    assert response.status_code == 200, response.text
    assert response.json()["visibility"] == "unlisted"


@pytest.mark.asyncio
async def test_publish_makes_a_private_tour_public(user_client, db_session, test_user):
    tour = await _tour(
        db_session, test_user, status=TourStatus.draft, visibility=TourVisibility.private
    )
    await _scene(db_session, tour)
    response = await user_client.post(f"/api/v1/tours/{tour.id}/publish")
    assert response.status_code == 200, response.text
    assert response.json()["visibility"] == "public"


@pytest.mark.asyncio
async def test_settings_patch_deep_merges_and_null_clears(user_client, db_session, test_user):
    """tours-web-23: a partial settings PATCH keeps sibling keys. null clears a key."""
    tour = await _tour(
        db_session,
        test_user,
        settings={
            "auto_rotate": True,
            "show_navbar": False,
            "branding": {"logo_url": "https://a/b.png"},
        },
    )
    response = await user_client.patch(
        f"/api/v1/tours/{tour.id}", json={"settings": {"auto_rotate": False}}
    )
    assert response.status_code == 200, response.text
    settings = response.json()["settings"]
    assert settings["auto_rotate"] is False
    assert settings["show_navbar"] is False
    assert settings["branding"]["logo_url"] == "https://a/b.png"

    cleared = await user_client.patch(
        f"/api/v1/tours/{tour.id}", json={"settings": {"branding": None}}
    )
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["settings"]["branding"] is None
    assert cleared.json()["settings"]["show_navbar"] is False


@pytest.mark.asyncio
async def test_tour_read_with_scene_returns_200(user_client, db_session, test_user):
    """be-tours-0 regression at the endpoint: a tour with a scene returns 200 and wire key scene_metadata."""
    tour = await _tour(db_session, test_user)
    await _scene(
        db_session, tour, metadata={"initial_view": {"yaw": 0.0, "pitch": 0.0, "zoom": 50}}
    )
    response = await user_client.get(f"/api/v1/tours/{tour.id}")
    assert response.status_code == 200, response.text
    scene = response.json()["scenes"][0]
    assert "scene_metadata" in scene and "metadata" not in scene


@pytest.mark.asyncio
async def test_create_tour_with_status_is_rejected(user_client):
    response = await user_client.post("/api/v1/tours", json={"title": "New", "status": "published"})
    assert response.status_code == 422


# -----------------------------------------------------------------------------
# Scenes (be-tours-6, tours-mobile-5, be-tours-0 PATCH path)
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scene_create_rejects_client_order_index(user_client, db_session, test_user):
    tour = await _tour(
        db_session, test_user, status=TourStatus.draft, visibility=TourVisibility.private
    )
    response = await user_client.post(
        f"/api/v1/tours/{tour.id}/scenes", json={"image_url": _IMG, "order_index": 5}
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_scene_create_assigns_order_index_server_side(user_client, db_session, test_user):
    tour = await _tour(
        db_session, test_user, status=TourStatus.draft, visibility=TourVisibility.private
    )
    await _scene(db_session, tour, order_index=0)
    response = await user_client.post(f"/api/v1/tours/{tour.id}/scenes", json={"image_url": _IMG})
    assert response.status_code == 201, response.text
    assert response.json()["order_index"] == 1


@pytest.mark.asyncio
async def test_scene_metadata_patch_keeps_server_written_keys(user_client, db_session, test_user):
    """be-tours-6: a PATCH that names initial_view keeps exif and is_panorama."""
    tour = await _tour(db_session, test_user)
    scene = await _scene(
        db_session,
        tour,
        metadata={
            "exif": {"Make": "X"},
            "is_panorama": True,
            "initial_view": {"yaw": 0.0, "pitch": 0.0},
        },
    )
    response = await user_client.patch(
        f"/api/v1/scenes/{scene.id}",
        json={"scene_metadata": {"initial_view": {"yaw": 45.0}}},
    )
    assert response.status_code == 200, response.text
    metadata = response.json()["scene_metadata"]
    assert metadata["exif"] == {"Make": "X"}
    assert metadata["is_panorama"] is True
    assert metadata["initial_view"]["yaw"] == 45.0


@pytest.mark.asyncio
async def test_scene_metadata_null_clears(user_client, db_session, test_user):
    tour = await _tour(db_session, test_user)
    scene = await _scene(db_session, tour, metadata={"is_panorama": True})
    response = await user_client.patch(f"/api/v1/scenes/{scene.id}", json={"scene_metadata": None})
    assert response.status_code == 200, response.text
    assert response.json()["scene_metadata"] is None


@pytest.mark.asyncio
async def test_scene_delete_removes_hotspots_that_target_it(user_client, db_session, test_user):
    """tours-mobile-5: a hotspot in another scene that targets the deleted scene is removed."""
    tour = await _tour(
        db_session, test_user, status=TourStatus.draft, visibility=TourVisibility.private
    )
    source = await _scene(db_session, tour, order_index=0)
    target = await _scene(db_session, tour, order_index=1)
    link = Hotspot(
        id=str(uuid.uuid4()),
        scene_id=source.id,
        type="navigation",
        position={"yaw": 0.0, "pitch": 0.0},
        target_scene_id=target.id,
        order_index=0,
    )
    db_session.add(link)
    await db_session.flush()

    response = await user_client.delete(f"/api/v1/scenes/{target.id}")
    assert response.status_code == 204, response.text
    remaining = (
        await db_session.execute(select(func.count(Hotspot.id)).where(Hotspot.id == link.id))
    ).scalar_one()
    assert remaining == 0


@pytest.mark.asyncio
async def test_scene_hotspot_list_is_owner_only(user_client, db_session, test_user_2):
    """The hotspot list checks ownership. Another user's scene is not visible."""
    tour = await _tour(db_session, test_user_2)
    scene = await _scene(db_session, tour)
    response = await user_client.get(f"/api/v1/scenes/{scene.id}/hotspots")
    assert response.status_code in (403, 404)


@pytest.mark.asyncio
async def test_scene_hotspot_list_is_a_cursor_page(user_client, db_session, test_user):
    tour = await _tour(db_session, test_user)
    scene = await _scene(db_session, tour)
    response = await user_client.get(f"/api/v1/scenes/{scene.id}/hotspots")
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) >= {"items", "next_cursor", "has_more", "limit", "total"}


# -----------------------------------------------------------------------------
# Hotspots (tours-web-9, tours-web-8, be-tours-18)
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_hotspot_patch_null_clears_title_and_content(user_client, db_session, test_user):
    """tours-web-9: explicit null clears title and content."""
    tour = await _tour(db_session, test_user)
    scene = await _scene(db_session, tour)
    created = await user_client.post(
        f"/api/v1/scenes/{scene.id}/hotspots",
        json={
            "type": "info",
            "position": {"yaw": 1.0, "pitch": 2.0},
            "title": "Heading",
            "content": {"text": "Some text"},
        },
    )
    assert created.status_code == 201, created.text
    hotspot_id = created.json()["id"]

    patched = await user_client.patch(
        f"/api/v1/hotspots/{hotspot_id}", json={"title": None, "content": None}
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["title"] is None
    assert patched.json()["content"] is None


@pytest.mark.asyncio
async def test_link_hotspot_accepts_mailto(user_client, db_session, test_user):
    """tours-web-8: mailto links are saved (one scheme set, same as the sanitizer)."""
    tour = await _tour(db_session, test_user)
    scene = await _scene(db_session, tour)
    response = await user_client.post(
        f"/api/v1/scenes/{scene.id}/hotspots",
        json={
            "type": "link",
            "position": {"yaw": 0.0, "pitch": 0.0},
            "content": {"url": "mailto:agent@example.com", "label": "Email"},
        },
    )
    assert response.status_code == 201, response.text
    assert response.json()["content"]["url"] == "mailto:agent@example.com"


@pytest.mark.asyncio
async def test_hotspot_create_rejects_alias_content_keys(user_client, db_session, test_user):
    """be-tours-18: input aliases such as link_url are not accepted."""
    tour = await _tour(db_session, test_user)
    scene = await _scene(db_session, tour)
    response = await user_client.post(
        f"/api/v1/scenes/{scene.id}/hotspots",
        json={
            "type": "link",
            "position": {"yaw": 0.0, "pitch": 0.0},
            "content": {"link_url": "https://example.com"},
        },
    )
    assert response.status_code == 422


# -----------------------------------------------------------------------------
# Floor plans (be-tours-1, be-tours-12, tours-web-4)
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_floor_plan_put_null_markers_is_rejected(user_client, db_session, test_user):
    """be-tours-1: markers null is a 422, and the list keeps working."""
    tour = await _tour(db_session, test_user)
    created = await user_client.post(
        f"/api/v1/tours/{tour.id}/floor-plans",
        json={"name": "Ground", "image_url": _IMG, "floor_number": 1},
    )
    assert created.status_code == 201, created.text
    plan_id = created.json()["id"]
    assert created.json()["markers"] == []

    put = await user_client.put(
        f"/api/v1/tours/{tour.id}/floor-plans/{plan_id}", json={"markers": None}
    )
    assert put.status_code == 422
    listed = await user_client.get(f"/api/v1/tours/{tour.id}/floor-plans")
    assert listed.status_code == 200, listed.text
    assert listed.json()["items"][0]["markers"] == []


@pytest.mark.asyncio
async def test_floor_plans_are_in_the_tour_detail_from_the_table(
    user_client, db_session, test_user
):
    """be-tours-12 / tours-web-4: the owner detail reads floor plans from the table."""
    tour = await _tour(db_session, test_user)
    await user_client.post(
        f"/api/v1/tours/{tour.id}/floor-plans",
        json={"name": "First", "image_url": _IMG, "floor_number": 2},
    )
    scene = await _scene(db_session, tour)
    response = await user_client.get(f"/api/v1/tours/{tour.id}")
    assert response.status_code == 200, response.text
    assert [plan["name"] for plan in response.json()["floor_plans"]] == ["First"]
    assert scene.id in [s["id"] for s in response.json()["scenes"]]


# -----------------------------------------------------------------------------
# Analytics (r2-json-blobs-0, be-tours-13, be-user-21)
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_heatmap_is_a_flat_list_with_scene_ids(user_client, db_session, test_user):
    """tours-web-14: heatmap is one flat list. Each point has its scene_id."""
    tour = await _tour(db_session, test_user)
    scene = await _scene(db_session, tour)
    for yaw, pitch in ((10.2, 4.9), (10.4, 5.1), (-80.0, 0.0)):
        db_session.add(
            TourAnalyticsEvent(
                tour_id=tour.id,
                scene_id=scene.id,
                event_type="scene_view",
                event_data={"yaw": yaw, "pitch": pitch},
            )
        )
    await db_session.flush()

    response = await user_client.get(f"/api/v1/tours/{tour.id}/heatmap")
    assert response.status_code == 200, response.text
    points = response.json()["heatmap"]
    assert isinstance(points, list) and len(points) == 2
    assert all(point["scene_id"] == scene.id for point in points)
    top = max(points, key=lambda point: point["count"])
    assert top["count"] == 2 and top["intensity"] == 1.0


@pytest.mark.asyncio
async def test_dashboard_storage_is_the_sum_of_media_sizes(user_client, db_session, test_user):
    """be-tours-13 / be-user-21: storage_used is the sum of media file sizes."""
    for size in (1_000, 2_500):
        db_session.add(
            MediaFile(
                id=str(uuid.uuid4()),
                user_id=test_user.id,
                filename=f"f{size}.jpg",
                file_url="https://res.cloudinary.com/demo/f.jpg",
                file_size=size,
                mime_type="image/jpeg",
                created_at=datetime.now(UTC),
            )
        )
    await db_session.flush()
    response = await user_client.get("/api/v1/dashboard/stats")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["storage_used"] >= 3_500
    assert body["storage_limit"] == 5 * 1024**3


# -----------------------------------------------------------------------------
# Public viewer routes (events, likes, scenes)
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_event_post_returns_204_and_dedupes_per_viewer(guest_client, db_session, test_user):
    """Events return 204. The same viewer's repeat inside the window is not stored twice."""
    tour = await _tour(db_session, test_user)
    scene = await _scene(db_session, tour)
    body = {
        "event_type": "scene_view",
        "scene_id": scene.id,
        "session_id": "sess-1",
        "event_data": {"yaw": 1.0, "pitch": 2.0},
    }
    first = await guest_client.post(f"/api/v1/public/tours/{tour.id}/events", json=body)
    second = await guest_client.post(f"/api/v1/public/tours/{tour.id}/events", json=body)
    assert first.status_code == 204, first.text
    assert second.status_code == 204, second.text
    stored = (
        await db_session.execute(
            select(func.count(TourAnalyticsEvent.id)).where(
                TourAnalyticsEvent.tour_id == tour.id, TourAnalyticsEvent.event_type == "scene_view"
            )
        )
    ).scalar_one()
    assert stored == 1


@pytest.mark.asyncio
async def test_event_rejects_unknown_type_and_like_type(guest_client, db_session, test_user):
    tour = await _tour(db_session, test_user)
    for event_type in ("like", "unknown_event"):
        response = await guest_client.post(
            f"/api/v1/public/tours/{tour.id}/events", json={"event_type": event_type}
        )
        assert response.status_code == 422, event_type


@pytest.mark.asyncio
async def test_like_counts_once_per_viewer_and_unlike_reverts(guest_client, db_session, test_user):
    tour = await _tour(db_session, test_user)
    url = f"/api/v1/public/tours/{tour.id}/like"
    headers = {"x-session-id": "viewer-A"}
    first = await guest_client.post(url, headers=headers)
    second = await guest_client.post(url, headers=headers)
    assert first.status_code == 200 and second.status_code == 200
    assert first.json() == {"like_count": 1}
    assert second.json() == {"like_count": 1}

    # Viewers are client IPs (review round 1). A new session id from the same client
    # does not make a second viewer, so the count stays at 1.
    other = await guest_client.post(url, headers={"x-session-id": "viewer-B"})
    assert other.json() == {"like_count": 1}

    removed = await guest_client.delete(url, headers=headers)
    assert removed.json() == {"like_count": 0}
    rows = (
        await db_session.execute(
            select(func.count(TourLike.tour_id)).where(TourLike.tour_id == tour.id)
        )
    ).scalar_one()
    assert rows == 0


@pytest.mark.asyncio
async def test_public_tour_detail_returns_floor_plans_and_no_settings_copy(
    guest_client, db_session, test_user
):
    """tours-web-4 / branch-drift-33: public viewers read floor plans at the top level only.

    A legacy settings.floor_plans copy in the stored JSON is dropped on read, so the
    viewer cannot pick up a stale plan list from settings.
    """
    tour = await _tour(
        db_session,
        test_user,
        settings={"show_navbar": True, "floor_plans": [{"name": "legacy copy"}]},
    )
    db_session.add(
        FloorPlan(
            id=str(uuid.uuid4()),
            tour_id=tour.id,
            name="Public plan",
            image_url=_IMG,
            floor_number=1,
            markers=[],
        )
    )
    await db_session.flush()
    response = await guest_client.get(f"/api/v1/public/tours/{tour.id}", params={"track": "false"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert [plan["name"] for plan in body["floor_plans"]] == ["Public plan"]
    assert "floor_plans" not in (body.get("settings") or {})


@pytest.mark.asyncio
async def test_public_scenes_list_is_a_cursor_page(guest_client, db_session, test_user):
    tour = await _tour(db_session, test_user)
    await _scene(db_session, tour, order_index=0)
    response = await guest_client.get(f"/api/v1/public/tours/{tour.id}/scenes")
    assert response.status_code == 200, response.text
    assert set(response.json()) >= {"items", "next_cursor", "has_more", "limit", "total"}


# -----------------------------------------------------------------------------
# Capture (tours-web-5, tours-web-6, tours-web-7)
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_capture_session_accepts_web_platform(user_client):
    response = await user_client.post(
        "/api/v1/capture-sessions",
        json={"title": "Web walk", "device_info": {"platform": "web"}},
    )
    assert response.status_code == 201, response.text


@pytest.mark.asyncio
async def test_capture_draft_cannot_jump_to_uploading(user_client):
    """tours-web-6: draft -> uploading is not a legal transition."""
    created = await user_client.post("/api/v1/capture-sessions", json={"title": "Jump"})
    session_id = created.json()["id"]
    response = await user_client.patch(
        f"/api/v1/capture-sessions/{session_id}", json={"status": "uploading"}
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_capture_fail_transition_records_error_message(user_client):
    """tours-web-7: a client can fail a session and record why. The session then stops."""
    created = await user_client.post("/api/v1/capture-sessions", json={"title": "Fail"})
    session_id = created.json()["id"]
    failed = await user_client.patch(
        f"/api/v1/capture-sessions/{session_id}",
        json={"status": "failed", "error_message": "Camera lost"},
    )
    assert failed.status_code == 200, failed.text
    assert failed.json()["status"] == "failed"
    assert failed.json()["error_message"] == "Camera lost"
    again = await user_client.patch(
        f"/api/v1/capture-sessions/{session_id}", json={"status": "capturing"}
    )
    assert again.status_code == 400


@pytest.mark.asyncio
async def test_capture_upload_path_follows_the_state_machine(user_client):
    created = await user_client.post("/api/v1/capture-sessions", json={"title": "Path"})
    session_id = created.json()["id"]
    for next_status in ("capturing", "review", "uploading"):
        response = await user_client.patch(
            f"/api/v1/capture-sessions/{session_id}", json={"status": next_status}
        )
        assert response.status_code == 200, (next_status, response.text)
    assert response.json()["status"] == "uploading"


# -----------------------------------------------------------------------------
# Custom domains (conventions-5)
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_custom_domain_list_is_a_cursor_page(user_client):
    response = await user_client.get("/api/v1/custom-domains")
    assert response.status_code == 200, response.text
    assert set(response.json()) >= {"items", "next_cursor", "has_more", "limit", "total"}
    assert response.json()["total"] is None
