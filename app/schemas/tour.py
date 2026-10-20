"""Pydantic schemas for the 360 virtual tour API.

One module holds every tour schema. Each JSON column has one schema:

- ``TourSettings`` (``tours.settings``) and ``TourBrandingSettings`` (inside it)
- ``SceneMetadata`` (``scenes.scene_metadata``)
- ``HotspotPosition`` (``hotspots.position``)
- the hotspot content models, one per hotspot type (``hotspots.content``)
- the AI job result models (``ai_jobs.result``)

Write bodies are ``WriteModel`` (unknown keys give 422). PATCH bodies are
``PatchModel``: a key the client omits is unchanged, and an explicit null
clears a nullable field. Stored JSON is validated on write. Response models read
stored JSON with ``read_json``, which drops keys the model does not declare and
returns null (with a log line) for a row that still fails, so one legacy row
cannot fail a whole tour response.
"""

from __future__ import annotations

import datetime
import math
from collections.abc import Sequence
from enum import Enum
from typing import Annotated, Any, Literal, cast
from urllib.parse import parse_qs, urlparse

import bleach  # type: ignore[import-untyped,unused-ignore]  # bleach ships no type stubs
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    ValidationInfo,
    ValidatorFunctionWrapHandler,
    WrapValidator,
    computed_field,
    field_validator,
    model_validator,
)

from app.core.logging import get_logger
from app.models.enums import (
    AIJobStatus,
    AIJobType,
    HotspotType,
    TourStatus,
    TourVisibility,
)
from app.schemas.base import NotNullable, PatchModel, UtcDateTime, WriteModel

logger = get_logger(__name__)

# Allowed hosts for user-supplied frame/scene image URLs (SSRF guard).
ALLOWED_FRAME_HOSTS = {"res.cloudinary.com"}

# The one list of schemes a hotspot link may use. The client keeps its own copy.
ALLOWED_LINK_SCHEMES = frozenset({"http", "https", "mailto", "tel"})


class ViewerEventType(str, Enum):
    """Event types a viewer may post to POST /public/tours/{id}/events.

    The values are the TourEventType values. like and unlike come from the like
    routes only. view is not here: GET /public/tours/{id} counts views, with its
    own dedupe window. The spec lists only these values.
    """

    scene_view = "scene_view"
    hotspot_click = "hotspot_click"
    share = "share"
    fullscreen_enter = "fullscreen_enter"
    fullscreen_exit = "fullscreen_exit"
    vr_enter = "vr_enter"
    vr_exit = "vr_exit"
    session_start = "session_start"
    session_end = "session_end"
    session_duration = "session_duration"


_HOTSPOT_HTML_ALLOWED_TAGS = [
    "p",
    "br",
    "strong",
    "em",
    "u",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "blockquote",
    "ul",
    "ol",
    "li",
    "a",
    "img",
    "div",
    "span",
    "code",
    "pre",
]
_HOTSPOT_HTML_ALLOWED_ATTRIBUTES: dict[str, list[str]] = {
    "a": ["href", "title", "target", "rel"],
    "img": ["src", "alt", "width", "height"],
}
_HOTSPOT_HTML_ALLOWED_PROTOCOLS = sorted(ALLOWED_LINK_SCHEMES)


class JsonModel(BaseModel):
    """Base for models that describe a JSON column. Unknown keys give 422 on write."""

    model_config = ConfigDict(extra="forbid")


# ====================
# Read helpers for stored JSON
# ====================


def _drop_undeclared_keys(model: type[BaseModel], value: Any) -> Any:
    """Drop top-level keys that the model does not declare (legacy stored JSON)."""
    if isinstance(value, dict):
        return {key: item for key, item in value.items() if key in model.model_fields}
    return value


def read_json(model: type[BaseModel]) -> WrapValidator:
    """Validate a stored JSON column on read. A row that still fails becomes null."""

    def _check(value: Any, handler: ValidatorFunctionWrapHandler, info: ValidationInfo) -> Any:
        if value is None:
            return None
        try:
            return model.model_validate(_drop_undeclared_keys(model, value))
        except ValidationError:
            logger.warning(
                "Stored %s JSON failed validation (field %s); returning null",
                model.__name__,
                info.field_name,
            )
            return None

    return WrapValidator(_check)


def is_allowed_link_url(value: str) -> bool:
    """True when the URL uses a scheme in ALLOWED_LINK_SCHEMES and has a target."""
    try:
        parsed = urlparse(value)
    except ValueError:
        return False
    if parsed.scheme not in ALLOWED_LINK_SCHEMES:
        return False
    if parsed.scheme in {"http", "https"}:
        return bool(parsed.netloc)
    return bool(parsed.path or parsed.netloc)


def _is_http_url(value: str) -> bool:
    try:
        parsed = urlparse(value)
    except ValueError:
        return False
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _sanitize_hotspot_html(value: str) -> str:
    return str(
        bleach.clean(
            value,
            tags=_HOTSPOT_HTML_ALLOWED_TAGS,
            attributes=_HOTSPOT_HTML_ALLOWED_ATTRIBUTES,
            protocols=_HOTSPOT_HTML_ALLOWED_PROTOCOLS,
            strip=True,
        )
    )


def _extract_youtube_id(url: str) -> str | None:
    try:
        parsed = urlparse(url)
    except ValueError:
        return None
    host = (parsed.hostname or "").lower()
    if host == "youtu.be":
        return parsed.path.lstrip("/") or None
    if host.endswith("youtube.com"):
        if parsed.path == "/watch":
            return (parse_qs(parsed.query).get("v", [None])[0]) or None
        if parsed.path.startswith(("/embed/", "/shorts/")):
            parts = parsed.path.strip("/").split("/")
            if len(parts) >= 2:
                return parts[1] or None
    return None


