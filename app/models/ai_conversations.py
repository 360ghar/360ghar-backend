"""
AI Conversation models for the in-app AI agent.

Stores conversation sessions and messages (user, assistant, tool calls)
for the Pydantic AI Agent chat feature.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class AIConversation(Base):
    __tablename__ = "ai_conversations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    messages: Mapped[list[AIConversationMessage]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="AIConversationMessage.created_at",
    )

    __table_args__ = (
        Index("idx_ai_conversations_user", "user_id", "updated_at"),
    )


class AIConversationMessage(Base):
    __tablename__ = "ai_conversation_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    conversation_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("ai_conversations.id", ondelete="CASCADE"),
        nullable=False,
    )
    role: Mapped[str] = mapped_column(
        String(20), nullable=False
    )  # user, assistant, tool_call, tool_result
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    tool_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    tool_args: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    tool_result: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    conversation: Mapped[AIConversation] = relationship(back_populates="messages")

    __table_args__ = (
        Index("idx_ai_messages_conv", "conversation_id", "created_at"),
    )
