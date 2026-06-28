"""Spatial (Matterport-style) tour generation from room panoramas.

Turns a set of equirectangular room panoramas into a connected tour: each scene
gets navigation hotspots placed on the actual doorway/opening that leads to the
correct adjacent room. Panorama-only — no floor plan is used.

This is the automated implementation of the manual procedure documented in
``360-viewer/docs/spatial-tour-sop.md``. It reuses the existing Gemini provider
(``app.services.ai``) for vision + structured JSON output.

Pipeline:
    1. analyze_panorama()  — per image: detect room type + openings (as image
       fractions) + the room visible through each opening.  (LLM)
    2. assign_scene_ids()  — derive stable scene ids from detected room types.
    3. build_graph()       — match each opening to the best target scene, enforce
       bidirectional links, dedupe, and repair connectivity.  (deterministic)
    4. build_spatial_tour() — orchestrates the above into a tour-plan dict whose
       scene/hotspot shape mirrors the API (Scene/Hotspot) and tour.json.

Coordinate convention (see coordinates.ts + PSV v5):
    yaw  = x_fraction * 360 - 180     (0 = image center, + right, - left)
    pitch = 90 - y_fraction * 180     (0 = horizon, - = floor)
Navigation pucks are floor-anchored: pitch clamped into [-45, -10].
"""
from __future__ import annotations

import math
from collections import deque
from typing import Any

from app.core.logging import get_logger
from app.services.ai import AIMessage, AIRole, VisionInput
from app.services.tour_ai.helpers import ROOM_TYPES, _complete_json_with_retry

logger = get_logger(__name__)

NAV_PITCH_DEFAULT = -28.0
NAV_PITCH_MIN = -45.0
NAV_PITCH_MAX = -10.0

OPENING_TYPES = ["door", "open_archway", "glass_sliding_door", "passage", "other"]


SPATIAL_SYSTEM_PROMPT = (
    "You are an expert virtual-tour builder analysing a single 360 equirectangular "
    "room photo (a flat image that wraps 360 degrees horizontally; the LEFT edge and "
    "RIGHT edge are the same direction behind the camera; the horizontal CENTER is "
    "straight ahead). Identify the room and every traversable opening that leads to "
    "another space.\n\n"
    "Report horizontal position as x_fraction in [0,1] (0 = left edge, 0.5 = center, "
    "1 = right edge) and the opening's FLOOR point as floor_y_fraction in [0,1] "
    "(0 = top, 1 = bottom; a doorway threshold floor is usually 0.6-0.8).\n\n"
    "Rules:\n"
    "- Classify the room from PIXELS, never assume from any filename hint.\n"
    "- An opening is a doorway (open or closed), an open archway, a glass sliding "
    "door to a balcony/terrace, or a passage. Do NOT report plain windows or mirrors "
    "(a mirror reflects the SAME room; a real opening shows a DIFFERENT space).\n"
    "- For each opening, say which room type is visible THROUGH it (leads_to_room_type) "
    "and your confidence. If the door is closed/unknown, set leads_to_room_type to null.\n"
    "- Respond with STRICT JSON only, no prose."
)


def _build_user_prompt(filename_hint: str | None) -> str:
    room_list = ", ".join(ROOM_TYPES)
    hint = f"\nWeak filename hint (may be WRONG, verify from pixels): {filename_hint}" if filename_hint else ""
    return (
        "Analyse this 360 panorama and return JSON with this exact shape:\n"
        "{\n"
        f'  "room_type": one of [{room_list}],\n'
        '  "room_confidence": 0.0-1.0,\n'
        '  "suggested_title": "short human title e.g. \\"Master Bedroom\\"",\n'
        '  "suggested_description": "1-2 sentences",\n'
        '  "facing_x_fraction": 0.0-1.0 (a good initial view direction: the main '
        "feature or the most important onward doorway),\n"
        '  "openings": [\n'
        "    {\n"
        f'      "type": one of [{", ".join(OPENING_TYPES)}],\n'
        '      "x_fraction": 0.0-1.0,\n'
        '      "floor_y_fraction": 0.0-1.0,\n'
        '      "leads_to_room_type": one of the room types or null if unknown,\n'
        '      "leads_to_confidence": 0.0-1.0,\n'
        '      "label": "short label e.g. \\"to kitchen\\""\n'
        "    }\n"
        "  ]\n"
        "}"
        f"{hint}"
    )


