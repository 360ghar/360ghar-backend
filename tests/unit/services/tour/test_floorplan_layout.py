"""Unit tests for the schematic floor-plan layout engine (no DB, no AI, no network)."""

from __future__ import annotations

from app.services.tour.floorplan_layout import (
    CELL_H,
    CELL_W,
    RoomInput,
    build_floor_plan_image,
    build_layout,
    layout_markers,
)


def _room(sid: str, order: int, title: str | None = None, room_type: str | None = None):
    return RoomInput(
        scene_id=sid,
        title=title or sid.replace("_", " ").title(),
        room_type=room_type,
        order_index=order,
    )


def _boxes_by_id(rooms, edges, start=None):
    boxes, width, height = build_layout(rooms, edges, start)
    return {box.room.scene_id: box for box in boxes}, width, height


def test_connected_rooms_land_in_adjacent_cells():
    rooms = [_room("living", 0), _room("kitchen", 1), _room("bedroom", 2)]
    edges = [("living", "kitchen"), ("kitchen", "bedroom")]
    boxes, _, _ = _boxes_by_id(rooms, edges)

    def adjacent(a, b):
        return abs(boxes[a].col - boxes[b].col) + abs(boxes[a].row - boxes[b].row) == 1

    assert adjacent("living", "kitchen")
    assert adjacent("kitchen", "bedroom")


def test_every_room_is_placed_exactly_once():
    rooms = [_room("a", 0), _room("b", 1), _room("c", 2)]
    boxes, _, _ = _boxes_by_id(rooms, [("a", "b")])
    cells = [(box.col, box.row) for box in boxes.values()]
    assert len(boxes) == 3
    assert len(set(cells)) == 3


def test_start_scene_gets_the_origin_cell():
    rooms = [_room("a", 0), _room("b", 1)]
    boxes, _, _ = _boxes_by_id(rooms, [("a", "b")], start="b")
    assert (boxes["b"].col, boxes["b"].row) == (0, 0)


def test_duplicate_and_reversed_edges_change_nothing():
    rooms = [_room("a", 0), _room("b", 1), _room("c", 2)]
    single, _, _ = _boxes_by_id(rooms, [("a", "b"), ("b", "c")])
    noisy, _, _ = _boxes_by_id(rooms, [("a", "b"), ("b", "a"), ("a", "b"), ("b", "c")])
    assert {(sid, b.col, b.row) for sid, b in single.items()} == {
        (sid, b.col, b.row) for sid, b in noisy.items()
    }


def test_edges_to_unknown_scenes_are_ignored():
    rooms = [_room("a", 0), _room("b", 1)]
    boxes, _, _ = _boxes_by_id(rooms, [("a", "ghost"), ("ghost", "b")])
    assert set(boxes) == {"a", "b"}


def test_markers_sit_at_room_centres_in_percent():
    rooms = [_room("a", 0), _room("b", 1)]
    boxes, width, height = build_layout(rooms, [("a", "b")])
    markers = layout_markers(boxes, width, height)

    assert [m["scene_id"] for m in markers] == ["a", "b"]
    for marker, box in zip(markers, boxes, strict=True):
        assert 0 <= marker["x"] <= 100
        assert 0 <= marker["y"] <= 100
        assert marker["x"] == round((box.x + CELL_W / 2) / width * 100, 2)
        assert marker["y"] == round((box.y + CELL_H / 2) / height * 100, 2)
        assert marker["label"]


def test_marker_labels_fall_back_to_room_type_when_title_is_blank():
    rooms = [RoomInput(scene_id="a", title="", room_type="living_room", order_index=0)]
    boxes, width, height = build_layout(rooms, [])
    markers = layout_markers(boxes, width, height)
    assert markers[0]["label"] == "Living Room"


def test_render_produces_a_png_and_is_deterministic():
    rooms = [_room("a", 0, "Living room"), _room("b", 1, "Kitchen", "kitchen")]
    edges = [("a", "b")]
    png_one, markers_one = build_floor_plan_image(rooms, edges, None, "Test Tour")
    png_two, markers_two = build_floor_plan_image(rooms, edges, None, "Test Tour")

    assert png_one.startswith(b"\x89PNG\r\n\x1a\n")
    assert png_one == png_two
    assert markers_one == markers_two
    assert len(markers_one) == 2


def test_rooms_without_links_still_render():
    rooms = [_room("a", 0), _room("b", 1)]
    png, markers = build_floor_plan_image(rooms, [])
    assert png.startswith(b"\x89PNG")
    assert len(markers) == 2
