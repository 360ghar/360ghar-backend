"""
Unit tests for tour Pydantic schemas.
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.models.enums import TourStatus, TourVisibility
from app.schemas.tour import TourWithScenes


class TestTourSettingsWorld3d:
    def test_world_3d_round_trips_on_tour_with_scenes(self):
        now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        result = TourWithScenes.model_validate(
            {
                "id": "tour-1",
                "user_id": 1,
                "title": "Sample Tour",
                "status": TourStatus.published,
                "is_featured": False,
                "visibility": TourVisibility.public,
                "view_count": 0,
                "like_count": 0,
                "share_count": 0,
                "created_at": now,
                "updated_at": now,
                "settings": {
                    "world_3d": {"mesh_url": "https://cdn.example/x.glb"},
                },
                "scenes": [],
            }
        )

        assert result.settings is not None
        assert result.settings.world_3d == {"mesh_url": "https://cdn.example/x.glb"}