def _extract_vimeo_id(url: str) -> str | None:
    try:
        parsed = urlparse(url)
    except ValueError:
        return None
    if not (parsed.hostname or "").lower().endswith("vimeo.com"):
        return None
    parts = [part for part in parsed.path.split("/") if part]
    if not parts:
        return None
    if parts[0] == "video" and len(parts) >= 2:
        return parts[1] if parts[1].isdigit() else None
    return parts[0] if parts[0].isdigit() else None


# ====================
# Tour settings and branding (tours.settings)
# ====================


class TourBrandingSettings(JsonModel):
    """Branding settings for a tour. Stored only in tours.settings.branding."""

    logo_url: str | None = Field(default=None, max_length=500)
    primary_color: str | None = Field(default=None, max_length=32)
    secondary_color: str | None = Field(default=None, max_length=32)
    accent_color: str | None = Field(default=None, max_length=32)
    text_color: str | None = Field(default=None, max_length=32)
    background_color: str | None = Field(default=None, max_length=32)
    font_family: str | None = Field(default=None, max_length=100)
    button_style: Literal["rounded", "square", "pill"] | None = None
    show_watermark: bool | None = True
    watermark_position: Literal["bottom-left", "bottom-right", "top-left", "top-right"] | None = (
        None
    )
    custom_css: str | None = Field(default=None, max_length=10000)


class TourInitialView(JsonModel):
    yaw: float = Field(default=0.0, ge=-180, le=180)
    pitch: float = Field(default=0.0, ge=-90, le=90)


class TourSettings(JsonModel):
    """Tour configuration (tours.settings). Floor plans live in the floor_plans table only."""

    auto_rotate: bool | None = False
    auto_rotate_speed: float | None = Field(default=1.0, ge=0.1, le=10.0)
    initial_scene_id: str | None = Field(default=None, max_length=36)
    initial_view: TourInitialView | None = None
    show_navbar: bool | None = True
    enable_fullscreen: bool | None = True
    enable_vr: bool | None = True
    enable_gyroscope: bool | None = True
    gyroscope_auto_start: bool | None = False
    branding: TourBrandingSettings | None = None


# ====================
# Floor plans (floor_plans table, the only source)
# ====================


class FloorPlanMarker(BaseModel):
    """Marker on a floor plan that links to a scene."""

    scene_id: str
    x: float = Field(..., ge=0, le=100)
    y: float = Field(..., ge=0, le=100)
    label: str | None = None


class FloorPlanMarkerIn(WriteModel):
    """Marker in a write body (unknown keys give 422). Stored markers use FloorPlanMarker."""

    scene_id: str = Field(..., max_length=36)
    x: float = Field(..., ge=0, le=100)
    y: float = Field(..., ge=0, le=100)
    label: str | None = Field(default=None, max_length=255)


class FloorPlanCreate(WriteModel):
    """Schema for creating a floor plan."""

    name: str = Field(..., min_length=1, max_length=255)
    image_url: str = Field(..., min_length=1, max_length=512)
    floor_number: int = Field(default=1, ge=1)
    markers: list[FloorPlanMarkerIn] = Field(default_factory=list)


class FloorPlanUpdate(PatchModel):
    """Schema for updating a floor plan. Every field is NOT NULL, so null is rejected."""

    name: Annotated[str | None, NotNullable] = Field(default=None, min_length=1, max_length=255)
    image_url: Annotated[str | None, NotNullable] = Field(
        default=None, min_length=1, max_length=512
    )
    floor_number: Annotated[int | None, NotNullable] = Field(default=None, ge=1)
    markers: Annotated[list[FloorPlanMarkerIn] | None, NotNullable] = None


class FloorPlanResponse(BaseModel):
    """Response schema for a floor plan. A stored marker that fails FloorPlanMarker is dropped."""

    id: str
    tour_id: str
    name: str
    image_url: str
    floor_number: int
    markers: list[FloorPlanMarker] = Field(default_factory=list)
    created_at: UtcDateTime
    updated_at: UtcDateTime

    model_config = ConfigDict(from_attributes=True)

    @field_validator("markers", mode="before")
    @classmethod
    def _valid_markers_only(cls, value: Any) -> Any:
        """Keep the stored markers that validate. Log and drop the rest, so one row cannot fail the plan."""
        if not isinstance(value, list):
            return []
        kept: list[FloorPlanMarker] = []
        for item in value:
            try:
                kept.append(FloorPlanMarker.model_validate(item))
            except ValidationError:
                logger.warning("Stored floor plan marker failed validation; dropped")
        return kept


# ====================
# Hotspot position and content (hotspots.position, hotspots.content)
# ====================


class HotspotPosition(JsonModel):
    """Position of a hotspot on the panorama."""

    yaw: float = Field(..., ge=-180, le=180, description="Horizontal angle in degrees")
    pitch: float = Field(..., ge=-90, le=90, description="Vertical angle in degrees")
    radius: float | None = Field(
        default=None, gt=0, description="Optional radius for interaction area"
    )


class HotspotPositionUpdate(WriteModel):
    """Body for PUT /hotspots/{id}/position."""

    yaw: float = Field(..., ge=-180, le=180)
    pitch: float = Field(..., ge=-90, le=90)


class NavigationContent(JsonModel):
    """Navigation hotspots store no content. The target is target_scene_id."""


class LinkContent(JsonModel):
    url: str = Field(..., max_length=2048)
    target: Literal["_blank", "_self"] = "_blank"
    label: str | None = Field(default=None, max_length=255)

    @field_validator("url")
    @classmethod
    def _scheme_allowed(cls, value: str) -> str:
        if not is_allowed_link_url(value):
            raise ValueError("Link URL must use one of: " + ", ".join(sorted(ALLOWED_LINK_SCHEMES)))
        return value


