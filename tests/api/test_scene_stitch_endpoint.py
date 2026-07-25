"""
API tests for POST /api/v1/scenes/{scene_id}/stitch.

The background stitch runner is patched out — these tests cover job
creation, ownership gating (404 on foreign/missing scenes), and payload
validation.
"""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

import pytest

from app.models.enums import TourStatus, TourVisibility
from app.models.tours import Scene, Tour

FRAME_URLS = ["https://cdn.example.com/f1.jpg", "https://cdn.example.com/f2.jpg"]


async def _make_scene(db_session, user) -> Scene:
    tour = Tour(
        id=str(uuid.uuid4()),
        user_id=user.id,
        title="Stitch Tour",
        status=TourStatus.draft,
        is_public=False,
        visibility=TourVisibility.private,
    )
    db_session.add(tour)
    scene = Scene(
        id=str(uuid.uuid4()),
        tour_id=tour.id,
        image_url="https://cdn.example.com/pano.jpg",
        order_index=0,
    )
    db_session.add(scene)
    await db_session.flush()
    return scene


def _patched_stitch_background():
    """Patch out the background stitch runner (no bg DB session in tests)."""
    return (
        patch(
            "app.services.tour_ai.stitch._track_background_task",
            side_effect=lambda coro: coro.close(),
        ),
        patch("app.services.tour_ai.stitch._run_scene_stitch", MagicMock(return_value=None)),
    )


class TestSceneStitchEndpoint:
    @pytest.mark.asyncio
    async def test_creates_pending_stitch_job(self, user_client, db_session, test_user):
        scene = await _make_scene(db_session, test_user)
        patch_track, patch_run = _patched_stitch_background()

        with patch_track as mock_track, patch_run:
            response = await user_client.post(
                f"/api/v1/scenes/{scene.id}/stitch", json={"frame_urls": FRAME_URLS}
            )

        assert response.status_code == 200
        job = response.json()["job"]
        assert job["job_type"] == "panorama_stitch"
        assert job["status"] == "pending"
        assert job["scene_id"] == scene.id
        assert job["tour_id"] == scene.tour_id
        mock_track.assert_called_once()

    @pytest.mark.asyncio
    async def test_foreign_scene_returns_404(
        self, user_client, db_session, test_user, test_user_2
    ):
        foreign_scene = await _make_scene(db_session, test_user_2)

        response = await user_client.post(
            f"/api/v1/scenes/{foreign_scene.id}/stitch", json={"frame_urls": FRAME_URLS}
        )

        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_missing_scene_returns_404(self, user_client, db_session, test_user):
        response = await user_client.post(
            f"/api/v1/scenes/{uuid.uuid4()}/stitch", json={"frame_urls": FRAME_URLS}
        )

        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_rejects_fewer_than_two_frames(self, user_client, db_session, test_user):
        scene = await _make_scene(db_session, test_user)

        response = await user_client.post(
            f"/api/v1/scenes/{scene.id}/stitch",
            json={"frame_urls": ["https://cdn.example.com/f1.jpg"]},
        )

        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_rejects_more_than_32_frames(self, user_client, db_session, test_user):
        scene = await _make_scene(db_session, test_user)
        urls = [f"https://cdn.example.com/f{i}.jpg" for i in range(33)]

        response = await user_client.post(
            f"/api/v1/scenes/{scene.id}/stitch", json={"frame_urls": urls}
        )

        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_rejects_non_http_urls(self, user_client, db_session, test_user):
        scene = await _make_scene(db_session, test_user)

        response = await user_client.post(
            f"/api/v1/scenes/{scene.id}/stitch",
            json={"frame_urls": ["ftp://example.com/f1.jpg", "https://cdn.example.com/f2.jpg"]},
        )

        assert response.status_code == 422
