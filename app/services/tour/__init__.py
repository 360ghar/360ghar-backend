"""
Service layer for 360 Virtual Tour operations.

This package contains business logic for tour, scene, hotspot,
floor plan, and analytics management. All public functions are
re-exported here for backward compatibility — existing callers
like ``from app.services.tour import get_tour`` continue to work.
"""

from app.services.tour.analytics import (
    get_dashboard_realtime_stats,
    get_dashboard_stats,
    get_tour_analytics,
    get_tour_heatmap,
    record_analytics_event,
)
from app.services.tour.floor_plans import (
    create_floor_plan,
    delete_floor_plan,
    get_floor_plan,
    get_floor_plans,
    update_floor_plan,
    update_floor_plan_markers,
)
from app.services.tour.helpers import (
    _HOTSPOT_HTML_ALLOWED_ATTRIBUTES,
    _HOTSPOT_HTML_ALLOWED_PROTOCOLS,
    _HOTSPOT_HTML_ALLOWED_TAGS,
    _ensure_scene_ownership,
    _ensure_tour_ownership,
    _extract_session_duration,
    _extract_vimeo_id,
    _extract_youtube_id,
    _is_safe_http_url,
    _normalize_hotspot_content,
    _sanitize_hotspot_html,
    _scene_processing_tasks,
)
from app.services.tour.hotspots import (
    create_hotspot,
    delete_hotspot,
    get_hotspot,
    get_hotspots,
    update_hotspot,
    update_hotspot_position,
)
from app.services.tour.scenes import (
    create_scene,
    delete_scene,
    get_scene,
    get_scenes,
    process_scene_image_background,
    reorder_scenes,
    schedule_scene_processing,
    update_scene,
)
from app.services.tour.tours import (
    create_tour,
    delete_tour,
    duplicate_tour,
    generate_short_code,
    get_tour,
    get_tours,
    publish_tour,
    unpublish_tour,
    update_tour,
)

__all__ = [
    # Tours
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
    "process_scene_image_background",
    "reorder_scenes",
    "schedule_scene_processing",
    "update_scene",
    # Hotspots
    "create_hotspot",
    "delete_hotspot",
    "get_hotspot",
    "get_hotspots",
    "update_hotspot",
    "update_hotspot_position",
    # Floor plans
    "create_floor_plan",
    "delete_floor_plan",
    "get_floor_plan",
    "get_floor_plans",
    "update_floor_plan",
    "update_floor_plan_markers",
    # Analytics
    "get_dashboard_realtime_stats",
    "get_dashboard_stats",
    "get_tour_analytics",
    "get_tour_heatmap",
    "record_analytics_event",
    # Helpers (public for cross-module use and tests)
    "_HOTSPOT_HTML_ALLOWED_ATTRIBUTES",
    "_HOTSPOT_HTML_ALLOWED_PROTOCOLS",
    "_HOTSPOT_HTML_ALLOWED_TAGS",
    "_ensure_scene_ownership",
    "_ensure_tour_ownership",
    "_extract_session_duration",
    "_extract_vimeo_id",
    "_extract_youtube_id",
    "_is_safe_http_url",
    "_normalize_hotspot_content",
    "_sanitize_hotspot_html",
    "_scene_processing_tasks",
]
