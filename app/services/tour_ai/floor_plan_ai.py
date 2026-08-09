"""
AI-powered floor plan analysis for 360° virtual tours.

Parses a floor plan image using vision AI to detect room labels and positions,
then matches detected rooms to existing tour scenes by room type.
"""
from __future__ import annotations

from typing import Any

from app.core.logging import get_logger
from app.services.ai import AIMessage, AIRole, VisionInput
from app.services.tour_ai.helpers import ROOM_TYPES, _complete_json_with_retry

logger = get_logger(__name__)


FLOOR_PLAN_SYSTEM_PROMPT = (
    "You are an expert architect analyzing a floor plan image. "
    "Detect all labeled rooms or spaces visible in the floor plan. "
    "Report each room's approximate center position as x_fraction (0=left, 1=right) "
    "and y_fraction (0=top, 1=bottom). "
    "Match each room to one of the standard room types. "
    "Respond with STRICT JSON only, no prose."
)


def _build_floor_plan_prompt(room_types_list: str) -> str:
    return (
        "Analyze this floor plan and return JSON with this exact shape:\n"
        "{\n"
        '  "rooms": [\n'
        "    {\n"
        '      "label": "text label visible on floor plan (e.g. \'Kitchen\', \'BR1\')",\n'
        f'      "room_type": "one of [{room_types_list}]",\n'
        '      "x_fraction": 0.0-1.0 (horizontal center of room),\n'
        '      "y_fraction": 0.0-1.0 (vertical center of room),\n'
        '      "confidence": 0.0-1.0\n'
        "    }\n"
        "  ]\n"
        "}"
    )


async def analyze_floor_plan(
    provider: Any,
    image_base64: str,
    mime_type: str,
) -> list[dict[str, Any]]:
    """Run vision AI on a floor plan image to detect rooms.

    Returns a list of detected rooms with: label, room_type, x_fraction, y_fraction, confidence.
    """
    room_types_list = ", ".join(ROOM_TYPES)
    messages = [
        AIMessage(role=AIRole.SYSTEM, content=FLOOR_PLAN_SYSTEM_PROMPT),
        AIMessage(role=AIRole.USER, content=_build_floor_plan_prompt(room_types_list)),
    ]
    vision = VisionInput(image_base64=image_base64, mime_type=mime_type)
    raw = await _complete_json_with_retry(provider, messages, vision)

    rooms = []
    for r in raw.get("rooms", []) or []:
        if not isinstance(r, dict) or "room_type" not in r:
            continue
        room_type = str(r.get("room_type") or "other").strip().lower().replace(" ", "_")
        if room_type not in ROOM_TYPES:
            room_type = "other"
        rooms.append({
            "label": str(r.get("label") or room_type).strip(),
            "room_type": room_type,
            "x_fraction": float(r.get("x_fraction") or 0.5),
            "y_fraction": float(r.get("y_fraction") or 0.5),
            "confidence": float(r.get("confidence") or 0.5),
        })
    return rooms


def match_rooms_to_scenes(
    floor_plan_rooms: list[dict[str, Any]],
    scenes: list[Any],  # ORM Scene objects with .id, .title, .scene_metadata
) -> list[dict[str, Any]]:
    """Match floor plan rooms to tour scenes by room type.

    Returns a list of marker dicts ready for update_floor_plan_markers():
    [{scene_id, x, y, label}]
    """
    from collections import defaultdict

    # Build a lookup: room_type -> list of unmatched scene ids
    scene_by_type: dict[str, list] = defaultdict(list)
    for scene in scenes:
        # Try to get room_type from scene_metadata
        meta = scene.scene_metadata or {}
        room_type = meta.get("room_type") or "other"
        scene_by_type[room_type].append(scene)

    markers = []
    used_scene_ids: set[str] = set()

    # Sort floor plan rooms by confidence desc for best matches first
    for room in sorted(floor_plan_rooms, key=lambda r: -r["confidence"]):
        rt = room["room_type"]
        candidates = [s for s in scene_by_type.get(rt, []) if s.id not in used_scene_ids]

        # Fallback: try "other" scenes
        if not candidates:
            candidates = [s for s in scene_by_type.get("other", []) if s.id not in used_scene_ids]

        if not candidates:
            # No scenes left to match — skip
            continue

        scene = candidates[0]
        used_scene_ids.add(scene.id)
        markers.append({
            "scene_id": scene.id,
            "x": room["x_fraction"] * 100,  # Convert to percentage (0-100)
            "y": room["y_fraction"] * 100,
            "label": room["label"],
        })

    return markers


__all__ = ["analyze_floor_plan", "match_rooms_to_scenes"]