class AudioContent(JsonModel):
    audio_url: str = Field(..., max_length=2048)
    autoplay: bool | None = None
    loop: bool | None = None

    @field_validator("audio_url")
    @classmethod
    def _http_only(cls, value: str) -> str:
        if not _is_http_url(value):
            raise ValueError("Audio URL must be an http(s) URL")
        return value


class VideoContent(JsonModel):
    """Exactly one of youtube_id, vimeo_id or video_url. A YouTube or Vimeo video_url is normalized to its id."""

    youtube_id: str | None = Field(default=None, max_length=64)
    vimeo_id: str | None = Field(default=None, max_length=32)
    video_url: str | None = Field(default=None, max_length=2048)
    poster_url: str | None = Field(default=None, max_length=2048)
    autoplay: bool | None = None
    muted: bool | None = None
    loop: bool | None = None

    @model_validator(mode="before")
    @classmethod
    def _derive_ids(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        data = dict(data)
        video_url = data.get("video_url")
        if isinstance(video_url, str) and not data.get("youtube_id") and not data.get("vimeo_id"):
            youtube_id = _extract_youtube_id(video_url)
            vimeo_id = None if youtube_id else _extract_vimeo_id(video_url)
            if youtube_id or vimeo_id:
                data.pop("video_url")
                if youtube_id:
                    data["youtube_id"] = youtube_id
                else:
                    data["vimeo_id"] = vimeo_id
        return data

    @model_validator(mode="after")
    def _one_source(self) -> VideoContent:
        sources = [self.youtube_id, self.vimeo_id, self.video_url]
        if sum(1 for source in sources if source) != 1:
            raise ValueError("Video content needs exactly one of youtube_id, vimeo_id or video_url")
        if self.video_url is not None and not _is_http_url(self.video_url):
            raise ValueError("Video URL must be an http(s) URL")
        if self.poster_url is not None and not _is_http_url(self.poster_url):
            raise ValueError("Video poster_url must be an http(s) URL")
        return self


class InfoContent(JsonModel):
    text: str | None = Field(default=None, max_length=10000)
    html: str | None = Field(default=None, max_length=20000)
    image_url: str | None = Field(default=None, max_length=2048)

    @field_validator("html")
    @classmethod
    def _sanitize(cls, value: str | None) -> str | None:
        return _sanitize_hotspot_html(value) if value is not None else None

    @field_validator("image_url")
    @classmethod
    def _http_only(cls, value: str | None) -> str | None:
        if value is not None and not _is_http_url(value):
            raise ValueError("Info image_url must be an http(s) URL")
        return value


class CustomContent(JsonModel):
    html: str | None = Field(default=None, max_length=20000)
    component_key: str | None = Field(default=None, max_length=100)
    props: dict[str, Any] | None = None

    @field_validator("html")
    @classmethod
    def _sanitize(cls, value: str | None) -> str | None:
        return _sanitize_hotspot_html(value) if value is not None else None


HOTSPOT_CONTENT_MODELS: dict[HotspotType, type[JsonModel]] = {
    HotspotType.navigation: NavigationContent,
    HotspotType.link: LinkContent,
    HotspotType.audio: AudioContent,
    HotspotType.video: VideoContent,
    HotspotType.info: InfoContent,
    HotspotType.custom: CustomContent,
}

HotspotContentIn = (
    NavigationContent | LinkContent | AudioContent | VideoContent | InfoContent | CustomContent
)


def content_for_type(hotspot_type: HotspotType, raw: Any) -> JsonModel | None:
    """Validate hotspot content against its type. Returns the typed model, or None when empty.

    Raises ``ValidationError`` (422) when the content does not fit the type.
    """
    model = HOTSPOT_CONTENT_MODELS[HotspotType(hotspot_type)]
    if raw is None:
        raw = {}
    if isinstance(raw, JsonModel):
        raw = raw.model_dump(exclude_unset=True)
    if not isinstance(raw, dict):
        raise ValueError("Hotspot content must be an object")
    typed = model.model_validate(raw)
    if not typed.model_dump(exclude_none=True):
        return None
    return typed


def content_to_storage(hotspot_type: HotspotType, raw: Any) -> dict[str, Any] | None:
    """Validate hotspot content and return the dict stored in hotspots.content."""
    typed = content_for_type(hotspot_type, raw)
    return typed.model_dump(exclude_none=True) if typed is not None else None


class HotspotBase(WriteModel):
    """Shared hotspot fields for the create body (unknown keys give 422)."""

    type: HotspotType = HotspotType.info
    position: HotspotPosition
    target_scene_id: str | None = Field(default=None, max_length=36)
    title: str | None = Field(default=None, max_length=255)
    description: str | None = Field(default=None, max_length=2000)
    icon: str | None = Field(default=None, max_length=50)
    icon_name: str | None = Field(default=None, max_length=100)
    icon_color: str | None = Field(default=None, pattern=r"^#[0-9A-Fa-f]{6}$")
    icon_size: int = Field(default=32, ge=16, le=100)
    custom_data: dict[str, Any] = Field(default_factory=dict)


class HotspotCreate(HotspotBase):
    """Schema for creating a hotspot. content is validated against type."""

    content: HotspotContentIn | None = None

    @model_validator(mode="before")
    @classmethod
    def _typed_content(cls, data: Any) -> Any:
        if isinstance(data, dict) and data.get("content") is not None:
            hotspot_type = data.get("type") or HotspotType.info
            typed = content_for_type(HotspotType(hotspot_type), data["content"])
            data = {**data, "content": typed}
        return data


class HotspotUpdate(PatchModel):
    """Schema for updating a hotspot. content is validated against the effective type in the service."""

    type: Annotated[HotspotType | None, NotNullable] = None
    position: Annotated[HotspotPosition | None, NotNullable] = None
    target_scene_id: str | None = Field(default=None, max_length=36)
    title: str | None = Field(default=None, max_length=255)
    description: str | None = Field(default=None, max_length=2000)
    icon: str | None = Field(default=None, max_length=50)
    icon_name: str | None = Field(default=None, max_length=100)
    icon_color: str | None = Field(default=None, pattern=r"^#[0-9A-Fa-f]{6}$")
    icon_size: Annotated[int | None, NotNullable] = Field(default=None, ge=16, le=100)
    content: dict[str, Any] | None = None
    custom_data: Annotated[dict[str, Any] | None, NotNullable] = None
    is_active: Annotated[bool | None, NotNullable] = None


class Hotspot(BaseModel):
    """Hotspot response schema."""

    id: str
    scene_id: str
    type: HotspotType
    position: Annotated[HotspotPosition | None, read_json(HotspotPosition)] = None
    target_scene_id: str | None = None
    title: str | None = None
    description: str | None = None
    icon: str | None = None
    icon_name: str | None = None
    icon_color: str | None = None
    icon_size: int
    content: HotspotContentIn | None = None
    custom_data: dict[str, Any] = Field(default_factory=dict)
    order_index: int
    is_active: bool
    created_at: UtcDateTime
    updated_at: UtcDateTime

    model_config = ConfigDict(from_attributes=True)

    @field_validator("custom_data", mode="before")
    @classmethod
    def _custom_data_not_null(cls, value: Any) -> Any:
        """Rows written before custom_data had a default may hold null. Read them as {}."""
        return {} if value is None else value

    @field_validator("content", mode="wrap")
    @classmethod
    def _content_by_type(
        cls, value: Any, handler: ValidatorFunctionWrapHandler, info: ValidationInfo
    ) -> Any:
        hotspot_type = info.data.get("type")
        if value is None or hotspot_type is None:
            return None
        try:
            return content_for_type(HotspotType(hotspot_type), _content_source(value))
        except ValidationError:
            logger.warning(
                "Stored hotspot content failed validation (type %s); returning null", hotspot_type
            )
            return None


def _content_source(value: Any) -> Any:
    """Strip keys the content models do not declare, so legacy rows still validate."""
    if isinstance(value, dict):
        return {key: item for key, item in value.items() if key != "kind"}
    return value


# ====================
# Scene metadata (scenes.scene_metadata)
# ====================


class SceneInitialView(JsonModel):
    """Initial camera view for a scene."""

    yaw: float = Field(default=0.0, ge=-180, le=180)
    pitch: float = Field(default=0.0, ge=-90, le=90)
    zoom: float | None = Field(
        default=50,
        ge=0,
        le=100,
        description="Zoom level from 0 (widest) to 100 (closest), the Photo Sphere Viewer zoomLevel scale.",
    )


class SceneCameraSettings(JsonModel):
    """Camera settings for a scene."""

    fov: float | None = Field(default=70, ge=10, le=150)
    min_fov: float | None = Field(default=30, ge=10, le=150)
    max_fov: float | None = Field(default=90, ge=10, le=150)


class SceneGps(JsonModel):
    latitude: float = Field(..., ge=-90, le=90)
    longitude: float = Field(..., ge=-180, le=180)


class SceneDimensions(JsonModel):
    width: int = Field(..., ge=0)
    height: int = Field(..., ge=0)


class SceneMetadata(JsonModel):
    """Metadata for a scene. The image pipeline and the AI services write the server-owned keys."""

    initial_view: SceneInitialView | None = None
    camera: SceneCameraSettings | None = None
    gps: SceneGps | None = None
    exif: dict[str, Any] | None = None
    dimensions: SceneDimensions | None = None
    is_panorama: bool | None = None
    room_type: str | None = Field(default=None, max_length=100)
    caption: str | None = Field(default=None, max_length=500)
    narration_script: str | None = Field(default=None, max_length=5000)


def ai_hotspot_position(yaw: Any, pitch: Any) -> dict[str, float | None]:
    """Position for a hotspot that an AI worker wrote. Angles are clamped to the HotspotPosition range.

    A value that is not a finite number becomes 0, so one bad model output never fails a write.
    """

    def _angle(value: Any, limit: float) -> float:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return 0.0
        if not math.isfinite(number):
            return 0.0
        return max(-limit, min(limit, number))

    return {"yaw": _angle(yaw, 180.0), "pitch": _angle(pitch, 90.0), "radius": None}


def merge_ai_scene_metadata(
    stored: dict[str, Any] | None, updates: dict[str, Any]
) -> dict[str, Any]:
    """Merge AI output into scene metadata and return the JSON to store.

    Keys that SceneMetadata does not declare are dropped. Each remaining key is kept only
    when the result still validates as SceneMetadata, so one bad value does not drop the
    rest. Legacy stored metadata that does not validate is returned as it was.
    """
    base: dict[str, Any] = dict(_drop_undeclared_keys(SceneMetadata, dict(stored or {})))
    kept = dict(base)
    for key, value in _drop_undeclared_keys(SceneMetadata, dict(updates)).items():
        candidate = {**kept, key: value}
        try:
            SceneMetadata.model_validate(candidate)
        except ValidationError:
            logger.warning("Dropped AI scene metadata key %s: failed validation", key)
            continue
        kept = candidate
    try:
        return SceneMetadata.model_validate(kept).model_dump(exclude_none=True)
    except ValidationError:
        return base


# ====================
# Scene schemas
# ====================


class SceneCreate(WriteModel):
    """Schema for creating a scene. order_index is server-owned: the new scene goes last."""

    title: str | None = Field(default=None, max_length=255)
    description: str | None = Field(default=None, max_length=2000)
    image_url: str = Field(..., max_length=500)
    thumbnail_url: str | None = Field(default=None, max_length=500)
    scene_metadata: SceneMetadata | None = None


class SceneUpdate(PatchModel):
    """Schema for updating a scene. scene_metadata is deep-merged, and null clears it."""

    title: str | None = Field(default=None, max_length=255)
    description: str | None = Field(default=None, max_length=2000)
    image_url: Annotated[str | None, NotNullable] = Field(default=None, max_length=500)
    thumbnail_url: str | None = Field(default=None, max_length=500)
    scene_metadata: dict[str, Any] | None = None


class SceneReorder(WriteModel):
    """Schema for reordering scenes."""

    scene_ids: list[str] = Field(..., min_length=1)


class Scene(BaseModel):
    """Scene response schema."""

    id: str
    tour_id: str
    title: str | None = None
    description: str | None = None
    image_url: str
    thumbnail_url: str | None = None
    vr_url: str | None = None
    order_index: int
    scene_metadata: Annotated[SceneMetadata | None, read_json(SceneMetadata)] = None
    is_processed: bool
    processing_error: str | None = None
    created_at: UtcDateTime
    updated_at: UtcDateTime
    hotspots: list[Hotspot] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class PublicSceneMetadata(BaseModel):
    """Scene metadata a viewer may see. EXIF (camera make, GPS, capture time) is left out."""

    initial_view: SceneInitialView | None = None
    camera: SceneCameraSettings | None = None
    dimensions: SceneDimensions | None = None
    is_panorama: bool | None = None
    room_type: str | None = None
    caption: str | None = None
    narration_script: str | None = None


class PublicScene(BaseModel):
    """Scene as an anonymous viewer sees it. No processing_error and no EXIF."""

    id: str
    tour_id: str
    title: str | None = None
    description: str | None = None
    image_url: str
    thumbnail_url: str | None = None
    vr_url: str | None = None
    order_index: int
    scene_metadata: Annotated[PublicSceneMetadata | None, read_json(PublicSceneMetadata)] = None
    is_processed: bool
    created_at: UtcDateTime
    updated_at: UtcDateTime
    hotspots: list[Hotspot] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


# ====================
# Tour schemas
# ====================


class TourCreate(WriteModel):
    """Schema for creating a tour. New tours are drafts. status changes only through publish."""

    title: str = Field(..., min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=5000)
    is_public: bool | None = False  # Deprecated: Use visibility instead
    visibility: TourVisibility = TourVisibility.private
    settings: TourSettings | None = None

    model_config = ConfigDict(extra="forbid", json_schema_extra={"title": "TourCreate"})


class TourUpdate(PatchModel):
    """Schema for updating a tour. status and is_featured are not writable here."""

    title: Annotated[str | None, NotNullable] = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=5000)
    is_public: Annotated[bool | None, NotNullable] = None  # Deprecated: Use visibility instead
    visibility: Annotated[TourVisibility | None, NotNullable] = None
    settings: TourSettings | None = None
    thumbnail_url: str | None = Field(default=None, max_length=500)


