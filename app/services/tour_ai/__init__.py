"""
AI Services for 360 Virtual Tour Operations.

This package provides AI-powered features for scene analysis,
hotspot suggestions, and description generation using the Gemini AI provider.

All public functions are re-exported here for backward compatibility.
Existing imports like ``from app.services.tour_ai import process_ai_job``
continue to work unchanged.
"""

# ---- helpers (constants & utility functions) ----
# ---- background (tour generation, optimization, apply suggestions) ----
from .background import (
    _run_tour_generation,
    _run_tour_optimization,
    apply_hotspot_suggestions,
    apply_scene_analysis,
    generate_tour,
    optimize_tour,
)
from .helpers import (
    _AI_TASK_SEMAPHORE,
    MAX_RETRIES,
    MAX_WAIT_SECONDS,
    MIN_WAIT_SECONDS,
    ROOM_TYPES,
    SCENE_ANALYSIS_PROMPT,
    _build_hotspot_suggestion_prompt,
    _complete_json_with_retry,
    _create_retry_decorator,
    _download_image_as_base64,
    _ensure_navigation_hotspots,
    _get_ai_provider_safe,
    _run_with_semaphore,
)

# ---- hotspot_suggestions (AI hotspot placement) ----
from .hotspot_suggestions import (
    _run_hotspot_suggestions,
    _run_tour_hotspot_suggestions,
    suggest_scene_hotspots,
    suggest_tour_hotspots,
)

# ---- jobs (AI job CRUD) ----
from .jobs import (
    cancel_ai_job,
    create_ai_job,
    get_ai_job,
    get_user_ai_jobs,
    update_job_status,
)

# ---- scene_analysis (scene analysis & description generation) ----
from .scene_analysis import (
    _run_description_generation,
    _run_scene_analysis,
    _run_tour_analysis,
    _run_tour_description_generation,
    analyze_scene,
    analyze_tour_scenes,
    generate_scene_description,
    generate_tour_descriptions,
)

__all__ = [
    # helpers
    "MAX_RETRIES",
    "MIN_WAIT_SECONDS",
    "MAX_WAIT_SECONDS",
    "ROOM_TYPES",
    "SCENE_ANALYSIS_PROMPT",
    "_AI_TASK_SEMAPHORE",
    "_build_hotspot_suggestion_prompt",
    "_complete_json_with_retry",
    "_create_retry_decorator",
    "_download_image_as_base64",
    "_ensure_navigation_hotspots",
    "_get_ai_provider_safe",
    "_run_with_semaphore",
    # jobs
    "cancel_ai_job",
    "create_ai_job",
    "get_ai_job",
    "get_user_ai_jobs",
    "update_job_status",
    # scene_analysis
    "analyze_scene",
    "analyze_tour_scenes",
    "generate_scene_description",
    "generate_tour_descriptions",
    "_run_scene_analysis",
    "_run_tour_analysis",
    "_run_description_generation",
    "_run_tour_description_generation",
    # hotspot_suggestions
    "suggest_scene_hotspots",
    "suggest_tour_hotspots",
    "_run_hotspot_suggestions",
    "_run_tour_hotspot_suggestions",
    # background
    "apply_scene_analysis",
    "apply_hotspot_suggestions",
    "generate_tour",
    "optimize_tour",
    "_run_tour_generation",
    "_run_tour_optimization",
]