def _frac_to_yaw(x_fraction: float) -> float:
    x = min(1.0, max(0.0, float(x_fraction)))
    return round(x * 360.0 - 180.0, 1)


def _frac_to_floor_pitch(y_fraction: float | None) -> float:
    if y_fraction is None:
        return NAV_PITCH_DEFAULT
    pitch = 90.0 - min(1.0, max(0.0, float(y_fraction))) * 180.0
    return round(min(NAV_PITCH_MAX, max(NAV_PITCH_MIN, pitch)), 1)


async def analyze_panorama(
    provider: Any,
    image_base64: str,
    mime_type: str,
    filename_hint: str | None = None,
) -> dict[str, Any]:
    """Run the vision model on one panorama; return normalized analysis.

    Returns: {room_type, room_confidence, suggested_title, suggested_description,
              facing_yaw, openings:[{type, yaw, pitch, leads_to_room_type,
              leads_to_confidence, label}]}
    """
    messages = [
        AIMessage(role=AIRole.SYSTEM, content=SPATIAL_SYSTEM_PROMPT),
        AIMessage(role=AIRole.USER, content=_build_user_prompt(filename_hint)),
    ]
    vision = VisionInput(image_base64=image_base64, mime_type=mime_type)
    raw = await _complete_json_with_retry(provider, messages, vision)

    room_type = str(raw.get("room_type") or "other").strip().lower().replace(" ", "_")
    if room_type not in ROOM_TYPES:
        room_type = "other"

    openings: list[dict[str, Any]] = []
    for op in raw.get("openings", []) or []:
        if not isinstance(op, dict) or "x_fraction" not in op:
            continue
        leads = op.get("leads_to_room_type")
        leads = str(leads).strip().lower().replace(" ", "_") if leads else None
        if leads not in ROOM_TYPES:
            leads = None
        openings.append(
            {
                "type": str(op.get("type") or "door"),
                "yaw": _frac_to_yaw(op["x_fraction"]),
                "pitch": _frac_to_floor_pitch(op.get("floor_y_fraction")),
                "leads_to_room_type": leads,
                "leads_to_confidence": float(op.get("leads_to_confidence") or 0.0),
                "label": str(op.get("label") or "").strip(),
            }
        )

    facing = raw.get("facing_x_fraction")
    facing_yaw = _frac_to_yaw(facing) if facing is not None else 0.0

    return {
        "room_type": room_type,
        "room_confidence": float(raw.get("room_confidence") or 0.0),
        "suggested_title": str(raw.get("suggested_title") or "").strip() or _title_from_type(room_type),
        "suggested_description": str(raw.get("suggested_description") or "").strip() or None,
        "facing_yaw": facing_yaw,
        "openings": openings,
    }


def _title_from_type(room_type: str) -> str:
    return room_type.replace("_", " ").title()


# Preferred start ordering by room type (lower = earlier).
_ORDER_PRIORITY = {
    "entrance": 0, "hallway": 1, "living_room": 2, "dining_room": 3, "kitchen": 4,
    "home_office": 5, "bedroom": 6, "bathroom": 7, "balcony": 8, "terrace": 9,
}


