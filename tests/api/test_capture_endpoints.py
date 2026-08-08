"""
API tests for guided capture session endpoints (Phase 0).
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_create_capture_session(user_client: AsyncClient):
    response = await user_client.post(
        "/api/v1/capture-sessions",
        json={
            "title": "2BHK Walkthrough",
            "description": "Phase 0 smoke test",
            "plan": {
                "template": "2bhk",
                "rooms": [
                    {
                        "id": "room-living",
                        "label": "Living Room",
                        "size": "medium",
                        "order_index": 0,
                        "waypoints": [
                            {
                                "id": "wp-0",
                                "index": 0,
                                "label": "Center",
                                "kind": "center",
                            }
                        ],
                    }
                ],
            },
            "device_info": {
                "platform": "ios",
                "model": "iPhone15,2",
                "app_version": "0.1.0",
            },
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["title"] == "2BHK Walkthrough"
    assert body["status"] == "draft"
    assert body["progress"] == 0
    assert body["plan"]["template"] == "2bhk"
    assert body["frame_count"] == 0
    assert body["id"]


@pytest.mark.asyncio
async def test_capture_session_requires_auth(guest_client: AsyncClient):
    response = await guest_client.post(
        "/api/v1/capture-sessions",
        json={"title": "Nope"},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_list_and_get_capture_session(user_client: AsyncClient):
    create = await user_client.post(
        "/api/v1/capture-sessions",
        json={"title": "List me"},
    )
    assert create.status_code == 201
    session_id = create.json()["id"]

    listed = await user_client.get("/api/v1/capture-sessions")
    assert listed.status_code == 200
    payload = listed.json()
    assert payload["total"] >= 1
    assert any(item["id"] == session_id for item in payload["items"])

    detail = await user_client.get(f"/api/v1/capture-sessions/{session_id}")
    assert detail.status_code == 200
    assert detail.json()["id"] == session_id
    assert detail.json()["frames"] == []


@pytest.mark.asyncio
async def test_update_plan_and_register_frame(user_client: AsyncClient):
    create = await user_client.post(
        "/api/v1/capture-sessions",
        json={"title": "Frame session"},
    )
    session_id = create.json()["id"]

    patched = await user_client.patch(
        f"/api/v1/capture-sessions/{session_id}",
        json={
            "status": "capturing",
            "progress": 10,
            "plan": {
                "template": "custom",
                "rooms": [
                    {
                        "id": "r1",
                        "label": "Kitchen",
                        "size": "small",
                        "order_index": 0,
                        "waypoints": [{"id": "w1", "index": 0, "kind": "center"}],
                    }
                ],
            },
        },
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["status"] == "capturing"
    assert patched.json()["plan"]["rooms"][0]["label"] == "Kitchen"

    frame = await user_client.post(
        f"/api/v1/capture-sessions/{session_id}/frames",
        json={
            "room_id": "r1",
            "room_label": "Kitchen",
            "waypoint_id": "w1",
            "waypoint_index": 0,
            "frame_index": 0,
            "image_url": "https://cdn.example.com/captures/frame0.jpg",
            "metadata": {
                "capture_mode": "multi_yaw",
                "pose": {
                    "yaw_deg": 0.0,
                    "pitch_deg": -1.2,
                    "tracking_backend": "imu_pdr",
                    "tracking_quality": "good",
                },
                "quality": {"blur_score": 0.9, "exposure_ok": True},
            },
        },
    )
    assert frame.status_code == 201, frame.text
    body = frame.json()
    assert body["image_url"].endswith("frame0.jpg")
    assert body["room_id"] == "r1"
    assert body["metadata"]["pose"]["yaw_deg"] == 0.0

    status_resp = await user_client.get(f"/api/v1/capture-sessions/{session_id}/status")
    assert status_resp.status_code == 200
    assert status_resp.json()["frame_count"] == 1
    assert status_resp.json()["status"] == "capturing"


@pytest.mark.asyncio
async def test_complete_and_cancel_session(user_client: AsyncClient):
    create = await user_client.post(
        "/api/v1/capture-sessions",
        json={"title": "Complete me"},
    )
    session_id = create.json()["id"]

    # complete with no frames should fail
    bad = await user_client.post(f"/api/v1/capture-sessions/{session_id}/complete")
    assert bad.status_code == 400

    await user_client.post(
        f"/api/v1/capture-sessions/{session_id}/frames",
        json={
            "room_id": "r1",
            "waypoint_id": "w1",
            "image_url": "https://cdn.example.com/a.jpg",
        },
    )

    done = await user_client.post(f"/api/v1/capture-sessions/{session_id}/complete")
    assert done.status_code == 200, done.text
    assert done.json()["status"] == "ready"
    assert done.json()["progress"] == 100

    # cancel another session
    create2 = await user_client.post(
        "/api/v1/capture-sessions",
        json={"title": "Cancel me"},
    )
    sid2 = create2.json()["id"]
    cancelled = await user_client.post(f"/api/v1/capture-sessions/{sid2}/cancel")
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"


@pytest.mark.asyncio
async def test_frame_requires_url_or_media_id(user_client: AsyncClient):
    create = await user_client.post(
        "/api/v1/capture-sessions",
        json={"title": "Missing media"},
    )
    session_id = create.json()["id"]
    response = await user_client.post(
        f"/api/v1/capture-sessions/{session_id}/frames",
        json={
            "room_id": "r1",
            "waypoint_id": "w1",
        },
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_frame_rejects_unknown_or_foreign_media_file_id(user_client: AsyncClient):
    """A frame must reference a MediaFile owned by this user (complete upload)."""
    create = await user_client.post(
        "/api/v1/capture-sessions",
        json={"title": "Bad media id"},
    )
    session_id = create.json()["id"]

    response = await user_client.post(
        f"/api/v1/capture-sessions/{session_id}/frames",
        json={
            "room_id": "r1",
            "waypoint_id": "w1",
            "media_file_id": "00000000-0000-0000-0000-000000000000",
        },
    )
    assert response.status_code == 400
    assert "media_file_id" in response.json()["error"]["message"]


@pytest.mark.asyncio
async def test_patch_cannot_jump_to_server_controlled_states(user_client: AsyncClient):
    """Clients may not PATCH their way to ready / processing / failed / cancelled."""
    create = await user_client.post(
        "/api/v1/capture-sessions",
        json={"title": "No jumping"},
    )
    session_id = create.json()["id"]

    for status in ("ready", "processing", "failed", "cancelled"):
        response = await user_client.patch(
            f"/api/v1/capture-sessions/{session_id}",
            json={"status": status},
        )
        assert response.status_code == 400, status
        assert "not allowed via PATCH" in response.json()["error"]["message"]

    # Forward transitions stay allowed.
    ok = await user_client.patch(
        f"/api/v1/capture-sessions/{session_id}",
        json={"status": "capturing"},
    )
    assert ok.status_code == 200

    # Skipping a step is still rejected.
    skip = await user_client.patch(
        f"/api/v1/capture-sessions/{session_id}",
        json={"status": "uploading"},
    )
    assert skip.status_code == 400
