"""
360 Virtual Tour Models

This module contains SQLAlchemy models for the 360 virtual tour platform:
- Tour: The main virtual tour entity
- Scene: Individual 360° panorama scenes within a tour
- Hotspot: Interactive elements placed within scenes
- TourAnalyticsEvent: Analytics tracking for tour views and interactions
"""
from datetime import datetime
from typing import Optional, List, TYPE_CHECKING
from uuid import uuid4

from sqlalchemy import (
    String,
    Integer,
    Boolean,
    DateTime,
    ForeignKey,
    Text,
    Index,
    BigInteger,
    Float,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func
from sqlalchemy.types import Enum as SQLEnum

from app.core.database import Base
from app.models.enums import TourStatus, TourVisibility, HotspotType

if TYPE_CHECKING:
    from app.models.users import User


def generate_uuid() -> str:
    """Generate a UUID string for primary keys."""
    return str(uuid4())


class Tour(Base):
    """
    Virtual Tour model.

    A tour is a collection of 360° panoramic scenes that users can navigate through.
    Tours can be published publicly or kept as drafts for editing.
    """
    __tablename__ = "tours"
    __table_args__ = (
        Index("idx_tours_user_id", "user_id"),
        Index("idx_tours_status", "status"),
        Index("idx_tours_user_status", "user_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[TourStatus] = mapped_column(
        SQLEnum(TourStatus, name="tour_status"),
        default=TourStatus.draft,
        nullable=False
    )
    is_public: Mapped[bool] = mapped_column(Boolean, default=False)
    visibility: Mapped[TourVisibility] = mapped_column(
        SQLEnum(TourVisibility, name="tour_visibility"),
        default=TourVisibility.private,
        nullable=False
    )
    is_featured: Mapped[bool] = mapped_column(Boolean, default=False)
    view_count: Mapped[int] = mapped_column(Integer, default=0)
    like_count: Mapped[int] = mapped_column(Integer, default=0)
    share_count: Mapped[int] = mapped_column(Integer, default=0)
    settings: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    thumbnail_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    archived_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False
    )
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="tours")
    scenes: Mapped[List["Scene"]] = relationship(
        "Scene",
        back_populates="tour",
        cascade="all, delete-orphan",
        order_by="Scene.order_index"
    )

    @property
    def scene_count(self) -> int:
        """Get the number of scenes in this tour."""
        return len(self.scenes) if self.scenes else 0


class Scene(Base):
    """
    Scene model for 360° panoramic images within a tour.

    Each scene represents a single 360° panorama with its own hotspots
    and view settings.
    """
    __tablename__ = "scenes"
    __table_args__ = (
        Index("idx_scenes_tour_id", "tour_id"),
        Index("idx_scenes_order", "tour_id", "order_index"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    tour_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("tours.id", ondelete="CASCADE"),
        nullable=False
    )
    title: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    image_url: Mapped[str] = mapped_column(String(500), nullable=False)
    thumbnail_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    vr_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    order_index: Mapped[int] = mapped_column(Integer, default=0)
    scene_metadata: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    is_processed: Mapped[bool] = mapped_column(Boolean, default=False)
    processing_error: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False
    )

    # Relationships
    tour: Mapped["Tour"] = relationship("Tour", back_populates="scenes")
    hotspots: Mapped[List["Hotspot"]] = relationship(
        "Hotspot",
        back_populates="scene",
        cascade="all, delete-orphan",
        order_by="Hotspot.order_index"
    )


class Hotspot(Base):
    """
    Hotspot model for interactive elements within scenes.

    Hotspots can be navigation points (linking to other scenes),
    information popups, audio/video players, or custom elements.
    """
    __tablename__ = "hotspots"
    __table_args__ = (
        Index("idx_hotspots_scene_id", "scene_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    scene_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("scenes.id", ondelete="CASCADE"),
        nullable=False
    )
    type: Mapped[HotspotType] = mapped_column(
        SQLEnum(HotspotType, name="hotspot_type"),
        default=HotspotType.info,
        nullable=False
    )
    position: Mapped[dict] = mapped_column(JSONB, nullable=False)  # {yaw, pitch, radius?}
    target_scene_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    title: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    icon: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    icon_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    icon_color: Mapped[Optional[str]] = mapped_column(String(7), nullable=True)  # #RRGGBB
    icon_size: Mapped[int] = mapped_column(Integer, default=32)
    content: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    custom_data: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    order_index: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False
    )

    # Relationships
    scene: Mapped["Scene"] = relationship("Scene", back_populates="hotspots")


class TourAnalyticsEvent(Base):
    """
    Analytics event tracking for tours.

    Records various user interactions like tour views, scene navigation,
    hotspot clicks, and shares for analytics purposes.
    """
    __tablename__ = "tour_analytics_events"
    __table_args__ = (
        Index("idx_analytics_tour_id", "tour_id"),
        Index("idx_analytics_created_at", "created_at"),
        Index("idx_analytics_event_type", "tour_id", "event_type"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tour_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("tours.id", ondelete="CASCADE"),
        nullable=False
    )
    user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    scene_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    hotspot_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    event_data: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    user_agent: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    ip_address: Mapped[Optional[str]] = mapped_column(String(45), nullable=True)
    country: Mapped[Optional[str]] = mapped_column(String(2), nullable=True)
    city: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    device_type: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    browser: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    os: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    screen_resolution: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    session_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False
    )


