"""
Schematic floor-plan generation from an analyzed 360° tour.

The spatial pipeline leaves two usable facts on a tour: each scene's room type
(``scene_metadata.room_type``) and which rooms its navigation hotspots connect.
This module turns those facts into an editable floor plan: a deterministic grid
layout of labelled rooms with doorway openings, rendered to PNG, plus marker
positions for the floor-plan row.

No AI call happens here — the analysis already ran and its result is stored.
The output is explicitly a schematic ("AI estimated layout"), not a measured
drawing; nothing in it claims survey accuracy.
"""

from __future__ import annotations

import io
import math
from collections import deque
from dataclasses import dataclass
from typing import Any

from PIL import Image, ImageDraw, ImageFont

# Geometry (pixels). Rooms in adjacent grid cells share a wall, like a plan.
CELL_W = 236
CELL_H = 188
MARGIN = 56
HEADER_H = 84
FOOTER_H = 52
DOOR_GAP_PX = 48

# Palette.
BG = "#F4F5F7"
ROOM_FILL = "#FFFFFF"
ROOM_BORDER = "#23272E"
TEXT_MAIN = "#1C1F24"
TEXT_DIM = "#6B7280"
CONNECTOR = "#9CA3AF"
DASH_LEN = 9
DASH_GAP = 7

# Deterministic neighbour preference when growing the grid: right, down, left, up.
_NEIGHBOUR_OFFSETS: tuple[tuple[int, int], ...] = ((1, 0), (0, 1), (-1, 0), (0, -1))


@dataclass(frozen=True)
class RoomInput:
    """One scene as layout input. Plain data — the caller maps ORM rows onto it."""

    scene_id: str
    title: str
    room_type: str | None
    order_index: int


@dataclass
class RoomBox:
    """A placed room. x/y is the top-left pixel of the rectangle."""

    room: RoomInput
    col: int
    row: int
    x: int
    y: int

    @property
    def w(self) -> int:
        return CELL_W

    @property
    def h(self) -> int:
        return CELL_H

    @property
    def cx(self) -> float:
        return self.x + self.w / 2

    @property
    def cy(self) -> float:
        return self.y + self.h / 2


def _component_order(
    rooms: list[RoomInput], adjacency: dict[str, list[str]], start_scene_id: str | None
) -> list[str]:
    """Visit order for placement: start scene first, then remaining components."""
    order = {r.scene_id for r in rooms}
    by_index = {r.scene_id: r.order_index for r in rooms}
    starts: list[str] = []
    if start_scene_id in order:
        starts.append(start_scene_id)
    starts.extend(sorted(by_index, key=lambda sid: (by_index[sid], sid)))
    return starts


def place_rooms(
    rooms: list[RoomInput],
    adjacency: dict[str, list[str]],
    start_scene_id: str | None = None,
) -> dict[str, tuple[int, int]]:
    """Assign every room a grid cell. Connected rooms land in adjacent cells.

    Deterministic BFS: from the start scene (or the first scene by order) each
    unplaced neighbour takes the first free neighbouring cell. Rooms in
    disconnected components start from the first free cell in row-major order,
    so no scene is ever dropped from the plan.
    """
    placement: dict[str, tuple[int, int]] = {}
    occupied: set[tuple[int, int]] = set()

    size = len(rooms) + 2  # more cells than rooms can ever occupy

    def free_cell() -> tuple[int, int]:
        for row in range(size):
            for col in range(size):
                if (col, row) not in occupied:
                    return (col, row)
        raise RuntimeError("floorplan layout: no free grid cell")

    def place(root: str) -> None:
        # A new component's root goes to the first free cell; the main
        # component's start scene goes to (0, 0) because nothing is occupied.
        cell = (0, 0) if not occupied else free_cell()
        placement[root] = cell
        occupied.add(cell)
        queue = deque([root])
        while queue:
            current = queue.popleft()
            for neighbour in adjacency.get(current, []):
                if neighbour in placement:
                    continue
                for dc, dr in _NEIGHBOUR_OFFSETS:
                    cell = (placement[current][0] + dc, placement[current][1] + dr)
                    if cell not in occupied:
                        break
                else:
                    cell = free_cell()
                placement[neighbour] = cell
                occupied.add(cell)
                queue.append(neighbour)

    for root in _component_order(rooms, adjacency, start_scene_id):
        if root not in placement:
            place(root)
    return placement


