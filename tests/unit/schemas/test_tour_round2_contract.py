"""Schema tests for the BE-tours fix round 2 (review items 1, 2, 13).

Legacy stored JSON must not fail a whole response. A stored value that fails its
model is dropped or nulled, with a log line. No database.
"""

from __future__ import annotations

from datetime import UTC, datetime

from app.models.enums import TourStatus, TourVisibility
from app.schemas.tour import (
    AIJobStatusResponse,
    FloorPlanResponse,
    Hotspot,
    HotspotPosition,
    PublicScene,
    PublicTourWithScenes,
    TourGenerationResult,
)

_NOW = datetime(2026, 10, 14, 10, 0, tzinfo=UTC)


def _tour_dict() -> dict:
    return {
        "id": "t1",
        "user_id": 1,
        "title": "Flat",
        "status": TourStatus.draft,
        "is_public": False,
        "visibility": TourVisibility.private,
        "is_featured": False,
        "view_count": 0,
        "like_count": 0,
        "share_count": 0,
        "created_at": _NOW,
        "updated_at": _NOW,
    }


def _plan(**overrides) -> dict:
    plan = {
        "id": "fp-1",
        "tour_id": "t1",
        "name": "Ground",
        "image_url": "https://res.cloudinary.com/demo/image/upload/plan.png",
        "floor_number": 1,
        "markers": [],
        "created_at": _NOW,
        "updated_at": _NOW,
    }
    plan.update(overrides)
    return plan


def _hotspot(**overrides) -> dict:
    row = {
        "id": "h1",
        "scene_id": "s1",
        "type": "info",
        "position": {"yaw": 10.0, "pitch": 5.0},
        "icon_size": 32,
        "custom_data": {},
        "order_index": 0,
        "is_active": True,
        "content": None,
        "created_at": _NOW,
        "updated_at": _NOW,
    }
    row.update(overrides)
    return row


# Review item 1: a legacy floor-plan marker that FloorPlanMarker rejects is dropped.
def test_floor_plan_drops_a_marker_without_scene_id_and_keeps_valid_ones():
    plan = FloorPlanResponse.model_validate(
        _plan(
            markers=[
                {"x": 10, "y": 20},
                {"scene_id": "s1", "x": 10, "y": 20, "label": "Kitchen"},
                {"scene_id": "s2", "x": 150, "y": 5},
            ]
        )
    )
    assert [m.scene_id for m in plan.markers] == ["s1"]
    assert plan.markers[0].label == "Kitchen"


def test_floor_plan_null_or_non_list_markers_read_as_empty():
    assert FloorPlanResponse.model_validate(_plan(markers=None)).markers == []
    assert FloorPlanResponse.model_validate(_plan(markers={"x": 1})).markers == []


# Review item 1: a legacy hotspot position is read leniently.
def test_hotspot_position_with_an_extra_key_keeps_the_angles():
    hotspot = Hotspot.model_validate(_hotspot(position={"yaw": 10, "pitch": 5, "legacy": True}))
    assert hotspot.position == HotspotPosition(yaw=10, pitch=5)


def test_hotspot_position_without_pitch_reads_as_null_and_the_hotspot_still_loads():
    hotspot = Hotspot.model_validate(_hotspot(position={"yaw": 10}))
    assert hotspot.position is None
    assert hotspot.id == "h1"


def test_hotspot_valid_position_is_unchanged():
    hotspot = Hotspot.model_validate(_hotspot())
    assert hotspot.position == HotspotPosition(yaw=10, pitch=5)


# Review item 2: the AI job result is validated against its job type on read.
def _job(job_type: str) -> dict:
    return {
        "id": "job-1",
        "job_type": job_type,
        "status": "completed",
        "progress": 100,
        "created_at": _NOW,
        "updated_at": _NOW,
    }


def test_ai_status_keeps_a_valid_generate_tour_result_typed():
    result = {
        "tour_id": "t1",
        "tour": _tour_dict(),
        "scenes": [],
        "generated": [{"scene_id": "s1"}],
        "created_hotspots": [],
    }
    response = AIJobStatusResponse.model_validate({"job": _job("generate_tour"), "result": result})
    assert isinstance(response.result, TourGenerationResult)
    assert response.result.tour.id == "t1"


def test_ai_status_nulls_a_legacy_result_that_fails_its_job_type():
    # Legacy row: the old generate_tour result had no tour key.
    response = AIJobStatusResponse.model_validate(
        {"job": _job("generate_tour"), "result": {"generated": {"scene_id": "s1"}}}
    )
    assert response.result is None
    assert response.job.id == "job-1"


def test_ai_status_nulls_a_result_for_an_unknown_job_type():
    response = AIJobStatusResponse.model_validate(
        {"job": _job("scene_analysis"), "result": {"analysis": []}}
    )
    assert response.job.job_type is None
    assert response.result is None


def test_ai_status_openapi_result_lists_the_per_type_models():
    schema = AIJobStatusResponse.model_json_schema()
    refs = {option.get("$ref", "") for option in schema["properties"]["result"]["anyOf"]}
    assert "#/$defs/TourGenerationResult" in refs
    assert "#/$defs/StitchResult" in refs


# Review item 13: the public scene has no processing_error and no EXIF.
def test_public_scene_omits_processing_error_and_exif():
    scene = PublicScene.model_validate(
        {
            "id": "s1",
            "tour_id": "t1",
            "image_url": "https://res.cloudinary.com/demo/image/upload/room.jpg",
            "order_index": 0,
            "is_processed": False,
            "created_at": _NOW,
            "updated_at": _NOW,
            "processing_error": "Traceback: secret path /srv/app",
            "scene_metadata": {
                "exif": {"camera": {"make": "Apple"}, "gps": {"latitude": 1.0}},
                "room_type": "kitchen",
                "caption": "Bright",
            },
        }
    )
    dumped = scene.model_dump()
    assert "processing_error" not in dumped
    assert "exif" not in dumped["scene_metadata"]
    assert dumped["scene_metadata"]["room_type"] == "kitchen"


def test_public_tour_scenes_use_the_public_scene_shape():
    tour = PublicTourWithScenes.model_validate({**_tour_dict(), "scenes": [], "floor_plans": []})
    assert "user_id" not in tour.model_dump()
    assert tour.main_scene_id is None