def assign_scene_ids(analyses: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Turn per-image analyses into scene dicts with unique ids.

    Each input item must carry a stable "key" (e.g. filename) and "image_url"
    (relative path or URL) alongside the analysis fields.
    """
    seen: dict[str, int] = {}
    scenes: list[dict[str, Any]] = []
    for a in analyses:
        rt = a["room_type"]
        seen[rt] = seen.get(rt, 0) + 1
        scene_id = rt if seen[rt] == 1 else f"{rt}_{seen[rt]}"
        scenes.append(
            {
                "id": scene_id,
                "key": a.get("key"),
                "room_type": rt,
                "title": a["suggested_title"],
                "description": a.get("suggested_description"),
                "image_url": a.get("image_url"),
                "facing_yaw": a.get("facing_yaw", 0.0),
                "openings": a.get("openings", []),
                "hotspots": [],
            }
        )
    # Second pass: if a room type ended up with duplicates, the first one keeps the
    # bare id but is ambiguous as a match target — that's fine, matching prefers the
    # closest-by-confidence and dedupes per (scene,target).
    return scenes


def _match_target(
    source: dict[str, Any],
    opening: dict[str, Any],
    scenes: list[dict[str, Any]],
    already_linked: set[str],
) -> str | None:
    """Pick the best target scene id for an opening, or None."""
    leads = opening.get("leads_to_room_type")
    if not leads:
        return None
    candidates = [s for s in scenes if s["room_type"] == leads and s["id"] != source["id"]]
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]["id"]
    # Multiple: prefer one not already linked from this source.
    for c in candidates:
        if c["id"] not in already_linked:
            return c["id"]
    return candidates[0]["id"]


def _add_hotspot(scene: dict[str, Any], target_id: str, opening: dict[str, Any], target_title: str) -> None:
    scene["hotspots"].append(
        {
            "id": f"{scene['id']}->{target_id}",
            "type": "navigation",
            "target_scene_id": target_id,
            "title": target_title,
            "position": {"yaw": opening["yaw"], "pitch": opening["pitch"]},
            "custom_data": {"auto_generated": True, "opening_type": opening.get("type")},
        }
    )


def build_graph(scenes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Place navigation hotspots: match openings -> scenes, make bidirectional,
    dedupe, and repair connectivity so every scene is reachable."""
    by_id = {s["id"]: s for s in scenes}

    # Pass 1: direct matches from each opening's leads_to_room_type.
    for s in scenes:
        linked: set[str] = set()
        # higher-confidence openings first so multi-candidate matching is stable
        for op in sorted(s["openings"], key=lambda o: -o.get("leads_to_confidence", 0)):
            target = _match_target(s, op, scenes, linked)
            if not target or target in linked:
                continue
            linked.add(target)
            _add_hotspot(s, target, op, by_id[target]["title"])

    # Pass 2: enforce bidirectionality.
    for s in scenes:
        for hs in list(s["hotspots"]):
            target = by_id.get(hs["target_scene_id"])
            if not target:
                continue
            has_reciprocal = any(h["target_scene_id"] == s["id"] for h in target["hotspots"])
            if has_reciprocal:
                continue
            # Prefer an opening in target that points back at this room type.
            op = _best_opening_for(target, s["room_type"])
            if op is None:
                continue  # leave one-way; still reachable elsewhere
            _add_hotspot(target, s["id"], op, s["title"])

    # Pass 3: connectivity repair (every scene reachable from the start scene).
    _repair_connectivity(scenes, by_id)

    # Dedupe per (scene, target): keep first (highest-confidence by construction).
    for s in scenes:
        seen: set[str] = set()
        deduped = []
        for hs in s["hotspots"]:
            if hs["target_scene_id"] in seen:
                continue
            seen.add(hs["target_scene_id"])
            deduped.append(hs)
        _spread_overlapping_hotspots(deduped)
        for i, hs in enumerate(deduped):
            hs["order_index"] = i
        s["hotspots"] = deduped

    return scenes


_MIN_PUCK_SEPARATION = 14.0  # degrees


def _spread_overlapping_hotspots(hotspots: list[dict[str, Any]]) -> None:
    """Fan out pucks that collapsed onto (nearly) the same yaw.

    When a hub room has fewer detected openings than links (common with imperfect
    panorama-only detection), reciprocal/connectivity links stack at one yaw and
    become un-clickable. Cluster those and spread them evenly around the cluster
    centre, keeping them near the real opening but individually selectable.
    """
    if len(hotspots) < 2:
        return
    ordered = sorted(hotspots, key=lambda h: h["position"]["yaw"])
    cluster: list[dict[str, Any]] = []

    def flush(group: list[dict[str, Any]]) -> None:
        if len(group) < 2:
            return
        # Circular mean to handle ±180° wrap-around correctly.
        sin_sum = sum(math.sin(math.radians(h["position"]["yaw"])) for h in group)
        cos_sum = sum(math.cos(math.radians(h["position"]["yaw"])) for h in group)
        centre = math.degrees(math.atan2(sin_sum, cos_sum))
        span = (len(group) - 1) * _MIN_PUCK_SEPARATION
        start = centre - span / 2
        for i, h in enumerate(group):
            yaw = start + i * _MIN_PUCK_SEPARATION
            h["position"]["yaw"] = round(((yaw + 180.0) % 360.0) - 180.0, 1)

    def _angular_distance(a: float, b: float) -> float:
        """Shortest angular distance between two yaw values in [-180, 180]."""
        diff = abs(a - b) % 360.0
        return min(diff, 360.0 - diff)

    # Collect all clusters first so we can merge wrap-around stragglers.
    all_clusters: list[list[dict[str, Any]]] = []
    for h in ordered:
        if cluster and _angular_distance(h["position"]["yaw"], cluster[-1]["position"]["yaw"]) < _MIN_PUCK_SEPARATION:
            cluster.append(h)
        else:
            if cluster:
                all_clusters.append(cluster)
            cluster = [h]
    if cluster:
        all_clusters.append(cluster)

    # Merge first and last cluster if they are adjacent across the ±180° boundary.
    if len(all_clusters) >= 2:
        first = all_clusters[0]
        last = all_clusters[-1]
        if _angular_distance(last[-1]["position"]["yaw"], first[0]["position"]["yaw"]) < _MIN_PUCK_SEPARATION:
            all_clusters[0] = last + first
            all_clusters.pop()

    for group in all_clusters:
        flush(group)


def _best_opening_for(scene: dict[str, Any], target_room_type: str) -> dict[str, Any] | None:
    """Pick the opening in `scene` most likely to lead to target_room_type, else
    the highest-confidence opening not yet used, else any opening."""
    used_yaws = {h["position"]["yaw"] for h in scene["hotspots"]}
    matching = [o for o in scene["openings"] if o.get("leads_to_room_type") == target_room_type]
    pool = matching or scene["openings"]
    free = [o for o in pool if o["yaw"] not in used_yaws]
    pool = free or pool
    if not pool:
        return None
    return max(pool, key=lambda o: o.get("leads_to_confidence", 0.0))


def start_scene_id(scenes: list[dict[str, Any]]) -> str:
    """Choose the start scene: entrance/living first, else most-connected."""
    ranked = sorted(
        scenes,
        key=lambda s: (_ORDER_PRIORITY.get(s["room_type"], 50), -len(s["hotspots"])),
    )
    return ranked[0]["id"] if ranked else scenes[0]["id"]


def _repair_connectivity(scenes: list[dict[str, Any]], by_id: dict[str, dict[str, Any]]) -> None:
    if len(scenes) < 2:
        return
    start = start_scene_id(scenes)
    # BFS over the (now bidirectional-ish) hotspot graph.
    reached = {start}
    q = deque([start])
    while q:
        cur = q.popleft()
        for hs in by_id[cur]["hotspots"]:
            t = hs["target_scene_id"]
            if t not in reached:
                reached.add(t)
                q.append(t)

    if len(reached) == len(scenes):
        return

    # Connect each unreached scene to the least-connected reached scene via its
    # best opening (or center if none), and add the reciprocal.
    # Use a snapshot of hotspot counts and update after each connection so that
    # unreached scenes are distributed across multiple hubs rather than all
    # connecting to the single most-connected one.
    hub_counts = {r: len(by_id[r]["hotspots"]) for r in reached}
    for s in scenes:
        if s["id"] in reached:
            continue
        hub_id = min(hub_counts, key=lambda r: hub_counts[r])
        hub = by_id[hub_id]
        op_out = _best_opening_for(s, hub["room_type"]) or _fallback_opening(s)
        _add_hotspot(s, hub["id"], op_out, hub["title"])
        op_back = _best_opening_for(hub, s["room_type"]) or _fallback_opening(hub)
        _add_hotspot(hub, s["id"], op_back, s["title"])
        # Update the snapshot count so the next iteration distributes to a
        # different hub if one with fewer connections exists.
        hub_counts[hub_id] = hub_counts.get(hub_id, 0) + 2
        reached.add(s["id"])


def _fallback_opening(scene: dict[str, Any]) -> dict[str, Any]:
    if scene["openings"]:
        return scene["openings"][0]
    return {"yaw": round(scene.get("facing_yaw", 0.0), 1), "pitch": NAV_PITCH_DEFAULT, "type": "other"}


def scenes_to_tour_plan(title: str, scenes: list[dict[str, Any]]) -> dict[str, Any]:
    """Serialize graph scenes into the tour.json / API shape."""
    ordered = sorted(scenes, key=lambda s: (_ORDER_PRIORITY.get(s["room_type"], 50), s["id"]))
    start = start_scene_id(scenes)
    out_scenes = []
    for idx, s in enumerate(ordered):
        out_scenes.append(
            {
                "id": s["id"],
                "title": s["title"],
                "description": s.get("description"),
                "image_url": s.get("image_url"),
                "order_index": idx,
                "metadata": {"initial_view": {"yaw": s.get("facing_yaw", 0.0), "pitch": 0, "zoom": 50}},
                "hotspots": s["hotspots"],
            }
        )
    return {
        "title": title,
        "generator": "spatial-ai-v1",
        "initial_scene_id": start,
        "scenes": out_scenes,
    }


async def analyze_and_build_scenes(
    panoramas: list[dict[str, Any]],
    provider: Any,
) -> list[dict[str, Any]]:
    """Analyse panoramas and build the connected scene graph.

    Returns the intermediate graph scenes (each retains its original ``key`` from
    the input and carries placed ``hotspots`` referencing plan scene ids). The DB
    wiring uses ``key`` to map plan ids back to real Scene rows; the CLI passes the
    result to :func:`scenes_to_tour_plan`.

    Args:
        panoramas: list of {key, image_base64, mime_type, image_url, filename_hint?}
        provider: an AIProvider (Gemini). Reused via complete_json.
    """
    import asyncio

    _VISION_SEMAPHORE = asyncio.Semaphore(4)

    async def _analyze_one(p: dict[str, Any]) -> dict[str, Any] | None:
        try:
            async with _VISION_SEMAPHORE:
                analysis = await analyze_panorama(
                    provider,
                    image_base64=p["image_base64"],
                    mime_type=p.get("mime_type", "image/jpeg"),
                    filename_hint=p.get("filename_hint") or p.get("key"),
                )
        except Exception as exc:
            # One bad/over-loaded image shouldn't sink the whole tour — skip it and
            # still build a tour from the rest. The scene remains in the tour (added
            # by the caller); it just won't originate spatial links this run.
            logger.warning("spatial: analysis failed for %s, skipping: %s", p.get("key"), exc)
            return None
        analysis["key"] = p.get("key")
        analysis["image_url"] = p.get("image_url")
        logger.info(
            "spatial: analysed %s -> %s (%d openings)",
            p.get("key"), analysis["room_type"], len(analysis["openings"]),
        )
        return analysis

    results = await asyncio.gather(*[_analyze_one(p) for p in panoramas])
    analyses = [r for r in results if r is not None]

    if not analyses:
        raise RuntimeError("spatial: all panorama analyses failed")

    scenes = assign_scene_ids(analyses)
    build_graph(scenes)
    return scenes


async def build_spatial_tour(
    panoramas: list[dict[str, Any]],
    provider: Any,
    title: str = "Virtual Tour",
) -> dict[str, Any]:
    """Build a complete spatial tour plan from panoramas.

    Returns: tour-plan dict (see scenes_to_tour_plan).
    """
    scenes = await analyze_and_build_scenes(panoramas, provider)
    return scenes_to_tour_plan(title, scenes)


def tour_plan_summary(plan: dict[str, Any]) -> str:
    """Human-readable summary of a tour plan (for CLI/logs)."""
    lines = [f"{plan['title']}  (start: {plan['initial_scene_id']})"]
    for s in plan["scenes"]:
        links = ", ".join(f"{h['target_scene_id']}@{h['position']['yaw']:.0f}deg" for h in s["hotspots"])
        lines.append(f"  {s['id']:<16} -> {links or '(no links)'}")
    return "\n".join(lines)


__all__ = [
    "analyze_panorama",
    "analyze_and_build_scenes",
    "assign_scene_ids",
    "build_graph",
    "build_spatial_tour",
    "scenes_to_tour_plan",
    "start_scene_id",
    "tour_plan_summary",
    "SPATIAL_SYSTEM_PROMPT",
]
