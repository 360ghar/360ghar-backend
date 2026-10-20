"""Unit tests for the spatial graph summary (deterministic, no AI, no DB)."""

from __future__ import annotations

from app.services.tour_ai.spatial import build_graph, graph_summary


def _opening(yaw: float, leads: str | None, conf: float = 0.9, label: str = ""):
    return {
        "type": "door",
        "yaw": yaw,
        "pitch": -28.0,
        "leads_to_room_type": leads,
        "leads_to_confidence": conf,
        "visual_context": "",
        "label": label,
    }


def _scene(sid: str, room_type: str, openings=(), hotspots=None):
    return {
        "id": sid,
        "room_type": room_type,
        "title": room_type.replace("_", " ").title(),
        "openings": list(openings),
        "hotspots": list(hotspots or []),
    }


def test_reciprocal_doorways_produce_a_clean_summary():
    scenes = [
        _scene("living_room", "living_room", [_opening(-90, "kitchen")]),
        _scene("kitchen", "kitchen", [_opening(90, "living_room")]),
    ]
    build_graph(scenes)
    summary = graph_summary(scenes)

    assert summary["scene_count"] == 2
    assert summary["link_count"] == 2
    assert summary["one_way_links"] == []
    assert summary["unreachable_scenes"] == []
    assert summary["rooms_without_links"] == []
    assert summary["unmatched_openings"] == []
    assert summary["warnings"] == []


def test_one_way_link_is_reported_when_the_target_has_no_openings():
    scenes = [
        _scene("living_room", "living_room", [_opening(-90, "kitchen")]),
        _scene("kitchen", "kitchen"),
    ]
    build_graph(scenes)
    summary = graph_summary(scenes)

    assert summary["one_way_links"] == ["living_room->kitchen"]
    assert any("one way" in warning for warning in summary["warnings"])


def test_doorway_to_a_missing_room_is_reported_not_invented():
    scenes = [
        _scene("living_room", "living_room", [_opening(-90, "bathroom", label="to bathroom")]),
        _scene("kitchen", "kitchen"),
    ]
    build_graph(scenes)
    summary = graph_summary(scenes)

    assert summary["unmatched_openings"] == [
        {"scene_id": "living_room", "leads_to_room_type": "bathroom", "label": "to bathroom"}
    ]
    assert summary["unlinked_openings"] == []
    assert any("without a scene" in warning for warning in summary["warnings"])


def test_doorway_the_linker_skipped_is_unlinked_not_unmatched():
    """A room exists behind the doorway, so the warning must not claim there is
    no scene for it. This is the shape a sandbox-built plan can have, where the
    graph comes from the agent instead of `build_graph` (whose connectivity
    repair would have linked it anyway)."""
    scenes = [
        _scene(
            "living_room",
            "living_room",
            [_opening(-90, "hallway", label="stairs up")],
            hotspots=[
                {
                    "id": "living_room->kitchen",
                    "type": "navigation",
                    "target_scene_id": "kitchen",
                    "title": "Kitchen",
                    "position": {"yaw": 90.0, "pitch": -28.0},
                }
            ],
        ),
        _scene("kitchen", "kitchen"),
        _scene("hallway", "hallway"),
    ]
    summary = graph_summary(scenes)

    assert summary["unmatched_openings"] == []
    assert summary["unlinked_openings"] == [
        {"scene_id": "living_room", "leads_to_room_type": "hallway", "label": "stairs up"}
    ]
    assert any("could not be matched" in warning for warning in summary["warnings"])
    assert not any("without a scene" in warning for warning in summary["warnings"])


def test_a_second_doorway_to_a_linked_room_is_not_an_unmatched_opening():
    """build_graph keeps one link per target, so the other doorway to the same
    room type must not be reported as a doorway with no room behind it."""
    scenes = [
        _scene(
            "living_room",
            "living_room",
            [_opening(-90, "kitchen", label="door to kitchen"), _opening(90, "kitchen", label="second door")],
        ),
        _scene("kitchen", "kitchen", [_opening(90, "living_room")]),
    ]
    build_graph(scenes)
    summary = graph_summary(scenes)

    assert summary["unmatched_openings"] == []
    assert summary["warnings"] == []


def test_single_room_tour_reports_the_room_without_links():
    scenes = [_scene("living_room", "living_room")]
    build_graph(scenes)
    summary = graph_summary(scenes)

    assert summary["rooms_without_links"] == ["living_room"]
    assert any("no doorway links" in warning for warning in summary["warnings"])


def test_empty_scene_list_summarises_cleanly():
    summary = graph_summary([])
    assert summary["scene_count"] == 0
    assert summary["warnings"] == []