class TourCore(BaseModel):
    """Tour fields that every viewer may see. Owner-only fields are added by Tour."""

    id: str
    title: str
    description: str | None = None
    status: TourStatus
    is_public: bool
    visibility: TourVisibility
    short_code: str | None = None
    is_featured: bool
    view_count: int
    like_count: int
    share_count: int
    settings: Annotated[TourSettings | None, read_json(TourSettings)] = None
    thumbnail_url: str | None = None
    published_at: UtcDateTime | None = None
    archived_at: UtcDateTime | None = None
    created_at: UtcDateTime
    updated_at: UtcDateTime
    deleted_at: UtcDateTime | None = None
    scene_count: int | None = None

    model_config = ConfigDict(from_attributes=True)


class Tour(TourCore):
    """Tour response schema for the owner. Adds the internal user_id."""

    user_id: int


def _main_scene_id(scenes: Sequence[Scene | PublicScene]) -> str | None:
    if not scenes:
        return None
    return min(scenes, key=lambda scene: (scene.order_index, scene.id)).id


class TourWithScenes(Tour):
    """Tour with scenes and floor plans (owner detail shape).

    main_scene_id is the scene with the lowest order_index, or null when the tour has no scenes.
    Clients read it instead of assuming a fixed position.
    """

    scenes: list[Scene] = Field(default_factory=list)
    floor_plans: list[FloorPlanResponse] = Field(default_factory=list)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def main_scene_id(self) -> str | None:
        return _main_scene_id(self.scenes)


