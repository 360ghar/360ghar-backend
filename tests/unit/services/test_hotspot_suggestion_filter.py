"""AI hotspot suggestions are checked before the job stores them (tours-web-19)."""

from __future__ import annotations

from app.services.tour_ai.hotspot_suggestions import _accepted_suggestions


def test_only_valid_suggestions_are_stored_in_apply_shape():
    raw = [
        {
            "type": "navigation",
            "yaw": 10,
            "pitch": 5,
            "target_scene_id": "s2",
            "suggested_title": "Kitchen",
            "reasoning": "doorway",
            "confidence": 0.8,
        },
        {"type": "navigation", "yaw": 10, "pitch": 5, "target_scene_id": "s1"},
        {"type": "info", "yaw": 400, "pitch": 0, "suggested_title": "View"},
        "not an object",
    ]
    accepted = _accepted_suggestions(raw, "s1", {"s1", "s2"})
    assert len(accepted) == 2
    kitchen, view = accepted
    assert kitchen["position"] == {"yaw": 10.0, "pitch": 5.0}
    assert kitchen["target_scene_id"] == "s2"
    assert kitchen["scene_id"] == "s1"
    assert kitchen["id"]
    assert view["position"]["yaw"] == 180.0
    assert view["target_scene_id"] is None


def test_non_list_result_yields_no_suggestions():
    assert _accepted_suggestions("nope", "s1", {"s1"}) == []
