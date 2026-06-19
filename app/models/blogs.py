from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.core.database import Base


class BlogCategory(Base):
    __tablename__ = "blog_categories"
    __table_args__ = (
        Index("ux_blog_categories_slug", "slug", unique=True),
        Index("ux_blog_categories_name", "name", unique=True),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    slug: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), onupdate=func.now(), nullable=True)

    posts: Mapped[list[BlogPost]] = relationship(
        back_populates="categories",
        secondary="blog_post_categories",
        lazy="selectin",
    )


class BlogTag(Base):
    __tablename__ = "blog_tags"
    __table_args__ = (
        Index("ux_blog_tags_slug", "slug", unique=True),
        Index("ux_blog_tags_name", "name", unique=True),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    slug: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), onupdate=func.now(), nullable=True)

    posts: Mapped[list[BlogPost]] = relationship(
        back_populates="tags",
        secondary="blog_post_tags",
        lazy="selectin",
    )


class BlogPost(Base):
    __tablename__ = "blog_posts"
    __table_args__ = (
        Index("ux_blog_posts_slug", "slug", unique=True),
        Index("ix_blog_posts_created_at", "created_at"),
        Index("idx_blog_posts_preview_token", "preview_token"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String, nullable=False)
    slug: Mapped[str] = mapped_column(String, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    excerpt: Mapped[str | None] = mapped_column(Text, nullable=True)
    cover_image_url: Mapped[str | None] = mapped_column(String, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=False)
    author_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), onupdate=func.now(), nullable=True)

    # Lifecycle status (draft / published / archived / scheduled). Kept in sync
    # with ``active`` in the service layer (active == (status == published)).
    status: Mapped[str] = mapped_column(String(32), default="draft", index=True)
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    preview_token: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # SEO fields
    meta_title: Mapped[str | None] = mapped_column(String(60), nullable=True)
    meta_description: Mapped[str | None] = mapped_column(String(160), nullable=True)
    focus_keyword: Mapped[str | None] = mapped_column(String(200), nullable=True)
    canonical_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    og_image_url: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # Reading analytics
    reading_time_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    word_count: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Publishing timestamp (separate from created_at for scheduling)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Structured sources: JSONB array of {url, name, type, retrieved_at}
    sources: Mapped[list] = mapped_column(JSONB, nullable=False, default=list, server_default="[]")

    # Flexible SEO metadata: schema_markup, keyword_analysis, trending_score, etc.
    seo_metadata: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default="{}")

    categories: Mapped[list[BlogCategory]] = relationship(
        back_populates="posts",
        secondary="blog_post_categories",
        lazy="selectin",
    )
    tags: Mapped[list[BlogTag]] = relationship(
        back_populates="posts",
        secondary="blog_post_tags",
        lazy="selectin",
    )


class BlogPostCategory(Base):
    __tablename__ = "blog_post_categories"
    __table_args__ = (
        Index("ux_blog_post_category_unique", "post_id", "category_id", unique=True),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    post_id: Mapped[int] = mapped_column(ForeignKey("blog_posts.id", ondelete="CASCADE"))
    category_id: Mapped[int] = mapped_column(ForeignKey("blog_categories.id", ondelete="CASCADE"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class BlogPostTag(Base):
    __tablename__ = "blog_post_tags"
    __table_args__ = (
        Index("ux_blog_post_tag_unique", "post_id", "tag_id", unique=True),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    post_id: Mapped[int] = mapped_column(ForeignKey("blog_posts.id", ondelete="CASCADE"))
    tag_id: Mapped[int] = mapped_column(ForeignKey("blog_tags.id", ondelete="CASCADE"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
