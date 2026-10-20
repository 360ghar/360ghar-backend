"""
360 Virtual Tour Models

This module contains SQLAlchemy models for the 360 virtual tour platform:
- Tour: The main virtual tour entity
- Scene: Individual 360° panorama scenes within a tour
- Hotspot: Interactive elements placed within scenes
- TourAnalyticsEvent: Analytics tracking for tour views and interactions
"""

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import uuid4

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func, text

from app.core.database import Base, db_enum
from app.models.enums import HotspotType, TourStatus, TourVisibility

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
        # Mirrors supabase/migrations/20260723000000_tour_short_code.sql (partial unique index).
        Index(
            "idx_tours_short_code",
            "short_code",
            unique=True,
            postgresql_where=text("short_code IS NOT NULL"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[TourStatus] = mapped_column(
        db_enum(TourStatus, "tour_status"), default=TourStatus.draft, nullable=False
    )
    is_public: Mapped[bool] = mapped_column(Boolean, default=False)
    short_code: Mapped[str | None] = mapped_column(String(12), nullable=True)
    visibility: Mapped[TourVisibility] = mapped_column(
        db_enum(TourVisibility, "tour_visibility"), default=TourVisibility.private, nullable=False
    )
    is_featured: Mapped[bool] = mapped_column(Boolean, default=False)
    view_count: Mapped[int] = mapped_column(Integer, default=0)
    like_count: Mapped[int] = mapped_column(Integer, default=0)
    share_count: Mapped[int] = mapped_column(Integer, default=0)
    settings: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    thumbnail_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="tours")
    scenes: Mapped[list["Scene"]] = relationship(
        "Scene", back_populates="tour", cascade="all, delete-orphan", order_by="Scene.order_index"
    )
    floor_plans: Mapped[list["FloorPlan"]] = relationship(
        "FloorPlan",
        order_by="FloorPlan.floor_number",
        passive_deletes=True,
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
        String(36), ForeignKey("tours.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    image_url: Mapped[str] = mapped_column(String(500), nullable=False)
    thumbnail_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    vr_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    order_index: Mapped[int] = mapped_column(Integer, default=0)
    scene_metadata: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    is_processed: Mapped[bool] = mapped_column(Boolean, default=False)
    processing_error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    # Relationships
    tour: Mapped["Tour"] = relationship("Tour", back_populates="scenes")
    hotspots: Mapped[list["Hotspot"]] = relationship(
        "Hotspot",
        back_populates="scene",
        cascade="all, delete-orphan",
        order_by="Hotspot.order_index",
        foreign_keys="Hotspot.scene_id",
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
        # Partial index from the base DDL (20260621000002_tours_and_media.sql).
        Index(
            "idx_hotspots_target_scene",
            "target_scene_id",
            postgresql_where=text("target_scene_id IS NOT NULL"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    scene_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("scenes.id", ondelete="CASCADE"), nullable=False
    )
    type: Mapped[HotspotType] = mapped_column(
        db_enum(HotspotType, "hotspot_type"), default=HotspotType.info, nullable=False
    )
    position: Mapped[dict] = mapped_column(JSONB, nullable=False)  # {yaw, pitch, radius?}
    target_scene_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("scenes.id", ondelete="CASCADE"), nullable=True
    )
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    icon: Mapped[str | None] = mapped_column(String(50), nullable=True)
    icon_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    icon_color: Mapped[str | None] = mapped_column(String(7), nullable=True)  # #RRGGBB
    icon_size: Mapped[int] = mapped_column(
        Integer, default=32, server_default=text("32"), nullable=False
    )
    content: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    custom_data: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    order_index: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    # Relationships
    scene: Mapped["Scene"] = relationship(
        "Scene", back_populates="hotspots", foreign_keys=[scene_id]
    )


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

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tour_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("tours.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    scene_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    hotspot_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    event_data: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    country: Mapped[str | None] = mapped_column(String(2), nullable=True)
    city: Mapped[str | None] = mapped_column(String(100), nullable=True)
    device_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    browser: Mapped[str | None] = mapped_column(String(50), nullable=True)
    os: Mapped[str | None] = mapped_column(String(50), nullable=True)
    screen_resolution: Mapped[str | None] = mapped_column(String(20), nullable=True)
    session_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
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
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    tour_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    scene_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    job_type: Mapped[str] = mapped_column(
        String(50), nullable=False
    )  # analyze_scenes, suggest_hotspots, generate_descriptions
    status: Mapped[str] = mapped_column(
        String(20), default="pending"
    )  # pending, processing, completed, failed, cancelled
    progress: Mapped[int] = mapped_column(Integer, default=0)  # 0-100
    retry_count: Mapped[int] = mapped_column(Integer, default=0)  # Number of retry attempts
    result: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
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
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    tour_id: Mapped[str | None] = mapped_column(
        ForeignKey("tours.id", ondelete="SET NULL"), nullable=True
    )
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    original_filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    file_url: Mapped[str] = mapped_column(String(512), nullable=False)
    thumbnail_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    cdn_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    file_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    mime_type: Mapped[str] = mapped_column(String(100), nullable=False)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration: Mapped[int | None] = mapped_column(Integer, nullable=True)
    folder: Mapped[str | None] = mapped_column(String(255), nullable=True)
    visibility: Mapped[str] = mapped_column(String(20), default="private")
    is_processed: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Upload tracking fields
    upload_status: Mapped[str] = mapped_column(String(20), default="complete")
    bucket_name: Mapped[str | None] = mapped_column(String(100), default="360ghar-storage")
    storage_path: Mapped[str | None] = mapped_column(String(512), nullable=True)


class TourLocation(Base):
    """Location metadata for tours."""

    __tablename__ = "tour_locations"
    __table_args__ = (
        Index("idx_locations_tour_id", "tour_id"),
        Index("idx_locations_country_city", "country", "city"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    tour_id: Mapped[str] = mapped_column(ForeignKey("tours.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    city: Mapped[str | None] = mapped_column(String(100), nullable=True)
    state: Mapped[str | None] = mapped_column(String(100), nullable=True)
    country: Mapped[str | None] = mapped_column(String(100), nullable=True)
    postal_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    timezone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    elevation: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class FloorPlan(Base):
    """Floor plan images and markers for tours."""

    __tablename__ = "floor_plans"
    __table_args__ = (Index("idx_floor_plans_tour_id", "tour_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    tour_id: Mapped[str] = mapped_column(ForeignKey("tours.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    image_url: Mapped[str] = mapped_column(String(512), nullable=False)
    floor_number: Mapped[int] = mapped_column(Integer, default=1)
    markers: Mapped[list] = mapped_column(
        JSONB,
        default=list,
        server_default=text("'[]'::jsonb"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class CustomDomain(Base):
    """Custom domain configuration for branded tour URLs."""

    __tablename__ = "custom_domains"
    __table_args__ = (
        Index("idx_custom_domains_user_id", "user_id"),
        Index("idx_custom_domains_domain", "domain"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    domain: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    verification_status: Mapped[str] = mapped_column(String(20), default="pending")
    ssl_status: Mapped[str] = mapped_column(String(20), default="pending")
    verification_token: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class TourLike(Base):
    """One viewer's like on a tour. The primary key counts a like once per viewer.

    viewer_key is the client IP as the server sees it (get_client_ip). A client session id
    is not used, because a client can change it on every request.
    """

    __tablename__ = "tour_likes"

    tour_id: Mapped[str] = mapped_column(
        ForeignKey("tours.id", ondelete="CASCADE"), primary_key=True
    )
    viewer_key: Mapped[str] = mapped_column(String(255), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