class PublicTourWithScenes(TourCore):
    """Public tour detail. Same as TourWithScenes, without the owner's user_id.

    Scenes are PublicScene: no processing_error and no EXIF. Inactive hotspots are removed
    by the service (tour_service.public_tour_view).
    """

    scenes: list[PublicScene] = Field(default_factory=list)
    floor_plans: list[FloorPlanResponse] = Field(default_factory=list)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def main_scene_id(self) -> str | None:
        return _main_scene_id(self.scenes)


# ====================
# Analytics schemas
# ====================


class DeviceBreakdown(BaseModel):
    """Device type breakdown for analytics."""

    desktop: int = 0
    mobile: int = 0
    tablet: int = 0
    vr: int = 0


class DailyView(BaseModel):
    """Daily view count for analytics. date is a calendar day (YYYY-MM-DD)."""

    date: datetime.date
    views: int


class TourEventPayload(WriteModel):
    """Body for POST /public/tours/{id}/events."""

    event_type: ViewerEventType
    scene_id: str | None = Field(default=None, max_length=36)
    hotspot_id: str | None = Field(default=None, max_length=36)
    session_id: str | None = Field(default=None, max_length=255)
    event_data: dict[str, Any] | None = None

    @model_validator(mode="after")
    def _check(self) -> TourEventPayload:
        if self.event_type == ViewerEventType.scene_view:
            if not self.scene_id:
                raise ValueError("scene_view events require scene_id")
            data = self.event_data or {}
            yaw, pitch = data.get("yaw"), data.get("pitch")
            if not _is_number(yaw, -180, 180) or not _is_number(pitch, -90, 90):
                raise ValueError(
                    "scene_view events require numeric yaw (-180..180) and pitch (-90..90)"
                )
            self.event_data = {
                **data,
                "yaw": float(cast(float, yaw)),
                "pitch": float(cast(float, pitch)),
            }
        return self


