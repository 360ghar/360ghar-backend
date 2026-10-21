"""Unit tests for the BE-tours pass B contract fixes. No database.

Each test names the ledger item it guards.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.schemas.tour import (
    DashboardRealtimeStats,
    FloorPlanMarkerIn,
    Hotspot,
    HotspotSuggestionDraft,
    HotspotUpdate,
    SceneInitialView,
    TourBrandingSettings,
    TourSettings,
)

_NOW = datetime(2026, 10, 14, 10, 0, tzinfo=UTC)


def _draft(payload: dict, scene_ids=("s1", "s2"), source: str = "s1") -> HotspotSuggestionDraft:
    return HotspotSuggestionDraft.model_validate(
        payload,
        context={"scene_ids": set(scene_ids), "source_scene_id": source},
    )


# tours-web-19: AI hotspot suggestions are checked when the job completes.
def test_navigation_to_another_scene_in_the_tour_is_kept():
    draft = _draft({"type": "navigation", "yaw": 10, "pitch": 0, "target_scene_id": "s2"})
    assert draft.target_scene_id == "s2"


def test_navigation_to_its_own_scene_is_dropped():
    with pytest.raises(ValidationError):
        _draft({"type": "navigation", "yaw": 10, "pitch": 0, "target_scene_id": "s1"})


def test_navigation_to_a_scene_outside_the_tour_is_dropped():
    with pytest.raises(ValidationError):
        _draft({"type": "navigation", "yaw": 0, "pitch": 0, "target_scene_id": "other-tour"})


def test_info_suggestion_clears_its_target():
    draft = _draft({"type": "info", "yaw": 0, "pitch": 0, "target_scene_id": "s2"})
    assert draft.target_scene_id is None


def test_angles_are_clamped_to_range():
    draft = _draft({"type": "info", "yaw": 200, "pitch": -120})
    assert draft.yaw == 180.0
    assert draft.pitch == -90.0


def test_non_finite_angle_is_dropped():
    with pytest.raises(ValidationError):
        _draft({"type": "info", "yaw": math.nan, "pitch": 0})


def test_unknown_suggestion_type_is_dropped():
    with pytest.raises(ValidationError):
        _draft({"type": "teleport", "yaw": 0, "pitch": 0})


# tours-web-30: branding enums are enforced on write.
def test_branding_rejects_an_unknown_button_style():
    with pytest.raises(ValidationError):
        TourBrandingSettings.model_validate({"button_style": "round"})


def test_branding_rejects_an_unknown_watermark_position():
    with pytest.raises(ValidationError):
        TourSettings.model_validate({"branding": {"watermark_position": "middle"}})


def test_branding_accepts_the_values_the_web_client_sends():
    branding = TourBrandingSettings.model_validate(
        {"button_style": "pill", "watermark_position": "top-left"}
    )
    assert branding.button_style == "pill"
    assert branding.watermark_position == "top-left"


# Floor-plan write bodies reject unknown marker keys.
def test_floor_plan_marker_input_rejects_unknown_keys():
    with pytest.raises(ValidationError):
        FloorPlanMarkerIn.model_validate({"scene_id": "s1", "x": 1, "y": 2, "bogus": True})


# tours-web-31: custom_data is never null on the response; PATCH null is rejected.
def _hotspot_row(**overrides) -> dict:
    row = {
        "id": "h1",
        "scene_id": "s1",
        "type": "info",
        "position": {"yaw": 0, "pitch": 0},
        "icon_size": 32,
        "order_index": 0,
        "is_active": True,
        "created_at": _NOW,
        "updated_at": _NOW,
        "custom_data": None,
    }
    row.update(overrides)
    return row


def test_hotspot_response_reads_null_custom_data_as_empty_object():
    assert Hotspot.model_validate(_hotspot_row()).custom_data == {}


def test_hotspot_patch_rejects_null_custom_data():
    with pytest.raises(ValidationError):
        HotspotUpdate.model_validate({"custom_data": None})


# r2-units-matrix-11: the zoom unit is stated in the schema.
def test_scene_initial_view_zoom_documents_its_unit():
    schema = SceneInitialView.model_json_schema()
    assert "0 (widest) to 100 (closest)" in schema["properties"]["zoom"]["description"]


# be-tours-31: realtime buckets carry a timestamp, not a calendar date.
def test_realtime_buckets_use_a_timestamp_key():
    stats = DashboardRealtimeStats(
        recent_views=[{"timestamp": datetime(2026, 10, 14, 10, 5, tzinfo=UTC), "views": 3}]
    )
    dumped = stats.model_dump(mode="json")
    assert dumped["recent_views"] == [{"timestamp": "2026-10-14T10:05:00Z", "views": 3}]
