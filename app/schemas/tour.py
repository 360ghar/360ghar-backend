"""
Pydantic schemas for 360 Virtual Tour API.

These schemas define the request/response models for the tour management endpoints.
"""
from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field, ConfigDict

from app.models.enums import TourStatus, HotspotType


# ====================
# Tour Settings Schema
# ====================

class TourBrandingSettings(BaseModel):
    """Branding settings for a tour."""
    logo_url: Optional[str] = None
    primary_color: Optional[str] = None
    show_watermark: Optional[bool] = True


class TourSettings(BaseModel):
    """Tour configuration settings."""
    auto_rotate: Optional[bool] = False
    auto_rotate_speed: Optional[float] = Field(default=1.0, ge=0.1, le=10.0)
    initial_scene_id: Optional[str] = None
    initial_view: Optional[Dict[str, float]] = None  # {yaw, pitch}
    show_navbar: Optional[bool] = True
    enable_fullscreen: Optional[bool] = True
    enable_vr: Optional[bool] = True
    branding: Optional[TourBrandingSettings] = None


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
    icon_color: Optional[str] = Field(default=None, pattern=r"^#[0-9A-Fa-f]{6}$")
    icon_size: Optional[int] = Field(default=32, ge=16, le=100)
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
    icon_color: Optional[str] = Field(default=None, pattern=r"^#[0-9A-Fa-f]{6}$")
    icon_size: Optional[int] = Field(default=None, ge=16, le=100)
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
    order_index: Optional[int] = Field(default=0, ge=0)
    metadata: Optional[SceneMetadata] = None


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

    model_config = ConfigDict(from_attributes=True)


# ====================
# Tour Schemas
# ====================

class TourBase(BaseModel):
    """Base tour schema with common fields."""
    title: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = Field(default=None, max_length=5000)
    status: Optional[TourStatus] = TourStatus.draft
    is_public: Optional[bool] = False
    settings: Optional[TourSettings] = None


class TourCreate(TourBase):
    """Schema for creating a tour."""
    pass


class TourUpdate(BaseModel):
    """Schema for updating a tour."""
    title: Optional[str] = Field(default=None, min_length=1, max_length=255)
    description: Optional[str] = Field(default=None, max_length=5000)
    status: Optional[TourStatus] = None
    is_public: Optional[bool] = None
    is_featured: Optional[bool] = None
    settings: Optional[TourSettings] = None
    thumbnail_url: Optional[str] = Field(default=None, max_length=500)


class Tour(TourBase):
    """Tour response schema."""
    id: str
    user_id: int
    is_featured: bool
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