def _is_number(value: Any, low: float, high: float) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    return low <= float(value) <= high


class HeatmapPoint(BaseModel):
    """Aggregated view-direction point. One point per 5-degree cell per scene."""

    scene_id: str
    yaw: float
    pitch: float
    intensity: float = Field(ge=0, le=1)
    count: int = Field(ge=1)


class TourLikeCount(BaseModel):
    """Like count after a like or unlike."""

    like_count: int


class TourHeatmapData(BaseModel):
    """Heatmap response: a flat list of points, each with its scene_id."""

    tour_id: str
    heatmap: list[HeatmapPoint] = Field(default_factory=list)


class TourAnalytics(BaseModel):
    """Analytics data for a tour."""

    tour_id: str
    total_views: int = 0
    unique_views: int = 0
    total_likes: int = 0
    total_shares: int = 0
    avg_session_duration: float = 0.0
    scene_views: dict[str, int] = Field(default_factory=dict)
    hotspot_clicks: dict[str, int] = Field(default_factory=dict)
    share_breakdown: dict[str, int] = Field(default_factory=dict)
    session_durations: list[float] = Field(default_factory=list)
    device_breakdown: DeviceBreakdown = Field(default_factory=DeviceBreakdown)
    country_breakdown: dict[str, int] = Field(default_factory=dict)
    daily_views: list[DailyView] = Field(default_factory=list)


class DashboardStats(BaseModel):
    """Dashboard statistics for a user."""

    total_tours: int = 0
    published_tours: int = 0
    total_views: int = 0
    total_scenes: int = 0
    storage_used: int = 0  # bytes, sum of the user's media file sizes
    storage_limit: int = 0  # bytes, a product constant (TOUR_STORAGE_LIMIT_BYTES in analytics.py)


class RealtimeViewBucket(BaseModel):
    """View count for one 5-minute bucket of the last hour. timestamp is the bucket start (UTC)."""

    timestamp: UtcDateTime
    views: int


class DashboardRealtimeStats(BaseModel):
    """Realtime dashboard metrics."""

    active_sessions: int = 0
    views_last_hour: int = 0
    likes_last_hour: int = 0
    shares_last_hour: int = 0
    avg_session_duration: float = 0.0
    recent_views: list[RealtimeViewBucket] = Field(default_factory=list)


# ====================
# AI processing schemas
# ====================


def _known_job_type(value: Any) -> Any:
    """Map a stored job_type outside the AIJobType enum to null, and log it."""
    if value is None or isinstance(value, AIJobType):
        return value
    try:
        return AIJobType(value)
    except ValueError:
        logger.warning("Unknown ai_jobs.job_type %r; returning null", value)
        return None


class AIJobBase(BaseModel):
    """Base AI Job schema."""

    id: str
    job_type: Annotated[AIJobType | None, WrapValidator(lambda v, h: _known_job_type(v))]
    status: AIJobStatus
    progress: int
    tour_id: str | None = None
    scene_id: str | None = None
    error_message: str | None = None
    started_at: UtcDateTime | None = None
    completed_at: UtcDateTime | None = None
    created_at: UtcDateTime
    updated_at: UtcDateTime | None = None

    model_config = ConfigDict(from_attributes=True)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def actual_duration(self) -> float | None:
        """Seconds from start to completion, or null while the job is not complete."""
        if self.started_at is None or self.completed_at is None:
            return None
        return max((self.completed_at - self.started_at).total_seconds(), 0.0)


class AIJobResponse(BaseModel):
    """Response containing an AI job."""

    job: AIJobBase


class SceneFrameMetadata(WriteModel):
    """Per-frame capture metadata for the metadata-driven cloud stitcher.

    When omitted (legacy requests), the frame is assumed to carry no
    orientation and the legacy OpenCV path is used.
    """
    url: str
    yaw: float = Field(default=0.0, ge=-360, le=360, description="Degrees, east-positive")
    pitch: float = Field(default=0.0, ge=-90, le=90)
    roll: float = Field(default=0.0, ge=-180, le=180)
    target_index: int | None = Field(
        default=None,
        ge=0,
        le=63,
        description="Client bookkeeping only (capture-plan slot); the "
        "blend worker does not consume it.",
    )
    low_quality: bool = False

    @field_validator("url")
    @classmethod
    def validate_url(cls, v: str) -> str:
        parsed = urlparse(v)
        if parsed.scheme != "https" or parsed.hostname not in ALLOWED_FRAME_HOSTS:
            raise ValueError(
                f"frame urls must be https URLs from allowed hosts, got: {v}"
            )
        return v


