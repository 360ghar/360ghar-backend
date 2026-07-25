"""
API tests for POST /api/v1/tours/{tour_id}/generate-3d.

The background world3d runner is patched out — these tests cover job
creation, the no-scenes 400, and ownership gating.
"""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

import pytest

from app.models.enums import TourStatus, TourVisibility
from app.models.tours import Scene, Tour


async def _make_tour(db_session, user, *, with_scene: bool = True) -> Tour:
    tour = Tour(
        id=str(uuid.uuid4()),
        user_id=user.id,
        title="World Tour",
        status=TourStatus.draft,
        is_public=False,
        visibility=TourVisibility.private,
    )
    db_session.add(tour)
    if with_scene:
        scene = Scene(
            id=str(uuid.uuid4()),
            tour_id=tour.id,
            image_url="https://cdn.example.com/pano.jpg",
            order_index=0,
        )
        db_session.add(scene)
    await db_session.flush()
    return tour


def _patched_world3d_background():
    """Patch out the background 3D runner (no bg DB session in tests)."""
    return (
        patch(
            "app.services.tour_ai.world3d._track_background_task",
            side_effect=lambda coro: coro.close(),
        ),
        patch(
            "app.services.tour_ai.world3d._run_generate_3d_world", MagicMock(return_value=None)
        ),
    )


class TestGenerate3DEndpoint:
    @pytest.mark.asyncio
    async def test_creates_pending_generate_3d_job(self, user_client, db_session, test_user):
        tour = await _make_tour(db_session, test_user)
        patch_track, patch_run = _patched_world3d_background()

        with patch_track as mock_track, patch_run:
            response = await user_client.post(f"/api/v1/tours/{tour.id}/generate-3d")

        assert response.status_code == 200
        job = response.json()["job"]
        assert job["job_type"] == "generate_3d_world"
        assert job["status"] == "pending"
        assert job["tour_id"] == tour.id
        mock_track.assert_called_once()

    @pytest.mark.asyncio
    async def test_tour_without_scenes_returns_400(self, user_client, db_session, test_user):
        tour = await _make_tour(db_session, test_user, with_scene=False)

        response = await user_client.post(f"/api/v1/tours/{tour.id}/generate-3d")

        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_foreign_tour_returns_403(
        self, user_client, db_session, test_user, test_user_2
    ):
        foreign_tour = await _make_tour(db_session, test_user_2)

        response = await user_client.post(f"/api/v1/tours/{foreign_tour.id}/generate-3d")

        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_missing_tour_returns_404(self, user_client, db_session, test_user):
        response = await user_client.post(f"/api/v1/tours/{uuid.uuid4()}/generate-3d")

        assert response.status_code == 404
