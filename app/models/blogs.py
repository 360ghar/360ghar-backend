from sqlalchemy import Integer, String, Text, DateTime, ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func
from typing import Optional, List
from datetime import datetime
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
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime, onupdate=func.now(), nullable=True)

    posts: Mapped[List["BlogPost"]] = relationship(
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
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime, onupdate=func.now(), nullable=True)

    posts: Mapped[List["BlogPost"]] = relationship(
        back_populates="tags",
        secondary="blog_post_tags",
        lazy="selectin",
    )


class BlogPost(Base):
    __tablename__ = "blog_posts"
    __table_args__ = (
        Index("ux_blog_posts_slug", "slug", unique=True),
        Index("ix_blog_posts_created_at", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String, nullable=False)
    slug: Mapped[str] = mapped_column(String, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    excerpt: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    cover_image_url: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    author_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime, onupdate=func.now(), nullable=True)

    categories: Mapped[List[BlogCategory]] = relationship(
        back_populates="posts",
        secondary="blog_post_categories",
        lazy="selectin",
    )
    tags: Mapped[List[BlogTag]] = relationship(
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
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class BlogPostTag(Base):
    __tablename__ = "blog_post_tags"
    __table_args__ = (
        Index("ux_blog_post_tag_unique", "post_id", "tag_id", unique=True),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    post_id: Mapped[int] = mapped_column(ForeignKey("blog_posts.id", ondelete="CASCADE"))
    tag_id: Mapped[int] = mapped_column(ForeignKey("blog_tags.id", ondelete="CASCADE"))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
