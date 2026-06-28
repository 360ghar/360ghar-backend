"""Generic conversation and message models.

App-scoped threads that work across flatmates, property management,
real estate, and stays. Supports N-party conversations via a
separate participants table (not just 1:1 pairs).
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import Enum as SQLEnum

from app.core.database import Base
from app.models.enums import ConversationApp, ConversationSource, ConversationStatus, MessageType

if TYPE_CHECKING:
    from app.models.users import User


class Conversation(Base):
    """Generic conversation thread scoped to an app.

    Participants are tracked in :class:`ConversationParticipant` (M:N),
    supporting group chats across flatmates, PM, real estate, and stays.
    """

    __tablename__ = "conversations"
    __table_args__ = (
        Index("idx_conversations_app", "app"),
        Index("idx_conversations_created_by", "created_by_user_id"),
        Index("idx_conversations_status", "status"),
        Index("idx_conversations_last_message", "last_message_at"),
        Index(
            "idx_conversations_context",
            "context_type",
            "context_id",
            postgresql_where=text("context_id IS NOT NULL"),
        ),
        CheckConstraint(
            "status IN ('active', 'archived', 'blocked', 'closed')",
            name="ck_conversations_status",
        ),
        CheckConstraint(
            "source IN ('listing_interest', 'profile_match', 'booking_inquiry', "
            "'property_inquiry', 'lease_inquiry', 'other')",
            name="ck_conversations_source",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    app: Mapped[ConversationApp] = mapped_column(
        SQLEnum(ConversationApp, name="conversation_app"),
        default=ConversationApp.flatmates,
    )
    created_by_user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[ConversationStatus] = mapped_column(
        String(20), default=ConversationStatus.active
    )
    source: Mapped[ConversationSource] = mapped_column(
        String(30), default=ConversationSource.listing_interest
    )
    last_message_preview: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    context_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    context_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    context_data: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    participants: Mapped[list[ConversationParticipant]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
    )
    messages: Mapped[list[Message]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="Message.created_at",
    )


class ConversationParticipant(Base):
    """A user participating in a conversation (M:N)."""

    __tablename__ = "conversation_participants"
    __table_args__ = (
        Index(
            "idx_conv_participants_conversation",
            "conversation_id",
        ),
        Index("idx_conv_participants_user", "user_id"),
        Index("idx_conv_participants_user_unread", "user_id", "last_read_at"),
        CheckConstraint(
            "role IN ('member', 'admin')",
            name="ck_conv_participants_role",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    role: Mapped[str] = mapped_column(String(20), default="member")
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    muted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    conversation: Mapped[Conversation] = relationship(back_populates="participants")
    user: Mapped[User] = relationship(foreign_keys=[user_id])


class Message(Base):
    """A message in a conversation, unified across all apps."""

    __tablename__ = "messages"
    __table_args__ = (
        Index("idx_messages_conversation", "conversation_id", "created_at"),
        Index("idx_messages_sender", "sender_id"),
        Index(
            "idx_messages_unread",
            "conversation_id",
            "read_at",
            postgresql_where=text("read_at IS NULL"),
        ),
        CheckConstraint(
            "message_type IN ('text', 'image', 'system', 'visit_request')",
            name="ck_messages_message_type",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    sender_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    message_type: Mapped[MessageType] = mapped_column(String(30), default=MessageType.text)
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    attachment_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    message_metadata: Mapped[dict | None] = mapped_column("metadata", JSONB, nullable=True)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    conversation: Mapped[Conversation] = relationship(back_populates="messages")
    sender: Mapped[User | None] = relationship(foreign_keys=[sender_id])
