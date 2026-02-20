"""
Pydantic schemas for 360 Virtual Tour API.

These schemas define the request/response models for the tour management endpoints.
"""
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import AliasChoices, BaseModel, ConfigDict, Field

from app.models.enums import HotspotType, TourStatus, TourVisibility


# ====================
# Tour Settings Schema
# ====================

class TourBrandingSettings(BaseModel):
    """Branding settings for a tour."""
    logo_url: Optional[str] = None
    primary_color: Optional[str] = None
    secondary_color: Optional[str] = None
    accent_color: Optional[str] = None
    text_color: Optional[str] = None
    background_color: Optional[str] = None
    font_family: Optional[str] = None
    button_style: Optional[str] = None  # rounded | square | pill
    show_watermark: Optional[bool] = True
    watermark_position: Optional[str] = None  # bottom-left, bottom-right, top-left, top-right
    custom_css: Optional[str] = None


class FloorPlanMarker(BaseModel):
    """Marker data for floor plan hotspots."""
    scene_id: str
    x: float = Field(..., ge=0, le=100)
    y: float = Field(..., ge=0, le=100)
    label: Optional[str] = None


class FloorPlan(BaseModel):
    """Floor plan configuration stored in tour settings."""
    id: str
    name: str
    image_url: str
    floor_number: int = 1
    markers: List[FloorPlanMarker] = Field(default_factory=list)


# ====================
# Floor Plan CRUD Schemas (for dedicated table)
# ====================

class FloorPlanCreate(BaseModel):
    """Schema for creating a floor plan."""
    name: str = Field(..., min_length=1, max_length=255)
    image_url: str = Field(..., min_length=1)
    floor_number: int = Field(default=1, ge=1)
    markers: List[FloorPlanMarker] = Field(default_factory=list)


class FloorPlanUpdate(BaseModel):
    """Schema for updating a floor plan."""
    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    image_url: Optional[str] = None
    floor_number: Optional[int] = Field(default=None, ge=1)
    markers: Optional[List[FloorPlanMarker]] = None


class FloorPlanResponse(BaseModel):
    """Response schema for floor plan."""
    id: str
    tour_id: str
    name: str
    image_url: str
    floor_number: int
    markers: List[FloorPlanMarker]
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class TourSettings(BaseModel):
    """Tour configuration settings."""
    auto_rotate: Optional[bool] = False
    auto_rotate_speed: Optional[float] = Field(default=1.0, ge=0.1, le=10.0)
    initial_scene_id: Optional[str] = None
    initial_view: Optional[Dict[str, float]] = None  # {yaw, pitch}
    show_navbar: Optional[bool] = True
    enable_fullscreen: Optional[bool] = True
    enable_vr: Optional[bool] = True
    enable_gyroscope: Optional[bool] = True
    gyroscope_auto_start: Optional[bool] = False
    branding: Optional[TourBrandingSettings] = None
    floor_plans: Optional[List[FloorPlan]] = None


# ====================
# Hotspot Schemas
# ====================

class HotspotPosition(BaseModel):
    """Position of a hotspot in 3D space."""
    yaw: float = Field(..., ge=-180, le=180, description="Horizontal angle in degrees")
    pitch: float = Field(..., ge=-90, le=90, description="Vertical angle in degrees")
    radius: Optional[float] = Field(default=None, gt=0, description="Optional radius for interaction area")


class HotspotBase(BaseModel):
    """Base hotspot schema with common fields."""
    type: HotspotType = HotspotType.info
    position: HotspotPosition
    target_scene_id: Optional[str] = None
    title: Optional[str] = Field(default=None, max_length=255)
    description: Optional[str] = Field(default=None, max_length=2000)
    icon: Optional[str] = Field(default=None, max_length=50)
    icon_name: Optional[str] = Field(default=None, max_length=100)
    icon_color: Optional[str] = Field(default=None, pattern=r"^#[0-9A-Fa-f]{6}$")
    icon_size: Optional[int] = Field(default=None, ge=16, le=100)
    content: Optional[Dict[str, Any]] = None
    custom_data: Optional[Dict[str, Any]] = None


