"""Schema tests for the BE-tours fix round 1 (review items 1, 5, 11, 12, 13, 16, 17, 19)."""

from __future__ import annotations

import datetime
import json

import pytest
from pydantic import ValidationError

from app.models.enums import AIJobType, TourEventType, TourStatus, TourVisibility
from app.schemas.capture import CaptureFrameMetadata, CaptureSessionCreate
from app.schemas.tour import (
    DailyView,
    PublicTourWithScenes,
    TourEventPayload,
    TourWithScenes,
    ai_hotspot_position,
    merge_ai_scene_metadata,
    validate_ai_result,
)

_NOW = "2026-10-14T10:00:00+00:00"


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
        "scene_count": 1,
    }


# Review item 1 (blocker): the worker writes generated as a list of per-scene results.
def test_generate_tour_result_accepts_the_worker_list_shape():
    worker_result = {
        "tour_id": "t1",
        "tour": _tour_dict(),
        "generated": [
            {
                "scene_id": "s1",
                "title": "Kitchen",
                "description": "Bright kitchen",
                "room_type": "kitchen",
            }
        ],
        "created_hotspots": ["h1"],
        "scenes": [{"id": "s1", "image_url": "https://cdn.example.com/a.jpg", "hotspot_count": 1}],
    }
    stored = validate_ai_result(AIJobType.generate_tour.value, worker_result)
    assert stored["generated"][0]["scene_id"] == "s1"
    assert stored["created_hotspots"] == ["h1"]
    assert stored["tour"]["status"] == "draft"


def test_generate_tour_result_with_an_empty_generated_list_is_valid():
    stored = validate_ai_result(
        AIJobType.generate_tour.value,
        {"tour_id": "t1", "tour": _tour_dict(), "generated": [], "scenes": []},
    )
    assert stored["generated"] == []


# Review item 16 (a): view is counted by GET /public/tours/{id}, not by the events route.
def test_events_route_refuses_the_view_event_type():
    with pytest.raises(ValidationError):
        TourEventPayload(event_type=TourEventType.view)


def test_events_route_still_accepts_hotspot_click():
    payload = TourEventPayload(event_type=TourEventType.hotspot_click, hotspot_id="h1")
    assert payload.event_type == TourEventType.hotspot_click


# Review item 19: the public tour shape has no owner id.
def test_public_tour_shape_has_no_user_id():
    assert "user_id" not in PublicTourWithScenes.model_fields
    assert "user_id" in TourWithScenes.model_fields


def test_public_tour_json_has_no_user_id():
    tour = PublicTourWithScenes.model_validate(
        {**_tour_dict(), "user_id": 7, "scenes": [], "floor_plans": []}
    )
    assert "user_id" not in json.loads(tour.model_dump_json())


# Review item 13: DailyView.date is a calendar date and keeps the YYYY-MM-DD wire form.
def test_daily_view_date_is_a_date_with_the_same_wire_form():
    row = DailyView(date="2026-10-14", views=3)
    assert row.date == datetime.date(2026, 10, 14)
    assert json.loads(row.model_dump_json()) == {"date": "2026-10-14", "views": 3}


def test_daily_view_rejects_a_datetime_string():
    with pytest.raises(ValidationError):
        DailyView(date="2026-10-14T10:00:00Z", views=1)


# Review item 17: AI hotspot positions are clamped to the HotspotPosition ranges.
def test_ai_hotspot_position_clamps_angles():
    assert ai_hotspot_position(500, -200) == {"yaw": 180.0, "pitch": -90.0, "radius": None}


def test_ai_hotspot_position_maps_non_numbers_to_zero():
    assert ai_hotspot_position(None, "north") == {"yaw": 0.0, "pitch": 0.0, "radius": None}
    assert ai_hotspot_position(float("nan"), 10) == {"yaw": 0.0, "pitch": 10.0, "radius": None}


# Review item 11: AI scene metadata is validated and undeclared keys are dropped.
def test_ai_scene_metadata_drops_undeclared_keys():
    stored = merge_ai_scene_metadata(
        {"exif": {"make": "x"}},
        {"room_type": "kitchen", "caption": "Bright", "made_up_key": 1},
    )
    assert stored == {"exif": {"make": "x"}, "room_type": "kitchen", "caption": "Bright"}


def test_ai_scene_metadata_keeps_valid_keys_when_one_value_is_invalid():
    stored = merge_ai_scene_metadata(
        None,
        {"room_type": "kitchen", "initial_view": {"yaw": 370, "pitch": 0, "zoom": 50}},
    )
    assert stored == {"room_type": "kitchen"}


def test_ai_scene_metadata_keeps_stored_value_when_stored_json_is_invalid():
    stored = merge_ai_scene_metadata({"is_panorama": "not-a-bool-but-legacy"}, {})
    assert stored == {"is_panorama": "not-a-bool-but-legacy"}


# Review item 12: nested capture write models reject unknown keys. The escape hatch stays.
def test_capture_plan_nested_unknown_key_is_rejected():
    with pytest.raises(ValidationError):
        CaptureSessionCreate(
            title="Flat",
            plan={"template": "1bhk", "rooms": [{"id": "r1", "label": "Hall", "bogus": 1}]},
        )


def test_capture_device_info_unknown_key_is_rejected():
    with pytest.raises(ValidationError):
        CaptureSessionCreate(title="Flat", device_info={"platform": "ios", "bogus": True})


def test_capture_frame_metadata_extra_dict_is_still_accepted():
    meta = CaptureFrameMetadata(extra={"anything": {"goes": 1}})
    assert meta.extra == {"anything": {"goes": 1}}
