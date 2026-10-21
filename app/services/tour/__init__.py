"""
Service layer for 360 Virtual Tour operations.

This package contains business logic for tour, scene, hotspot,
floor plan, and analytics management. All public functions are
re-exported here for backward compatibility — existing callers
like ``from app.services.tour import get_tour`` continue to work.
"""

from app.services.tour.analytics import (
    EVENT_DEDUPE_WINDOW_S,
    VIEW_DEDUPE_WINDOW_S,
    get_dashboard_realtime_stats,
    get_dashboard_stats,
    get_tour_analytics,
    get_tour_heatmap,
    is_repeat_viewer_event,
    record_analytics_event,
)
from app.services.tour.floor_plans import (
    create_floor_plan,
    delete_floor_plan,
    generate_floor_plan,
    get_floor_plan,
    get_floor_plans_page,
    update_floor_plan,
    update_floor_plan_markers,
)
from app.services.tour.helpers import (
    _ensure_scene_ownership,
    _ensure_tour_ownership,
    _extract_session_duration,
    _scene_processing_tasks,
)
from app.services.tour.hotspots import (
    create_hotspot,
    delete_hotspot,
    get_hotspot,
    get_hotspots,
    get_hotspots_page,
    update_hotspot,
    update_hotspot_position,
)
from app.services.tour.scenes import (
    create_scene,
    delete_scene,
    get_scene,
    get_scenes,
    get_scenes_page,
    process_scene_image_background,
    reorder_scenes,
    schedule_scene_processing,
    update_scene,
)
from app.services.tour.tours import (
    active_hotspots_only,
    create_tour,
    delete_tour,
    duplicate_tour,
    generate_short_code,
    get_tour,
    get_tours,
    public_tour_view,
    publish_tour,
    unpublish_tour,
    update_tour,
)

__all__ = [
    # Tours
    "active_hotspots_only",
    "public_tour_view",
    "create_tour",
    "delete_tour",
    "duplicate_tour",
    "generate_short_code",
    "get_tour",
    "get_tours",
    "publish_tour",
    "unpublish_tour",
    "update_tour",
    # Scenes
    "create_scene",
    "delete_scene",
    "get_scene",
    "get_scenes",
    "get_scenes_page",
    "process_scene_image_background",
    "reorder_scenes",
    "schedule_scene_processing",
    "update_scene",
    # Hotspots
    "create_hotspot",
    "delete_hotspot",
    "get_hotspot",
    "get_hotspots",
    "get_hotspots_page",
    "update_hotspot",
    "update_hotspot_position",
    # Floor plans
    "create_floor_plan",
    "delete_floor_plan",
    "generate_floor_plan",
    "get_floor_plan",
    "get_floor_plans_page",
    "update_floor_plan",
    "update_floor_plan_markers",
    # Analytics
    "get_dashboard_realtime_stats",
    "get_dashboard_stats",
    "get_tour_analytics",
    "get_tour_heatmap",
    "EVENT_DEDUPE_WINDOW_S",
    "VIEW_DEDUPE_WINDOW_S",
    "is_repeat_viewer_event",
    "record_analytics_event",
    # Helpers (public for cross-module use and tests)
    "_ensure_scene_ownership",
    "_ensure_tour_ownership",
    "_extract_session_duration",
    "_scene_processing_tasks",
]
