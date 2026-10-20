"""
Shared helpers for the tour service package.

Ownership checks, the JSON merge used by PATCH bodies, analytics duration
parsing, and the scene-processing task registry. Field validation (hotspot
content, link URLs, HTML sanitization) lives in ``app.schemas.tour``.
"""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from typing import Any

from app.core.exceptions import ForbiddenException
from app.models.tours import Scene, Tour

# ---------------------------------------------------------------------------
# Ownership checks
# ---------------------------------------------------------------------------


def _ensure_tour_ownership(tour: Tour, user_id: int, action: str = "access") -> None:
    """Raise 403 if user doesn't own the tour."""
    if tour.user_id != user_id:
        raise ForbiddenException(detail=f"You don't have permission to {action} this tour")


def _ensure_scene_ownership(scene: Scene, user_id: int, action: str = "access") -> None:
    """Raise 403 if user doesn't own the scene's tour."""
    if scene.tour.user_id != user_id:
        raise ForbiddenException(detail=f"You don't have permission to {action} this scene")


# ---------------------------------------------------------------------------
# JSON column merge (PATCH)
# ---------------------------------------------------------------------------


def merge_json(existing: dict[str, Any] | None, patch: dict[str, Any]) -> dict[str, Any]:
    """Deep-merge ``patch`` into ``existing``.

    Nested dicts merge key by key. A value of None deletes the key, so a client
    can clear a field. Other values replace the stored value. Keys that the
    patch does not name keep their stored value.
    """
    result: dict[str, Any] = dict(existing or {})
    for key, value in patch.items():
        if value is None:
            result.pop(key, None)
        elif isinstance(value, dict):
            base = result.get(key)
            result[key] = merge_json(base if isinstance(base, dict) else {}, value)
        else:
            result[key] = value
    return result


def drop_keys(stored: dict[str, Any] | None, model_fields: set[str]) -> dict[str, Any]:
    """Drop stored top-level keys the model no longer declares (legacy JSON) before a merge."""
    return {key: value for key, value in (stored or {}).items() if key in model_fields}


# ---------------------------------------------------------------------------
# Analytics helper
# ---------------------------------------------------------------------------


def _extract_session_duration(event, session_starts: dict) -> float | None:
    """Extract session duration from an analytics event."""
    payload = event.event_data or {}
    duration = payload.get("duration_seconds")
    if duration is None and payload.get("duration_ms") is not None:
        duration = float(payload.get("duration_ms") or 0) / 1000
    if duration is None and payload.get("duration") is not None:
        duration = payload.get("duration")
    if duration is None and event.session_id and event.session_id in session_starts:
        duration = (event.created_at - session_starts[event.session_id]).total_seconds()
    return float(duration) if duration is not None else None


# ---------------------------------------------------------------------------
# Background task registry for scene processing
# ---------------------------------------------------------------------------

MAX_SCENE_PROCESSING_TASKS = 500
_scene_processing_tasks: OrderedDict[str, asyncio.Task] = OrderedDict()


def _register_scene_processing_task(scene_id: str, task: asyncio.Task) -> None:
    """Register a scene-processing task with oldest-entry eviction."""
    _scene_processing_tasks.pop(scene_id, None)
    while len(_scene_processing_tasks) >= MAX_SCENE_PROCESSING_TASKS:
        _, old_task = _scene_processing_tasks.popitem(last=False)
        if not old_task.done():
            old_task.cancel()
    _scene_processing_tasks[scene_id] = task