class HotspotCreate(HotspotBase):
    """Schema for creating a hotspot."""
    pass


class HotspotUpdate(BaseModel):
    """Schema for updating a hotspot."""
    type: Optional[HotspotType] = None
    position: Optional[HotspotPosition] = None
    target_scene_id: Optional[str] = None
    title: Optional[str] = Field(default=None, max_length=255)
    description: Optional[str] = Field(default=None, max_length=2000)
    icon: Optional[str] = Field(default=None, max_length=50)
    icon_name: Optional[str] = Field(default=None, max_length=100)
    icon_color: Optional[str] = Field(default=None, pattern=r"^#[0-9A-Fa-f]{6}$")
    icon_size: Optional[int] = Field(default=None, ge=16, le=100)
    content: Optional[Dict[str, Any]] = None
    custom_data: Optional[Dict[str, Any]] = None
    is_active: Optional[bool] = None


class HotspotPositionUpdate(BaseModel):
    """Schema for updating only hotspot position."""
    yaw: float = Field(..., ge=-180, le=180)
    pitch: float = Field(..., ge=-90, le=90)


class Hotspot(HotspotBase):
    """Hotspot response schema."""
    id: str
    scene_id: str
    order_index: int
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ====================
# Scene Metadata Schema
# ====================

class SceneInitialView(BaseModel):
    """Initial camera view for a scene."""
    yaw: float = 0
    pitch: float = 0
    zoom: Optional[float] = 50


class SceneCameraSettings(BaseModel):
    """Camera settings for a scene."""
    fov: Optional[float] = 70
    min_fov: Optional[float] = 30
    max_fov: Optional[float] = 90


class SceneMetadata(BaseModel):
    """Metadata for a scene."""
    initial_view: Optional[SceneInitialView] = None
    camera: Optional[SceneCameraSettings] = None
    gps: Optional[Dict[str, float]] = None  # {latitude, longitude}
    exif: Optional[Dict[str, Any]] = None


# ====================
# Scene Schemas
# ====================

class SceneBase(BaseModel):
    """Base scene schema with common fields."""
    title: Optional[str] = Field(default=None, max_length=255)
    description: Optional[str] = Field(default=None, max_length=2000)
    order_index: Optional[int] = Field(default=None, ge=0)
    metadata: Optional[SceneMetadata] = Field(
        default=None,
        alias="scene_metadata",
        validation_alias=AliasChoices("metadata", "scene_metadata"),
        serialization_alias="metadata",
    )

    model_config = ConfigDict(populate_by_name=True)


class SceneCreate(SceneBase):
    """Schema for creating a scene."""
    image_url: str = Field(..., max_length=500)
    thumbnail_url: Optional[str] = Field(default=None, max_length=500)


class SceneUpdate(SceneBase):
    """Schema for updating a scene."""
    image_url: Optional[str] = Field(default=None, max_length=500)
    thumbnail_url: Optional[str] = Field(default=None, max_length=500)


class SceneReorder(BaseModel):
    """Schema for reordering scenes."""
    scene_ids: List[str] = Field(..., min_length=1)


class Scene(SceneBase):
    """Scene response schema."""
    id: str
    tour_id: str
    image_url: str
    thumbnail_url: Optional[str] = None
    vr_url: Optional[str] = None
    is_processed: bool
    processing_error: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    hotspots: Optional[List[Hotspot]] = None

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


# ====================
# Tour Schemas
# ====================

class TourBase(BaseModel):
    """Base tour schema with common fields."""
    title: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = Field(default=None, max_length=5000)
    status: Optional[TourStatus] = TourStatus.draft
    is_public: Optional[bool] = False  # Deprecated: Use visibility instead
    visibility: Optional[TourVisibility] = TourVisibility.private
    settings: Optional[TourSettings] = None