class CameraProfileIn(WriteModel):
    """Camera geometry the capture was planned with (fallback 55x69 when
    absent — matches the mobile documented fallback profile). FOVs must be
    strictly below 180°: the pinhole projection is singular at 180°."""
    horizontal_fov: float = Field(default=55.0, gt=1, lt=180)
    vertical_fov: float = Field(default=69.0, gt=1, lt=180)


class SceneStitchRequest(WriteModel):
    """Request payload for cloud panorama stitching of captured frames.

    Backward compatible: `frame_urls` alone (legacy) still works — the
    worker falls back to the OpenCV path. When `frames` (with orientation
    metadata) is present, the metadata-driven equirect blend is used.
    """
    frame_urls: list[str] = Field(..., min_length=2, max_length=32)
    frames: list[SceneFrameMetadata] | None = Field(default=None, max_length=32)
    camera_profile: CameraProfileIn | None = None

    @field_validator("frame_urls")
    @classmethod
    def validate_frame_urls(cls, v: list[str]) -> list[str]:
        for url in v:
            parsed = urlparse(url)
            if parsed.scheme != "https" or parsed.hostname not in ALLOWED_FRAME_HOSTS:
                raise ValueError(f"frame_urls must be https URLs from allowed hosts, got: {url}")
        return v

    @field_validator("frames")
    @classmethod
    def validate_frames_count(cls, v: list[SceneFrameMetadata] | None) -> list[SceneFrameMetadata] | None:
        if v is not None and len(v) < 2:
            raise ValueError("frames must contain at least 2 entries")
        return v


class DescriptionOptions(WriteModel):
    """Options for AI description generation."""

    tone: str | None = Field(
        default="professional", pattern=r"^(professional|casual|luxury|friendly)$"
    )
    length: str | None = Field(default="medium", pattern=r"^(short|medium|long)$")
    include_features: bool | None = True
    target_audience: str | None = Field(default=None, max_length=255)


class TourGenerationSceneInput(WriteModel):
    """Scene input for AI-driven tour generation."""

    image_url: str = Field(..., max_length=500)
    thumbnail_url: str | None = Field(default=None, max_length=500)
    title: str | None = Field(default=None, max_length=255)
    description: str | None = Field(default=None, max_length=2000)
    scene_metadata: SceneMetadata | None = None


class TourGenerationRequest(WriteModel):
    """Request payload for AI tour generation. The tour is created as a draft."""

    title: str = Field(..., min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=5000)
    is_public: bool | None = False  # Deprecated: Use visibility instead
    visibility: TourVisibility = TourVisibility.private
    settings: TourSettings | None = None
    scenes: list[TourGenerationSceneInput] | None = None
    image_urls: list[str] | None = None
    generate_titles: bool | None = True
    generate_descriptions: bool | None = True
    suggest_hotspots: bool | None = False
    apply_to_scenes: bool | None = True
    language: str | None = Field(default=None, max_length=20)
    # When true, build Matterport-style spatial navigation: place each navigation
    # hotspot on the actual doorway leading to the correct adjacent room (vision +
    # graph), instead of naive consecutive-scene linking. See
    # app/services/tour_ai/spatial.py.
    spatial: bool | None = False


class TourGenerationResponse(BaseModel):
    """Response for AI tour generation."""

    job: AIJobBase
    tour_id: str
    scene_ids: list[str]


class TourOptimizationRequest(WriteModel):
    """Request payload for AI tour optimization."""

    goals: list[str] | None = None
    focus_areas: list[str] | None = None
    update_titles: bool | None = False
    update_descriptions: bool | None = False
    suggest_hotspots: bool | None = False
    language: str | None = Field(default=None, max_length=20)


# ====================
# AI job results (ai_jobs.result, one model per job type)
# ====================


class TourGenerationSceneSummary(BaseModel):
    """Scene summary inside a generate_tour result."""

    id: str
    title: str | None = None
    description: str | None = None
    image_url: str
    thumbnail_url: str | None = None
    hotspot_count: int = 0


class SpatialGraphSummary(BaseModel):
    """Linking-quality report of a spatial job (see `tour_ai.spatial.graph_summary`).

    Every field is declared: an undeclared key would be dropped on the way into
    `ai_jobs.result`, and the review UI would silently show nothing.
    """

    scene_count: int = Field(default=0, ge=0)
    link_count: int = Field(default=0, ge=0)
    rooms_without_links: list[str] = Field(default_factory=list)
    one_way_links: list[str] = Field(default_factory=list)
    unreachable_scenes: list[str] = Field(default_factory=list)
    unmatched_openings: list[dict[str, Any]] = Field(default_factory=list)
    unlinked_openings: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class TourGenerationResult(BaseModel):
    """ai_jobs.result for generate_tour. The wizard reads tour and scenes."""

    tour_id: str
    tour: Tour
    scenes: list[TourGenerationSceneSummary] = Field(default_factory=list)
    generated: list[dict[str, Any]] = Field(default_factory=list)
    created_hotspots: list[str] = Field(default_factory=list)
    # Null when the run did no spatial linking, so the wizard shows no report.
    spatial_summary: SpatialGraphSummary | None = None


class OptimizeTourResult(BaseModel):
    """ai_jobs.result for optimize_tour."""

    tour_id: str
    overview: dict[str, Any] = Field(default_factory=dict)
    overview_recommendations: list[Any] = Field(default_factory=list)
    scene_suggestions: list[Any] = Field(default_factory=list)
    created_hotspots: list[Any] = Field(default_factory=list)
    spatial_summary: SpatialGraphSummary | None = None


class FloorPlanAnalysisResult(BaseModel):
    """ai_jobs.result for analyze_floor_plan."""

    tour_id: str
    floor_plan_id: str
    markers_placed: int = Field(default=0, ge=0)
    rooms_detected: list[Any] = Field(default_factory=list)


