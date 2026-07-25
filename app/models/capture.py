"""
Guided capture session models.

A CaptureSession represents one property walkthrough from the mobile capture app.
Rooms / waypoints live in the plan JSON for Phase 0; frames are stored relationally
so progressive upload can attach media + pose metadata.
"""
from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func
from sqlalchemy.types import Enum as SQLEnum

from app.core.database import Base
from app.models.enums import CaptureSessionStatus

if TYPE_CHECKING:
    from app.models.tours import Tour
    from app.models.users import User


def generate_uuid() -> str:
    return str(uuid4())


class CaptureSession(Base):
    """One guided-capture walkthrough owned by a user."""

    __tablename__ = "capture_sessions"
    __table_args__ = (
        Index("idx_capture_sessions_user_id", "user_id"),
        Index("idx_capture_sessions_status", "status"),
        Index("idx_capture_sessions_user_created", "user_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[CaptureSessionStatus] = mapped_column(
        SQLEnum(
            CaptureSessionStatus,
            name="capture_session_status",
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        default=CaptureSessionStatus.draft,
        nullable=False,
    )
    progress: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # Room checklist + waypoint plan (see schemas.capture.CapturePlan)
    plan: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # Device / app info from the capture client
    device_info: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # Linked tour once processing completes
    tour_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("tours.id", ondelete="SET NULL"),
        nullable=True,
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    user: Mapped[User] = relationship("User")
    tour: Mapped[Tour | None] = relationship("Tour")
    frames: Mapped[list[CaptureFrame]] = relationship(
        "CaptureFrame",
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="CaptureFrame.created_at",
    )


class CaptureFrame(Base):
    """A single captured image registered against a session waypoint."""

    __tablename__ = "capture_frames"
    __table_args__ = (
        Index("idx_capture_frames_session_id", "session_id"),
        Index("idx_capture_frames_session_room", "session_id", "room_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    session_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("capture_sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    room_id: Mapped[str] = mapped_column(String(64), nullable=False)
    room_label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    waypoint_id: Mapped[str] = mapped_column(String(64), nullable=False)
    waypoint_index: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    frame_index: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # Media already uploaded via /upload or presigned flow
    media_file_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    image_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # Full capture metadata (pose, camera, quality) — see CaptureFrameMetadata schema
    frame_metadata: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    session: Mapped[CaptureSession] = relationship(
        "CaptureSession",
        back_populates="frames",
    )
