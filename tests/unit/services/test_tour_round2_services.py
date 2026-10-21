"""Service tests for the BE-tours fix round 2 (review items 8, 9, 21).

Rows are written in db_session, which rolls back at the end of each test.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.enums import HotspotType, TourStatus, TourVisibility
from app.models.tours import Tour
from app.schemas.tour import TourGenerationRequest
from app.services.tour.tours import _apply_publish_state
from app.services.tour_ai.background import generate_tour
from app.services.tour_ai.helpers import _ensure_navigation_hotspots

_IMG = "https://res.cloudinary.com/demo/image/upload/room.jpg"


# Review item 8: the publish retry and the first publish share one rule.
def test_publish_state_keeps_an_unlisted_tour_unlisted():
    tour = Tour(
        id="t", user_id=1, title="T", status=TourStatus.draft, visibility=TourVisibility.unlisted
    )
    _apply_publish_state(tour)
    assert tour.status == TourStatus.published
    assert tour.visibility == TourVisibility.unlisted
    assert tour.is_public is False


def test_publish_state_makes_a_private_tour_public():
    tour = Tour(
        id="t", user_id=1, title="T", status=TourStatus.draft, visibility=TourVisibility.private
    )
    _apply_publish_state(tour)
    assert tour.visibility == TourVisibility.public
    assert tour.is_public is True


# Review item 21: AI hotspots get order_index after the scene's last hotspot.
@pytest.mark.asyncio
async def test_ai_navigation_hotspot_order_index_follows_the_last_hotspot():
    existing = SimpleNamespace(order_index=3, type=HotspotType.info, target_scene_id=None)
    scene = SimpleNamespace(id="scene-a", order_index=0, title="A", hotspots=[existing])
    next_scene = SimpleNamespace(id="scene-b", order_index=1, title="B", hotspots=[])
    tour = SimpleNamespace(scenes=[scene, next_scene])
    db = MagicMock()
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()

    created = await _ensure_navigation_hotspots(db, tour)

    assert len(created) == 1
    assert created[0].order_index == 4
    assert created[0].target_scene_id == "scene-b"


# Review item 9: generate_tour sets is_public from visibility; a disagreeing request is_public is ignored.
@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("visibility", "request_is_public", "expected"),
    [
        (TourVisibility.public, False, True),
        (TourVisibility.private, True, False),
        (TourVisibility.unlisted, True, False),
    ],
)
async def test_generate_tour_is_public_follows_visibility(
    db_session, test_user, visibility, request_is_public, expected
):
    data = TourGenerationRequest(
        title="Generated",
        visibility=visibility,
        is_public=request_is_public,
        scenes=[{"image_url": _IMG}],
    )

    def _close(coro):
        coro.close()

    # The worker never runs here: its coroutine is replaced and the task is closed.
    with (
        patch("app.services.tour_ai.background._run_tour_generation", MagicMock()),
        patch("app.services.tour_ai.background._track_background_task", side_effect=_close),
    ):
        _job, tour, _scene_ids = await generate_tour(db_session, test_user.id, data)

    assert tour.visibility == visibility
    assert tour.is_public is expected
    assert tour.status == TourStatus.draft
