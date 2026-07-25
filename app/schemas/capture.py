"""
Pydantic schemas for guided capture sessions.

Phase 0: session CRUD + frame registration stubs.
Stitch / tour promotion arrives in later phases.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import CaptureMode, CaptureSessionStatus, CaptureTrackingBackend

# ---------------------------------------------------------------------------
# Nested plan / metadata
# ---------------------------------------------------------------------------


class CaptureWaypointPlan(BaseModel):
    """Planned standing position inside a room."""

    id: str
    index: int = 0
    label: str | None = None
    # Local session coordinates in meters (origin = room start / calibration)
    x_m: float = 0.0
    y_m: float = 0.0
    z_m: float = 0.0
    kind: str = "center"  # center | mid_wall | doorway | grid


class CaptureRoomPlan(BaseModel):
    """Room in the capture checklist."""

    id: str
    label: str
    size: str = "medium"  # small | medium | large
    order_index: int = 0
    waypoints: list[CaptureWaypointPlan] = Field(default_factory=list)


class CapturePlan(BaseModel):
    """Full session plan stored on CaptureSession.plan."""

    template: str | None = None  # e.g. "1bhk", "2bhk", "custom"
    rooms: list[CaptureRoomPlan] = Field(default_factory=list)


class CaptureDeviceInfo(BaseModel):
    platform: str | None = None  # ios | android
    model: str | None = None
    os_version: str | None = None
    app_version: str | None = None


class CapturePose(BaseModel):
    position_m: dict[str, float] | None = None  # {x,y,z}
    position_frame: str = "session_local"
    orientation_quat: dict[str, float] | None = None
    yaw_deg: float | None = None
    pitch_deg: float | None = None
    roll_deg: float | None = None
    tracking_quality: str | None = None  # good | limited | unavailable
    tracking_backend: CaptureTrackingBackend = CaptureTrackingBackend.imu_pdr


class CaptureCameraInfo(BaseModel):
    intrinsics: dict[str, float] | None = None
    fov_h_deg: float | None = None
    resolution: list[int] | None = None


class CaptureQuality(BaseModel):
    blur_score: float | None = None
    exposure_ok: bool | None = None


class CaptureFrameMetadata(BaseModel):
    """Per-frame metadata attached when registering an uploaded image."""

    capture_mode: CaptureMode = CaptureMode.multi_yaw
    timestamp_iso: str | None = None
    device: CaptureDeviceInfo | None = None
    pose: CapturePose | None = None
    camera: CaptureCameraInfo | None = None
    quality: CaptureQuality | None = None
    extra: dict[str, Any] | None = None


# ---------------------------------------------------------------------------
# Session request / response
# ---------------------------------------------------------------------------


class CaptureSessionCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)
    plan: CapturePlan | None = None
    device_info: CaptureDeviceInfo | None = None


class CaptureSessionUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)
    status: CaptureSessionStatus | None = None
    progress: int | None = Field(default=None, ge=0, le=100)
    plan: CapturePlan | None = None
    device_info: CaptureDeviceInfo | None = None
    error_message: str | None = None


class CaptureFrameCreate(BaseModel):
    """Register a frame that was already uploaded via /upload or presigned."""

    room_id: str = Field(..., min_length=1, max_length=64)
    room_label: str | None = Field(default=None, max_length=255)
    waypoint_id: str = Field(..., min_length=1, max_length=64)
    waypoint_index: int = Field(default=0, ge=0)
    frame_index: int = Field(default=0, ge=0)
    media_file_id: str | None = None
    image_url: str | None = Field(default=None, max_length=500)
    metadata: CaptureFrameMetadata | None = None


class CaptureFrameResponse(BaseModel):
    id: str
    session_id: str
    room_id: str
    room_label: str | None = None
    waypoint_id: str
    waypoint_index: int
    frame_index: int
    media_file_id: str | None = None
    image_url: str | None = None
    metadata: dict[str, Any] | None = Field(
        default=None,
        validation_alias="frame_metadata",
    )
    created_at: datetime

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class CaptureSessionResponse(BaseModel):
    id: str
    user_id: int
    title: str
    description: str | None = None
    status: CaptureSessionStatus
    progress: int
    plan: dict[str, Any] | None = None
    device_info: dict[str, Any] | None = None
    tour_id: str | None = None
    error_message: str | None = None
    frame_count: int = 0
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class CaptureSessionDetail(CaptureSessionResponse):
    frames: list[CaptureFrameResponse] = Field(default_factory=list)


class CaptureSessionStatusResponse(BaseModel):
    id: str
    status: CaptureSessionStatus
    progress: int
    tour_id: str | None = None
    error_message: str | None = None
    frame_count: int = 0
    message: str | None = None


class CaptureSessionListResponse(BaseModel):
    items: list[CaptureSessionResponse]
    total: int