def build_layout(
    rooms: list[RoomInput],
    edges: list[tuple[str, str]],
    start_scene_id: str | None = None,
) -> tuple[list[RoomBox], int, int]:
    """Place rooms and derive canvas size. Returns (boxes, width, height)."""
    room_ids = {r.scene_id for r in rooms}
    adjacency: dict[str, list[str]] = {r.scene_id: [] for r in rooms}
    by_index = {r.scene_id: r.order_index for r in rooms}
    seen_edges: set[frozenset[str]] = set()
    for a, b in edges:
        if a not in room_ids or b not in room_ids or a == b:
            continue
        key = frozenset((a, b))
        if key in seen_edges:
            continue
        seen_edges.add(key)
        adjacency[a].append(b)
        adjacency[b].append(a)
    for sid in adjacency:
        adjacency[sid].sort(key=lambda other: (by_index[other], other))

    placement = place_rooms(rooms, adjacency, start_scene_id)
    min_col = min(col for col, _ in placement.values())
    min_row = min(row for _, row in placement.values())

    boxes = [
        RoomBox(
            room=room,
            col=placement[room.scene_id][0],
            row=placement[room.scene_id][1],
            x=MARGIN + (placement[room.scene_id][0] - min_col) * CELL_W,
            y=HEADER_H + MARGIN + (placement[room.scene_id][1] - min_row) * CELL_H,
        )
        for room in rooms
    ]
    cols = max(b.col for b in boxes) - min_col
    rows = max(b.row for b in boxes) - min_row
    width = MARGIN * 2 + (cols + 1) * CELL_W
    height = HEADER_H + MARGIN * 2 + (rows + 1) * CELL_H + FOOTER_H
    return boxes, width, height


def layout_markers(boxes: list[RoomBox], width: int, height: int) -> list[dict[str, Any]]:
    """Marker rows (percent coordinates) for one marker at each room's centre."""
    markers: list[dict[str, Any]] = []
    for box in sorted(boxes, key=lambda b: b.room.order_index):
        label = box.room.title.strip() or (box.room.room_type or "Room").replace("_", " ").title()
        markers.append(
            {
                "scene_id": box.room.scene_id,
                "x": round(min(100.0, max(0.0, box.cx / width * 100)), 2),
                "y": round(min(100.0, max(0.0, box.cy / height * 100)), 2),
                "label": label[:255],
            }
        )
    return markers


def _wrap_two_lines(
    text: str, font: ImageFont.FreeTypeFont | ImageFont.ImageFont, max_width: float
) -> list[str]:
    """Split a label into at most two lines that fit max_width."""
    words = text.split()
    if not words:
        return [""]
    lines: list[str] = [words[0]]
    for word in words[1:]:
        candidate = f"{lines[-1]} {word}"
        if font.getlength(candidate) <= max_width or len(lines) == 2:
            lines[-1] = candidate
        else:
            lines.append(word)
    if len(lines) == 2 and font.getlength(lines[1]) > max_width:
        while lines[1] and font.getlength(lines[1] + "…") > max_width:
            lines[1] = lines[1][:-1]
        lines[1] += "…"
    return lines


def _dashed_line(
    draw: ImageDraw.ImageDraw,
    start: tuple[float, float],
    end: tuple[float, float],
    fill: str,
    width: int = 2,
) -> None:
    length = math.hypot(end[0] - start[0], end[1] - start[1])
    if length <= 0:
        return
    step = DASH_LEN + DASH_GAP
    ux, uy = (end[0] - start[0]) / length, (end[1] - start[1]) / length
    position = 0.0
    while position < length:
        segment_end = min(position + DASH_LEN, length)
        draw.line(
            [
                (start[0] + ux * position, start[1] + uy * position),
                (start[0] + ux * segment_end, start[1] + uy * segment_end),
            ],
            fill=fill,
            width=width,
        )
        position += step


def _door_openings(box: RoomBox, other: RoomBox) -> list[tuple[float, float, float, float]]:
    """The white gap rectangles that turn a shared wall into a doorway."""
    if other.col == box.col + 1:  # door on box's right wall
        x = box.x + box.w
        return [(x - 3, box.cy - DOOR_GAP_PX / 2, x + 3, box.cy + DOOR_GAP_PX / 2)]
    if other.col == box.col - 1:  # left wall
        x = box.x
        return [(x - 3, box.cy - DOOR_GAP_PX / 2, x + 3, box.cy + DOOR_GAP_PX / 2)]
    if other.row == box.row + 1:  # bottom wall
        y = box.y + box.h
        return [(box.cx - DOOR_GAP_PX / 2, y - 3, box.cx + DOOR_GAP_PX / 2, y + 3)]
    if other.row == box.row - 1:  # top wall
        y = box.y
        return [(box.cx - DOOR_GAP_PX / 2, y - 3, box.cx + DOOR_GAP_PX / 2, y + 3)]
    return []


