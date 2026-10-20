"""Contract tests for the tour schemas (no database).

Each test names the ledger item it guards (BE-tours slice).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from app.models.enums import AIJobType, HotspotType
from app.models.tours import Scene as SceneModel
from app.models.tours import Tour as TourModel
from app.schemas.base import PatchModel
from app.schemas.capture import CaptureDeviceInfo, CaptureSessionUpdate
from app.schemas.custom_domain import CustomDomainResponse
from app.schemas.tour import (
    ALLOWED_LINK_SCHEMES,
    AIJobBase,
    FloorPlanUpdate,
    Hotspot,
    HotspotCreate,
    HotspotUpdate,
    Scene,
    SceneCreate,
    SceneMetadata,
    Tour,
    TourEventPayload,
    TourSettings,
    TourUpdate,
    ViewerEventType,
    content_to_storage,
    validate_ai_result,
)
from app.services.tour.helpers import merge_json

_NOW = datetime(2026, 10, 14, tzinfo=UTC)
_POS = {"yaw": 10.0, "pitch": 5.0}


# -----------------------------------------------------------------------------
# NOT NULL fields reject explicit null on PATCH (be-tours-1, be-tours-25, tours-web-9)
# -----------------------------------------------------------------------------


def test_floor_plan_patch_rejects_null_markers():
    with pytest.raises(ValidationError):
        FloorPlanUpdate.model_validate({"markers": None})


def test_floor_plan_patch_rejects_null_name():
    with pytest.raises(ValidationError):
        FloorPlanUpdate.model_validate({"name": None})


def test_hotspot_patch_rejects_null_position_and_icon_size():
    with pytest.raises(ValidationError):
        HotspotUpdate.model_validate({"position": None})
    with pytest.raises(ValidationError):
        HotspotUpdate.model_validate({"icon_size": None})


def test_hotspot_patch_accepts_null_title_and_content_to_clear():
    body = HotspotUpdate.model_validate({"title": None, "content": None})
    assert body.model_fields_set == {"title", "content"}
    assert body.title is None and body.content is None


def test_tour_patch_rejects_null_title():
    with pytest.raises(ValidationError):
        TourUpdate.model_validate({"title": None})


# -----------------------------------------------------------------------------
# Write bodies are strict; status and is_featured are not writable (be-tours-4, be-tours-5)
# -----------------------------------------------------------------------------


def test_tour_update_cannot_set_status():
    with pytest.raises(ValidationError):
        TourUpdate.model_validate({"status": "published"})


def test_tour_update_cannot_set_is_featured():
    with pytest.raises(ValidationError):
        TourUpdate.model_validate({"is_featured": True})


def test_tour_update_is_a_patch_model():
    assert issubclass(TourUpdate, PatchModel)


def test_scene_create_rejects_client_order_index():
    """order_index is server-owned (be-tours-? order_index server-owned)."""
    with pytest.raises(ValidationError):
        SceneCreate.model_validate({"image_url": "https://cdn.example.com/a.jpg", "order_index": 0})


def test_settings_reject_floor_plans_key():
    """Floor plans live in the table only (be-tours-12, tours-web-4)."""
    with pytest.raises(ValidationError):
        TourSettings.model_validate({"floor_plans": []})


def test_settings_reject_unknown_key():
    with pytest.raises(ValidationError):
        TourSettings.model_validate({"auto_rotate": True, "bogus": 1})


# -----------------------------------------------------------------------------
# Hotspot content per type (be-tours-18, tours-web-8, tours-web-18)
# -----------------------------------------------------------------------------


def test_link_allows_mailto_and_tel():
    """Link schemes are defined once and match the sanitizer (tours-web-8)."""
    assert ALLOWED_LINK_SCHEMES == {"http", "https", "mailto", "tel"}
    for url in ("mailto:agent@example.com", "tel:+911234567890", "https://example.com/x"):
        stored = content_to_storage(HotspotType.link, {"url": url})
        assert stored["url"] == url


def test_link_rejects_javascript_scheme():
    with pytest.raises(ValidationError):
        content_to_storage(HotspotType.link, {"url": "javascript:alert(1)"})


def test_link_rejects_alias_keys():
    """link_url was an input alias. Input aliases are removed (be-tours-18)."""
    with pytest.raises(ValidationError):
        content_to_storage(HotspotType.link, {"link_url": "https://example.com"})


def test_audio_rejects_url_alias():
    with pytest.raises(ValidationError):
        content_to_storage(HotspotType.audio, {"url": "https://example.com/a.mp3"})


def test_content_must_match_hotspot_type():
    with pytest.raises(ValidationError):
        content_to_storage(HotspotType.audio, {"url": "https://example.com/a.mp3"})


def test_video_url_is_normalized_to_youtube_id():
    stored = content_to_storage(
        HotspotType.video, {"video_url": "https://www.youtube.com/watch?v=abc123"}
    )
    assert stored == {"youtube_id": "abc123"}


def test_video_needs_exactly_one_source():
    with pytest.raises(ValidationError):
        content_to_storage(HotspotType.video, {"youtube_id": "a", "vimeo_id": "1"})


def test_info_html_is_sanitized():
    stored = content_to_storage(HotspotType.info, {"html": "<p>ok</p><script>x()</script>"})
    assert "<script" not in stored["html"]
    assert "<p>ok</p>" in stored["html"]


def test_navigation_stores_no_content():
    assert content_to_storage(HotspotType.navigation, None) is None
    assert content_to_storage(HotspotType.navigation, {}) is None


def test_hotspot_create_content_is_typed_by_type():
    body = HotspotCreate.model_validate(
        {
            "type": "link",
            "position": _POS,
            "content": {"url": "https://example.com", "label": "Site"},
        }
    )
    assert body.content.url == "https://example.com"


def test_hotspot_create_rejects_content_for_wrong_type():
    with pytest.raises(ValidationError):
        HotspotCreate.model_validate(
            {"type": "audio", "position": _POS, "content": {"url": "https://a/b"}}
        )


def test_hotspot_title_and_description_limits_are_in_openapi_schema():
    """tours-web-18: the client needs the limits from the published schema."""
    props = HotspotCreate.model_json_schema()["properties"]
    assert props["title"]["anyOf"][0]["maxLength"] == 255
    assert props["description"]["anyOf"][0]["maxLength"] == 2000


def test_hotspot_read_drops_legacy_kind_key():
    """Rows written before the typed contract carry a server-added kind key."""
    hotspot = Hotspot.model_validate(
        {
            "id": "h1",
            "scene_id": "s1",
            "type": "link",
            "position": _POS,
            "content": {"kind": "link", "url": "https://example.com", "target": "_blank"},
            "icon_size": 32,
            "order_index": 0,
            "is_active": True,
            "created_at": _NOW,
            "updated_at": _NOW,
        }
    )
    assert hotspot.content is not None
    assert hotspot.content.url == "https://example.com"


def test_hotspot_read_returns_null_for_content_that_no_longer_validates():
    hotspot = Hotspot.model_validate(
        {
            "id": "h1",
            "scene_id": "s1",
            "type": "audio",
            "position": _POS,
            "content": {"url": "not-a-valid-audio-payload-for-audio"},
            "icon_size": 32,
            "order_index": 0,
            "is_active": True,
            "created_at": _NOW,
            "updated_at": _NOW,
        }
    )
    assert hotspot.content is None


# -----------------------------------------------------------------------------
# Scene metadata (be-tours-6, be-tours-7, branch-drift-21)
# -----------------------------------------------------------------------------


def test_scene_metadata_declares_server_written_keys():
    meta = SceneMetadata.model_validate(
        {
            "exif": {"Make": "X"},
            "dimensions": {"width": 4000, "height": 2000},
            "is_panorama": True,
            "room_type": "kitchen",
            "caption": "Bright kitchen",
            "narration_script": "Welcome",
        }
    )
    assert meta.dimensions.width == 4000


def test_merge_json_keeps_server_keys_and_null_clears():
    """be-tours-6: a PATCH that names only initial_view keeps exif, dimensions and is_panorama."""
    stored = {
        "exif": {"Make": "X"},
        "dimensions": {"width": 4000, "height": 2000},
        "is_panorama": True,
        "initial_view": {"yaw": 1.0, "pitch": 0.0, "zoom": 50},
    }
    merged = merge_json(stored, {"initial_view": {"yaw": 90.0}})
    assert merged["exif"] == {"Make": "X"}
    assert merged["is_panorama"] is True
    assert merged["initial_view"] == {"yaw": 90.0, "pitch": 0.0, "zoom": 50}

    cleared = merge_json(merged, {"is_panorama": None, "initial_view": {"zoom": None}})
    assert "is_panorama" not in cleared
    assert "zoom" not in cleared["initial_view"]


def test_merge_json_replaces_non_dict_values():
    assert merge_json({"a": [1]}, {"a": [2]}) == {"a": [2]}


def test_read_ignores_legacy_top_level_keys_in_scene_metadata():
    scene_row = SceneModel(
        id="s1",
        tour_id="t1",
        image_url="https://cdn.example.com/a.jpg",
        order_index=0,
        scene_metadata={"initial_view": {"yaw": 0.0, "pitch": 0.0}, "legacy_key": 1},
        is_processed=True,
        created_at=_NOW,
        updated_at=_NOW,
    )
    scene = Scene.model_validate(scene_row)
    assert scene.scene_metadata.initial_view.yaw == 0.0


def test_tour_read_tolerates_legacy_floor_plans_in_settings():
    """Legacy rows hold settings.floor_plans. The read drops it and keeps the rest."""
    tour = TourModel(
        id="t1",
        user_id=1,
        title="T",
        status="draft",
        visibility="private",
        is_public=False,
        view_count=0,
        like_count=0,
        share_count=0,
        is_featured=False,
        settings={"auto_rotate": True, "floor_plans": [{"id": "x"}]},
        created_at=_NOW,
        updated_at=_NOW,
    )
    out = Tour.model_validate(tour)
    assert out.settings is not None
    assert out.settings.auto_rotate is True


# -----------------------------------------------------------------------------
# Events (be-tours-? analytics; r2-json-blobs-0)
# -----------------------------------------------------------------------------


def test_scene_view_requires_numeric_yaw_and_pitch():
    with pytest.raises(ValidationError):
        TourEventPayload.model_validate(
            {"event_type": "scene_view", "scene_id": "s1", "event_data": {"yaw": "x"}}
        )
    with pytest.raises(ValidationError):
        TourEventPayload.model_validate({"event_type": "scene_view", "scene_id": "s1"})


def test_scene_view_with_yaw_and_pitch_is_accepted_and_coerced():
    payload = TourEventPayload.model_validate(
        {"event_type": "scene_view", "scene_id": "s1", "event_data": {"yaw": 12, "pitch": -3}}
    )
    assert payload.event_data["yaw"] == 12.0
    assert payload.event_type is ViewerEventType.scene_view


def test_viewer_cannot_post_like_or_unlike():
    for event in ("like", "unlike", "heatmap", "fullscreen"):
        with pytest.raises(ValidationError):
            TourEventPayload.model_validate({"event_type": event})


def test_legacy_tour_prefixed_event_names_are_rejected():
    with pytest.raises(ValidationError):
        TourEventPayload.model_validate({"event_type": "tour_view"})


# -----------------------------------------------------------------------------
# Capture (tours-web-5, tours-web-6, tours-web-7)
# -----------------------------------------------------------------------------


def test_capture_platform_accepts_web():
    assert CaptureDeviceInfo(platform="web").platform == "web"


def test_capture_platform_rejects_unknown_value():
    with pytest.raises(ValidationError):
        CaptureDeviceInfo(platform="windows")


def test_capture_patch_rejects_null_status():
    with pytest.raises(ValidationError):
        CaptureSessionUpdate.model_validate({"status": None})


def test_capture_patch_accepts_error_message_with_failed_status():
    body = CaptureSessionUpdate.model_validate(
        {"status": "failed", "error_message": "Upload failed"}
    )
    assert body.error_message == "Upload failed"


# -----------------------------------------------------------------------------
# AI jobs (be-tours-19, be-tours-20, tours-web-10, tours-web-11, tours-web-0)
# -----------------------------------------------------------------------------


def test_ai_job_type_enum_lists_the_written_types():
    written = {
        "analyze_scene",
        "analyze_scenes",
        "generate_description",
        "generate_descriptions",
        "generate_tour",
        "optimize_tour",
        "spatial_connect",
        "analyze_floor_plan",
        "suggest_hotspots",
        "suggest_tour_hotspots",
        "panorama_stitch",
    }
    assert {member.value for member in AIJobType} == written


def _job(**overrides) -> dict:
    base = {
        "id": "job-1",
        "job_type": "generate_tour",
        "status": "completed",
        "progress": 100,
        "created_at": _NOW,
        "updated_at": _NOW,
    }
    base.update(overrides)
    return base


def test_ai_job_unknown_type_maps_to_null():
    job = AIJobBase.model_validate(_job(job_type="legacy_tour_job"))
    assert job.job_type is None


def test_ai_job_status_is_the_enum_spelling():
    job = AIJobBase.model_validate(_job(status="cancelled"))
    assert job.status.value == "cancelled"
    with pytest.raises(ValidationError):
        AIJobBase.model_validate(_job(status="canceled"))


def test_ai_job_actual_duration_is_seconds_between_start_and_completion():
    job = AIJobBase.model_validate(_job(started_at=_NOW, completed_at=_NOW + timedelta(seconds=12)))
    assert job.model_dump(mode="json")["actual_duration"] == 12.0


def test_ai_job_actual_duration_is_null_until_complete():
    job = AIJobBase.model_validate(_job(status="processing", started_at=_NOW))
    assert job.model_dump(mode="json")["actual_duration"] is None


def test_generate_tour_result_must_carry_tour_and_scenes_keys():
    """tours-web-0: the wizard reads tour and scenes from the result."""
    with pytest.raises(ValidationError):
        validate_ai_result(
            "generate_tour", {"tour_id": "t1", "generated": {}, "created_hotspots": []}
        )


def test_generate_tour_result_round_trips_tour_and_scenes():
    tour = {
        "id": "t1",
        "user_id": 1,
        "title": "Flat",
        "status": "draft",
        "is_public": False,
        "visibility": "private",
        "is_featured": False,
        "view_count": 0,
        "like_count": 0,
        "share_count": 0,
        "created_at": _NOW.isoformat(),
        "updated_at": _NOW.isoformat(),
        "scene_count": 1,
    }
    scenes = [
        {
            "id": "s1",
            "title": "Kitchen",
            "image_url": "https://cdn.example.com/a.jpg",
            "hotspot_count": 0,
        }
    ]
    stored = validate_ai_result(
        "generate_tour",
        {"tour_id": "t1", "tour": tour, "scenes": scenes, "generated": [], "created_hotspots": []},
    )
    assert stored["tour"]["id"] == "t1"
    assert stored["scenes"][0]["id"] == "s1"


def test_spatial_summary_survives_result_validation_for_every_spatial_job_type():
    """A result key the model does not declare is dropped on the way into
    ai_jobs.result, and the review UI then silently shows nothing. This pins the
    whole summary, not just its presence."""
    summary = {
        "scene_count": 3,
        "link_count": 4,
        "rooms_without_links": ["bathroom"],
        "one_way_links": ["kitchen->hallway"],
        "unreachable_scenes": ["balcony"],
        "unmatched_openings": [
            {"scene_id": "kitchen", "leads_to_room_type": "garage", "label": "side door"}
        ],
        "unlinked_openings": [
            {"scene_id": "living_room", "leads_to_room_type": "hallway", "label": "stairs up"}
        ],
        "warnings": ["1 room(s) have no doorway links yet: bathroom"],
    }
    tour = {
        "id": "t1",
        "user_id": 1,
        "title": "Flat",
        "status": "draft",
        "is_public": False,
        "visibility": "private",
        "is_featured": False,
        "view_count": 0,
        "like_count": 0,
        "share_count": 0,
        "created_at": _NOW.isoformat(),
        "updated_at": _NOW.isoformat(),
        "scene_count": 3,
    }

    generated = validate_ai_result(
        "generate_tour",
        {"tour_id": "t1", "tour": tour, "scenes": [], "spatial_summary": summary},
    )
    assert generated["spatial_summary"] == summary

    optimized = validate_ai_result("optimize_tour", {"tour_id": "t1", "spatial_summary": summary})
    assert optimized["spatial_summary"] == summary

    connected = validate_ai_result(
        "spatial_connect", {"tour_id": "t1", "hotspots_created": 4, "spatial_summary": summary}
    )
    assert connected["spatial_summary"] == summary


def test_graph_summary_reports_only_keys_the_result_model_declares():
    """The summary is written straight into ai_jobs.result: a key the model does
    not declare would be dropped without an error. Catch that here, not in prod."""
    from app.schemas.tour import SpatialGraphSummary
    from app.services.tour_ai.spatial import graph_summary

    produced = set(graph_summary([]))
    declared = set(SpatialGraphSummary.model_fields)
    assert produced == declared


def test_spatial_summary_may_be_absent_when_linking_did_not_run():
    """A run without spatial linking carries null, so the client shows no report."""
    stored = validate_ai_result(
        "spatial_connect", {"tour_id": "t1", "hotspots_created": 0, "spatial_summary": None}
    )
    assert stored["spatial_summary"] is None


def test_unknown_job_type_has_no_result_schema():
    with pytest.raises(ValueError):
        validate_ai_result("not_a_job", {})


# -----------------------------------------------------------------------------
# Custom domains (be-tours-21, tours-web-35)
# -----------------------------------------------------------------------------


def test_custom_domain_ssl_status_is_the_enum():
    base = {
        "id": "d1",
        "user_id": 1,
        "domain": "tours.example.com",
        "verification_status": "pending",
        "created_at": _NOW,
        "updated_at": _NOW,
    }
    assert (
        CustomDomainResponse.model_validate({**base, "ssl_status": "pending"}).ssl_status.value
        == "pending"
    )
    with pytest.raises(ValidationError):
        CustomDomainResponse.model_validate({**base, "ssl_status": "provisioning"})


# -----------------------------------------------------------------------------
# Main scene id is explicit (tours-mobile-1)
# -----------------------------------------------------------------------------


def test_main_scene_id_is_the_lowest_order_index():
    from app.schemas.tour import TourWithScenes

    tour = TourModel(
        id="t1",
        user_id=1,
        title="T",
        status="draft",
        visibility="private",
        is_public=False,
        view_count=0,
        like_count=0,
        share_count=0,
        is_featured=False,
        created_at=_NOW,
        updated_at=_NOW,
    )
    later = SceneModel(
        id="s-later",
        tour_id="t1",
        image_url="https://c/a.jpg",
        order_index=1,
        is_processed=True,
        created_at=_NOW,
        updated_at=_NOW,
    )
    main = SceneModel(
        id="s-main",
        tour_id="t1",
        image_url="https://c/b.jpg",
        order_index=0,
        is_processed=True,
        created_at=_NOW,
        updated_at=_NOW,
    )
    tour.scenes = [later, main]
    payload = TourWithScenes.model_validate(tour).model_dump(mode="json")
    assert payload["main_scene_id"] == "s-main"


def test_main_scene_id_is_null_without_scenes():
    from app.schemas.tour import TourWithScenes

    tour = TourModel(
        id="t2",
        user_id=1,
        title="T",
        status="draft",
        visibility="private",
        is_public=False,
        view_count=0,
        like_count=0,
        share_count=0,
        is_featured=False,
        created_at=_NOW,
        updated_at=_NOW,
    )
    tour.scenes = []
    assert TourWithScenes.model_validate(tour).main_scene_id is None