class TourCreate(TourBase):
    """Schema for creating a tour."""
    pass


class TourUpdate(BaseModel):
    """Schema for updating a tour."""
    title: Optional[str] = Field(default=None, min_length=1, max_length=255)
    description: Optional[str] = Field(default=None, max_length=5000)
    status: Optional[TourStatus] = None
    is_public: Optional[bool] = None  # Deprecated: Use visibility instead
    visibility: Optional[TourVisibility] = None
    is_featured: Optional[bool] = None
    settings: Optional[TourSettings] = None
    thumbnail_url: Optional[str] = Field(default=None, max_length=500)


class Tour(TourBase):
    """Tour response schema."""
    id: str
    user_id: int
    is_featured: bool
    visibility: TourVisibility
    view_count: int
    like_count: int
    share_count: int
    thumbnail_url: Optional[str] = None
    published_at: Optional[datetime] = None
    archived_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime
    deleted_at: Optional[datetime] = None
    scenes: Optional[List[Scene]] = None
    scene_count: Optional[int] = None

    model_config = ConfigDict(from_attributes=True)


class TourWithScenes(Tour):
    """Tour with all scenes loaded."""
    scenes: List[Scene] = []


# ====================
# Analytics Schemas
# ====================

class DeviceBreakdown(BaseModel):
    """Device type breakdown for analytics."""
    desktop: int = 0
    mobile: int = 0
    tablet: int = 0
    vr: int = 0


class DailyView(BaseModel):
    """Daily view count for analytics."""
    date: str
    views: int


class TourEventPayload(BaseModel):
    """Payload for tracking tour analytics events."""
    event_type: str
    scene_id: Optional[str] = None
    hotspot_id: Optional[str] = None
    session_id: Optional[str] = None
    event_data: Optional[Dict[str, Any]] = None


class HeatmapPoint(BaseModel):
    """Heatmap point for viewer analytics."""
    scene_id: Optional[str] = None
    yaw: Optional[float] = None
    pitch: Optional[float] = None
    x: Optional[float] = None
    y: Optional[float] = None
    intensity: float = 1.0


class TourAnalytics(BaseModel):
    """Analytics data for a tour."""
    tour_id: str
    total_views: int = 0
    unique_views: int = 0
    total_likes: int = 0
    total_shares: int = 0
    avg_session_duration: float = 0.0
    scene_views: Dict[str, int] = {}
    hotspot_clicks: Dict[str, int] = {}
    heatmap_points: List[HeatmapPoint] = []
    share_breakdown: Dict[str, int] = {}
    session_durations: List[float] = []
    device_breakdown: DeviceBreakdown = DeviceBreakdown()
    country_breakdown: Dict[str, int] = {}
    daily_views: List[DailyView] = []


class DashboardStats(BaseModel):
    """Dashboard statistics for a user."""
    total_tours: int = 0
    published_tours: int = 0
    total_views: int = 0
    total_scenes: int = 0
    storage_used: int = 0  # bytes
    storage_limit: int = 0  # bytes


class DashboardRealtimeStats(BaseModel):
    """Realtime dashboard metrics."""
    active_sessions: int = 0
    views_last_hour: int = 0
    likes_last_hour: int = 0
    shares_last_hour: int = 0
    avg_session_duration: float = 0.0
    recent_views: List[DailyView] = []


# ====================
# Paginated Response
# ====================

class PaginatedTourResponse(BaseModel):
    """Paginated response for tours."""
    items: List[Tour]
    total: int
    page: int
    page_size: int
    total_pages: int


# ====================
# API Response Wrapper
# ====================

class ApiResponse(BaseModel):
    """Standard API response wrapper."""
    success: bool = True
    data: Any
    message: Optional[str] = None


# ====================
# AI Processing Schemas
# ====================