class SpatialConnectResult(BaseModel):
    """ai_jobs.result for spatial_connect."""

    tour_id: str
    hotspots_created: int = Field(default=0, ge=0)
    spatial_summary: SpatialGraphSummary | None = None


class HotspotSuggestionsResult(BaseModel):
    """ai_jobs.result for suggest_hotspots and suggest_tour_hotspots."""

    hotspots: list[dict[str, Any]] = Field(default_factory=list)
    tour_id: str | None = None


class HotspotSuggestionDraft(BaseModel):
    """One AI hotspot suggestion, checked when the job completes. Invalid items are dropped.

    Angles are clamped to range. A navigation suggestion needs a target scene that is
    in the same tour and is not the source scene. An info suggestion has no target.
    Validation context: ``scene_ids`` (set of tour scene ids) and ``source_scene_id``.
    """

    model_config = ConfigDict(extra="ignore")

    type: Literal["navigation", "info"]
    yaw: float
    pitch: float
    target_scene_id: str | None = Field(default=None, max_length=36)
    suggested_title: str | None = Field(default=None, max_length=255)
    reasoning: str | None = Field(default=None, max_length=2000)
    confidence: float | None = Field(default=None, ge=0, le=1)

    @field_validator("yaw", "pitch", mode="after")
    @classmethod
    def _clamp_angle(cls, value: float, info: ValidationInfo) -> float:
        if not math.isfinite(value):
            raise ValueError(f"{info.field_name} must be a finite number")
        limit = 180.0 if info.field_name == "yaw" else 90.0
        return max(-limit, min(limit, value))

    @model_validator(mode="after")
    def _target_rules(self, info: ValidationInfo) -> HotspotSuggestionDraft:
        context = info.context or {}
        if self.type == "info":
            self.target_scene_id = None
            return self
        scene_ids: set[str] = context.get("scene_ids", set())
        source = context.get("source_scene_id")
        if not self.target_scene_id or self.target_scene_id not in scene_ids:
            raise ValueError("navigation suggestion needs a target scene in this tour")
        if self.target_scene_id == source:
            raise ValueError("navigation suggestion cannot target its own scene")
        return self


class SceneAnalysisJobResult(BaseModel):
    """ai_jobs.result for analyze_scene and analyze_scenes."""

    analysis: list[dict[str, Any]] = Field(default_factory=list)


class DescriptionJobResult(BaseModel):
    """ai_jobs.result for generate_description and generate_descriptions."""

    descriptions: list[dict[str, Any]] = Field(default_factory=list)


class StitchResult(BaseModel):
    """ai_jobs.result for panorama_stitch."""

    image_url: str
    width: int = Field(ge=0)
    height: int = Field(ge=0)
    # Quality report of the metadata-driven blend. Absent on the legacy OpenCV path.
    quality: dict[str, Any] | None = None


AI_RESULT_MODELS: dict[str, type[BaseModel]] = {
    AIJobType.generate_tour.value: TourGenerationResult,
    AIJobType.optimize_tour.value: OptimizeTourResult,
    AIJobType.analyze_floor_plan.value: FloorPlanAnalysisResult,
    AIJobType.spatial_connect.value: SpatialConnectResult,
    AIJobType.suggest_hotspots.value: HotspotSuggestionsResult,
    AIJobType.suggest_tour_hotspots.value: HotspotSuggestionsResult,
    AIJobType.analyze_scene.value: SceneAnalysisJobResult,
    AIJobType.analyze_scenes.value: SceneAnalysisJobResult,
    AIJobType.generate_description.value: DescriptionJobResult,
    AIJobType.generate_descriptions.value: DescriptionJobResult,
    AIJobType.panorama_stitch.value: StitchResult,
}


def validate_ai_result(job_type: str, result: dict[str, Any]) -> dict[str, Any]:
    """Validate a completed job's result against its job type. Returns the JSON form to store.

    Raises ``ValidationError`` when the result does not match the model for its type.
    """
    model = AI_RESULT_MODELS.get(job_type)
    if model is None:
        raise ValueError(f"No result schema for AI job type {job_type!r}")
    return model.model_validate(result).model_dump(mode="json")


def _result_by_job_type(
    value: Any, handler: ValidatorFunctionWrapHandler, info: ValidationInfo
) -> Any:
    """Validate a stored AI result against the model for its job type. Failure gives null."""
    if value is None:
        return None
    job_type = getattr(info.data.get("job"), "job_type", None)
    if not isinstance(job_type, AIJobType):
        logger.warning("Stored AI result has no known job_type; returning null")
        return None
    model = AI_RESULT_MODELS.get(job_type.value)
    if model is None:
        logger.warning("Stored AI result has no model for job_type %s; returning null", job_type)
        return None
    try:
        return model.model_validate(value)
    except ValidationError:
        logger.warning(
            "Stored AI result failed validation (job_type %s); returning null", job_type.value
        )
        return None


AIJobResultUnion = (
    TourGenerationResult
    | OptimizeTourResult
    | FloorPlanAnalysisResult
    | SpatialConnectResult
    | HotspotSuggestionsResult
    | SceneAnalysisJobResult
    | DescriptionJobResult
    | StitchResult
)


class AIJobStatusResponse(BaseModel):
    """Response containing AI job status with optional results.

    result is the model for job.job_type (AI_RESULT_MODELS). A stored result that fails
    that model is returned as null, with a log line, so one legacy row cannot fail the
    status response. OpenAPI shows the union of the per-type result models.
    """

    job: AIJobBase
    result: Annotated[AIJobResultUnion | None, WrapValidator(_result_by_job_type)] = None