def render_layout_png(
    boxes: list[RoomBox],
    edges: list[tuple[str, str]],
    width: int,
    height: int,
    heading: str | None = None,
) -> bytes:
    """Render the placed layout to PNG bytes."""
    image = Image.new("RGB", (width, height), BG)
    draw = ImageDraw.Draw(image)
    by_id = {box.room.scene_id: box for box in boxes}

    title_font = ImageFont.load_default(size=17)
    label_font = ImageFont.load_default(size=13)
    heading_font = ImageFont.load_default(size=21)
    footer_font = ImageFont.load_default(size=13)

    # Connectors first so the room rectangles cover their middles. Only the
    # stretch between two boxes stays visible.
    normalised: set[frozenset[str]] = set()
    for a, b in edges:
        if a not in by_id or b not in by_id or a == b:
            continue
        key = frozenset((a, b))
        if key in normalised:
            continue
        normalised.add(key)
        box_a, box_b = by_id[a], by_id[b]
        adjacent = abs(box_a.col - box_b.col) + abs(box_a.row - box_b.row) == 1
        if not adjacent:
            _dashed_line(draw, (box_a.cx, box_a.cy), (box_b.cx, box_b.cy), CONNECTOR)

    for box in boxes:
        draw.rectangle(
            [box.x, box.y, box.x + box.w, box.y + box.h],
            fill=ROOM_FILL,
            outline=ROOM_BORDER,
            width=3,
        )

    # Door openings on shared walls.
    for a, b in edges:
        if a not in by_id or b not in by_id:
            continue
        box_a, box_b = by_id[a], by_id[b]
        for gap in _door_openings(box_a, box_b) or _door_openings(box_b, box_a):
            draw.rectangle(gap, fill=BG)

    # Door jamb ticks for the same openings.
    for a, b in edges:
        if a not in by_id or b not in by_id:
            continue
        box_a, box_b = by_id[a], by_id[b]
        gaps = _door_openings(box_a, box_b) or _door_openings(box_b, box_a)
        for x1, y1, x2, y2 in gaps:
            if (y2 - y1) > (x2 - x1):
                # Door in a vertical wall: jambs are short horizontal ticks.
                draw.line([(x1 - 10, y1), (x2 + 10, y1)], fill=ROOM_BORDER, width=2)
                draw.line([(x1 - 10, y2), (x2 + 10, y2)], fill=ROOM_BORDER, width=2)
            else:
                # Door in a horizontal wall: jambs are short vertical ticks.
                draw.line([(x1, y1 - 10), (x1, y2 + 10)], fill=ROOM_BORDER, width=2)
                draw.line([(x2, y1 - 10), (x2, y2 + 10)], fill=ROOM_BORDER, width=2)

    # Room labels.
    for box in boxes:
        label = box.room.title.strip() or (box.room.room_type or "Room")
        lines = _wrap_two_lines(label.replace("_", " "), title_font, box.w - 28)
        line_height = 21
        start_y = box.cy - (len(lines) * line_height) / 2 - 6
        for i, line in enumerate(lines):
            draw.text(
                (box.cx, start_y + i * line_height),
                line,
                font=title_font,
                fill=TEXT_MAIN,
                anchor="mm",
            )
        if box.room.room_type:
            draw.text(
                (box.cx, start_y + len(lines) * line_height + 2),
                box.room.room_type.replace("_", " "),
                font=label_font,
                fill=TEXT_DIM,
                anchor="mm",
            )

    if heading:
        draw.text((MARGIN, 34), heading, font=heading_font, fill=TEXT_MAIN, anchor="lm")

    draw.text(
        (MARGIN, height - 26),
        "AI estimated layout · schematic, not to scale",
        font=footer_font,
        fill=TEXT_DIM,
        anchor="lm",
    )

    out = io.BytesIO()
    image.save(out, format="PNG", optimize=True)
    return out.getvalue()


def build_floor_plan_image(
    rooms: list[RoomInput],
    edges: list[tuple[str, str]],
    start_scene_id: str | None = None,
    heading: str | None = None,
) -> tuple[bytes, list[dict[str, Any]]]:
    """Layout + render one shot. Returns (png bytes, marker rows)."""
    if not rooms:
        raise ValueError("A floor plan needs at least one room")
    boxes, width, height = build_layout(rooms, edges, start_scene_id)
    png = render_layout_png(boxes, edges, width, height, heading)
    return png, layout_markers(boxes, width, height)


__all__ = [
    "RoomInput",
    "RoomBox",
    "build_floor_plan_image",
    "build_layout",
    "layout_markers",
    "place_rooms",
    "render_layout_png",
]