class AIJobBase(BaseModel):
    """Base AI Job schema."""
    id: str
    job_type: str
    status: str
    progress: int
    tour_id: Optional[str] = None
    scene_id: Optional[str] = None
    error_message: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AIJobResponse(BaseModel):
    """Response containing an AI job."""
    job: AIJobBase


class SceneAnalysisResult(BaseModel):
    """Result of AI scene analysis."""
    scene_id: str
    room_type: str
    room_confidence: float = Field(..., ge=0, le=1)
    suggested_title: str
    suggested_description: str
    quality_score: int = Field(..., ge=0, le=100)
    quality_issues: Optional[List[str]] = None
    features_detected: List[str] = []


class HotspotSuggestion(BaseModel):
    """AI-suggested hotspot."""
    id: str
    type: str = "navigation"
    position: HotspotPosition
    target_scene_id: Optional[str] = None
    suggested_title: Optional[str] = None
    reasoning: str
    confidence: float = Field(..., ge=0, le=1)


class AIJobStatusResponse(BaseModel):
    """Response containing AI job status with optional results."""
    job: AIJobBase
    result: Optional[Dict[str, Any]] = None


class DescriptionOptions(BaseModel):
    """Options for AI description generation."""
    tone: Optional[str] = Field(default="professional", pattern=r"^(professional|casual|luxury|friendly)$")
    length: Optional[str] = Field(default="medium", pattern=r"^(short|medium|long)$")
    include_features: Optional[bool] = True
    target_audience: Optional[str] = None


class ApplySceneAnalysis(BaseModel):
    """Request to apply AI scene analysis suggestions."""
    suggestions: List[Dict[str, Any]]


class ApplyHotspotSuggestions(BaseModel):
    """Request to apply AI hotspot suggestions."""
    suggestion_ids: List[str]


class AIJobListResponse(BaseModel):
    """Response containing list of AI jobs."""
    jobs: List[AIJobBase]
    total: int


class TourGenerationSceneInput(BaseModel):
    """Scene input for AI-driven tour generation."""
    image_url: str = Field(..., max_length=500)
    thumbnail_url: Optional[str] = Field(default=None, max_length=500)
    title: Optional[str] = Field(default=None, max_length=255)
    description: Optional[str] = Field(default=None, max_length=2000)
    order_index: Optional[int] = Field(default=None, ge=0)
    metadata: Optional[SceneMetadata] = Field(
        default=None,
        alias="scene_metadata",
        validation_alias=AliasChoices("metadata", "scene_metadata"),
        serialization_alias="metadata",
    )

    model_config = ConfigDict(populate_by_name=True)


class TourGenerationRequest(BaseModel):
    """Request payload for AI tour generation."""
    title: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = Field(default=None, max_length=5000)
    status: Optional[TourStatus] = TourStatus.draft
    is_public: Optional[bool] = False  # Deprecated: Use visibility instead
    visibility: Optional[TourVisibility] = TourVisibility.private
    settings: Optional[TourSettings] = None
    scenes: Optional[List[TourGenerationSceneInput]] = None
    image_urls: Optional[List[str]] = None
    generate_titles: Optional[bool] = True
    generate_descriptions: Optional[bool] = True
    suggest_hotspots: Optional[bool] = False
    apply_to_scenes: Optional[bool] = True
    language: Optional[str] = None

    model_config = ConfigDict(extra="allow")


class TourGenerationResponse(BaseModel):
    """Response for AI tour generation."""
    job: AIJobBase
    tour_id: str
    scene_ids: List[str]


class TourOptimizationRequest(BaseModel):
    """Request payload for AI tour optimization."""
    goals: Optional[List[str]] = None
    focus_areas: Optional[List[str]] = None
    update_titles: Optional[bool] = False
    update_descriptions: Optional[bool] = False
    suggest_hotspots: Optional[bool] = False
    language: Optional[str] = None

    model_config = ConfigDict(extra="allow")


class TourOptimizationResponse(BaseModel):
    """Response for AI tour optimization."""
    job: AIJobBase
