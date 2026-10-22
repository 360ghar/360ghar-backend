from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.core.database import Base

# review_status values. 'auto' and 'approved' rows are served by the public API.
SERVED_STATUSES = ("auto", "approved")


class ContentBlock(Base):
    """Generated, validated text for one entity in one locale."""

    __tablename__ = "content_blocks"
    __table_args__ = (
        Index("ux_content_blocks_entity", "entity_type", "slug", "locale", unique=True),
        Index("ix_content_blocks_review", "entity_type", "review_status"),
        Index(
            "ix_content_blocks_manifest",
            "entity_type",
            text("updated_at DESC"),
            postgresql_where=text("review_status IN ('auto', 'approved')"),
        ),
        CheckConstraint(
            "entity_type IN ('locality', 'property')", name="content_blocks_entity_type_check"
        ),
        CheckConstraint("locale IN ('en', 'hi')", name="content_blocks_locale_check"),
        CheckConstraint(
            "review_status IN ('auto', 'needs_review', 'approved', 'rejected', 'failed')",
            name="content_blocks_review_status_check",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    entity_type: Mapped[str] = mapped_column(String(20), nullable=False)
    slug: Mapped[str] = mapped_column(String(200), nullable=False)
    locale: Mapped[str] = mapped_column(String(5), nullable=False)
    body: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    sources: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    facts_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    fact_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    key_fact: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    prompt_version: Mapped[str] = mapped_column(String(20), nullable=False)
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    data_as_of: Mapped[date | None] = mapped_column(Date, nullable=True)
    review_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="needs_review", server_default="needs_review"
    )
    indexable: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    dup_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    errors: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class Locality(Base):
    """Locality master data, loaded from a committed snapshot by scripts/import_localities.py."""

    __tablename__ = "localities"
    __table_args__ = (
        Index("ix_localities_city", "city"),
        CheckConstraint(
            "place_type IN ('locality', 'sector', 'society', 'village', 'road', 'township', 'phase')",
            name="localities_place_type_check",
        ),
    )

    slug: Mapped[str] = mapped_column(String(200), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    city: Mapped[str] = mapped_column(String(100), nullable=False)
    place_type: Mapped[str] = mapped_column(String(30), nullable=False)
    parent_slug: Mapped[str | None] = mapped_column(String(200), nullable=True)
    aliases: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    landmarks: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    source: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class GeneratedImage(Base):
    """Registry of generated art and OG cards. key = sha256(style version + subject + size)."""

    __tablename__ = "generated_images"
    __table_args__ = (
        Index("ix_generated_images_subject", "subject_type", "subject_slug"),
        Index(
            "ix_generated_images_retry",
            "retry_after",
            postgresql_where=text("status = 'failed'"),
        ),
        CheckConstraint(
            "subject_type IN ('city', 'locality', 'property', 'blog')",
            name="generated_images_subject_type_check",
        ),
        CheckConstraint(
            "status IN ('pending', 'ready', 'failed')", name="generated_images_status_check"
        ),
    )

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    subject_type: Mapped[str] = mapped_column(String(20), nullable=False)
    subject_slug: Mapped[str] = mapped_column(String(200), nullable=False)
    public_id: Mapped[str | None] = mapped_column(String(300), nullable=True)
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending", server_default="pending"
    )
    retry_after: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