class AIJob(Base):
    """
    AI Processing Job model.

    Tracks the status of AI processing tasks like scene analysis,
    hotspot suggestions, and description generation.
    """
    __tablename__ = "ai_jobs"
    __table_args__ = (
        Index("idx_ai_jobs_user_id", "user_id"),
        Index("idx_ai_jobs_status", "status"),
        Index("idx_ai_jobs_tour_id", "tour_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    tour_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    scene_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    job_type: Mapped[str] = mapped_column(String(50), nullable=False)  # analyze_scenes, suggest_hotspots, generate_descriptions
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending, processing, completed, failed, cancelled
    progress: Mapped[int] = mapped_column(Integer, default=0)  # 0-100
    retry_count: Mapped[int] = mapped_column(Integer, default=0)  # Number of retry attempts
    result: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False
    )


# ====================
# Additional Tour Data Models
# ====================

class MediaFile(Base):
    """Media file metadata for uploads and processing."""
    __tablename__ = "media_files"
    __table_args__ = (
        Index("idx_media_files_user_id", "user_id"),
        Index("idx_media_files_mime_type", "mime_type"),
        Index("idx_media_files_folder", "folder"),
        Index("idx_media_files_visibility", "visibility"),
        Index("idx_media_files_processed", "is_processed"),
        Index("idx_media_files_created_at", "created_at"),
        Index("idx_media_files_expires_at", "expires_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    tour_id: Mapped[Optional[str]] = mapped_column(ForeignKey("tours.id", ondelete="SET NULL"), nullable=True)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    original_filename: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    file_url: Mapped[str] = mapped_column(String(512), nullable=False)
    thumbnail_url: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    cdn_url: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    file_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    mime_type: Mapped[str] = mapped_column(String(100), nullable=False)
    width: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    height: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    duration: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    folder: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    visibility: Mapped[str] = mapped_column(String(20), default="private")
    is_processed: Mapped[bool] = mapped_column(Boolean, default=False)
    processing_metadata: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Upload tracking fields
    upload_status: Mapped[str] = mapped_column(String(20), default="complete")
    bucket_name: Mapped[Optional[str]] = mapped_column(String(100), default="360ghar-storage")
    storage_path: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)


class UserSession(Base):
    """Auth session tracking for refresh tokens."""
    __tablename__ = "user_sessions"
    __table_args__ = (
        Index("idx_sessions_user_id", "user_id"),
        Index("idx_sessions_refresh_token", "refresh_token_hash"),
        Index("idx_sessions_access_token", "access_token_hash"),
        Index("idx_sessions_expires_at", "expires_at"),
        Index("idx_sessions_revoked", "is_revoked"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    refresh_token_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    access_token_hash: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    user_agent: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    ip_address: Mapped[Optional[str]] = mapped_column(String(45), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    is_revoked: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_accessed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TourLocation(Base):
    """Location metadata for tours."""
    __tablename__ = "tour_locations"
    __table_args__ = (
        Index("idx_locations_tour_id", "tour_id"),
        Index("idx_locations_country_city", "country", "city"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    tour_id: Mapped[str] = mapped_column(ForeignKey("tours.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    address: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    city: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    state: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    country: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    postal_code: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    latitude: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    longitude: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    timezone: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    elevation: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class SearchIndex(Base):
    """Full-text search index for tours and scenes."""
    __tablename__ = "search_index"
    __table_args__ = (
        Index("idx_search_vector", "search_vector"),
        Index("idx_search_tour_id", "tour_id"),
        Index("idx_search_scene_id", "scene_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    tour_id: Mapped[str] = mapped_column(ForeignKey("tours.id", ondelete="CASCADE"), nullable=False)
    scene_id: Mapped[Optional[str]] = mapped_column(ForeignKey("scenes.id", ondelete="CASCADE"), nullable=True)
    search_vector: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    weight_tsrank: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class CacheEntry(Base):
    """Database-level cache entries for frequently accessed tour data."""
    __tablename__ = "cache"
    __table_args__ = (
        Index("idx_cache_expires_at", "expires_at"),
        Index("idx_cache_created_at", "created_at"),
    )

    key: Mapped[str] = mapped_column(String(255), primary_key=True)
    value: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class FloorPlan(Base):
    """Floor plan images and markers for tours."""
    __tablename__ = "floor_plans"
    __table_args__ = (
        Index("idx_floor_plans_tour_id", "tour_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    tour_id: Mapped[str] = mapped_column(ForeignKey("tours.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    image_url: Mapped[str] = mapped_column(String(512), nullable=False)
    floor_number: Mapped[int] = mapped_column(Integer, default=1)
    markers: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class TourBranding(Base):
    """Branding configuration for a tour."""
    __tablename__ = "tour_branding"
    __table_args__ = (
        Index("idx_tour_branding_tour_id", "tour_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    tour_id: Mapped[str] = mapped_column(ForeignKey("tours.id", ondelete="CASCADE"), nullable=False)
    settings: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class CustomDomain(Base):
    """Custom domain configuration for branded tour URLs."""
    __tablename__ = "custom_domains"
    __table_args__ = (
        Index("idx_custom_domains_user_id", "user_id"),
        Index("idx_custom_domains_domain", "domain"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    domain: Mapped[str] = mapped_column(String(255), nullable=False)
    verification_status: Mapped[str] = mapped_column(String(20), default="pending")
    ssl_status: Mapped[str] = mapped_column(String(20), default="pending")
    verification_token: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class VideoMetadata(Base):
    """Video metadata for uploaded video assets."""
    __tablename__ = "video_metadata"
    __table_args__ = (
        Index("idx_video_metadata_media_file_id", "media_file_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    media_file_id: Mapped[str] = mapped_column(ForeignKey("media_files.id", ondelete="CASCADE"), nullable=False)
    duration: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    width: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    height: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    format: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    bitrate: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    framerate: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    thumbnail_url: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    stream_url: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
