from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import BlogPostStatus


class BlogSource(BaseModel):
    """A single cited source for a blog post."""
    url: str = Field(..., min_length=1, description="Source URL")
    name: str = Field("", description="Display name of the source (e.g. 'Economic Times')")
    type: str = Field("article", description="Source type: primary, article, government, data, image, video, other")
    retrieved_at: str | None = Field(None, description="ISO 8601 date when the source was accessed")


class BlogSEOMetadata(BaseModel):
    """Flexible SEO metadata container."""
    schema_markup: dict | None = Field(None, description="JSON-LD structured data (Article, FAQPage, etc.)")
    keyword_analysis: dict | None = Field(None, description="Keyword research data: volume, difficulty, related terms")
    trending_score: float | None = Field(None, description="0-100 score indicating trend virality")
    secondary_keywords: list[str] | None = Field(None, description="Additional target keywords")
    internal_links: list[str] | None = Field(None, description="Slugs of related blog posts for internal linking")
    custom_data: dict | None = Field(None, description="Any additional SEO data")


class BlogCategoryBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=200, description="Category name")
    slug: str | None = Field(None, description="URL-friendly slug (auto-generated if not provided)")
    description: str | None = Field(None, max_length=1000, description="Category description")


class BlogCategoryCreate(BlogCategoryBase):
    pass


class BlogCategoryUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=200, description="Category name")
    description: str | None = Field(None, max_length=1000, description="Category description")


class BlogCategory(BlogCategoryBase):
    id: int
    created_at: datetime
    updated_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)



class BlogTagBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=100, description="Tag name")
    slug: str | None = Field(None, description="URL-friendly slug (auto-generated if not provided)")


class BlogTagCreate(BlogTagBase):
    pass


class BlogTagUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=100, description="Tag name")


class BlogTag(BlogTagBase):
    id: int
    created_at: datetime
    updated_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)



class BlogPostBase(BaseModel):
    title: str = Field(..., min_length=1, max_length=500, description="Post title", examples=["Top 10 Areas to Live in Bengaluru"])
    content: str = Field(..., min_length=10, description="Post content (HTML/markdown)", examples=["<p>Bengaluru offers a vibrant lifestyle...</p>"])
    excerpt: str | None = Field(None, max_length=1000, description="Post excerpt/summary")
    cover_image_url: str | None = Field(None, description="Cover image URL")

    # Accept category and tag identifiers (slugs or names)
    categories: list[str] | None = Field(default=None, description="Category slugs or names")
    tags: list[str] | None = Field(default=None, description="Tag slugs or names")

    # SEO fields
    meta_title: str | None = Field(None, max_length=60, description="SEO title tag (distinct from display title)")
    meta_description: str | None = Field(None, max_length=160, description="SERP snippet text")
    focus_keyword: str | None = Field(None, max_length=200, description="Primary target keyword")
    canonical_url: str | None = Field(None, max_length=500, description="Canonical URL for duplicate content")
    og_image_url: str | None = Field(None, max_length=500, description="Open Graph / social share image URL")

    # Structured sources
    sources: list[BlogSource] | None = Field(default=None, description="Cited sources for the blog post")

    # Flexible SEO metadata
    seo_metadata: BlogSEOMetadata | None = Field(None, description="SEO analysis, schema markup, etc.")


class BlogPostCreate(BlogPostBase):
    active: bool | None = Field(default=False, description="Publish status (defaults to draft)", examples=[False, True])
    published_at: datetime | None = Field(None, description="Explicit publish timestamp (defaults to now if active=True)")
    status: BlogPostStatus | None = Field(
        default=None,
        description="Lifecycle status (draft/published/archived/scheduled). Overrides `active` when provided.",
    )
    scheduled_at: datetime | None = Field(
        default=None,
        description="When a scheduled post should be auto-published (required when status=scheduled)",
    )


class BlogPostUpdate(BaseModel):
    title: str | None = Field(None, min_length=1, max_length=500, description="Post title")
    content: str | None = Field(None, min_length=10, description="Post content (HTML/markdown)")
    excerpt: str | None = Field(None, max_length=1000, description="Post excerpt/summary")
    cover_image_url: str | None = Field(None, description="Cover image URL")
    categories: list[str] | None = Field(default=None, description="Category slugs or names")
    tags: list[str] | None = Field(default=None, description="Tag slugs or names")
    active: bool | None = Field(default=None, description="Publish status")
    meta_title: str | None = Field(None, max_length=60, description="SEO title tag")
    meta_description: str | None = Field(None, max_length=160, description="SERP snippet text")
    focus_keyword: str | None = Field(None, max_length=200, description="Primary target keyword")
    canonical_url: str | None = Field(None, max_length=500, description="Canonical URL")
    og_image_url: str | None = Field(None, max_length=500, description="Open Graph image URL")
    sources: list[BlogSource] | None = Field(default=None, description="Cited sources")
    seo_metadata: BlogSEOMetadata | None = Field(None, description="SEO metadata")
    published_at: datetime | None = Field(None, description="Publish timestamp")
    status: BlogPostStatus | None = Field(default=None, description="Lifecycle status")
    scheduled_at: datetime | None = Field(default=None, description="Scheduled publish timestamp")


class BlogPostInDB(BlogPostBase):
    id: int
    slug: str
    active: bool
    created_at: datetime
    updated_at: datetime | None = None
    meta_title: str | None = None
    meta_description: str | None = None
    focus_keyword: str | None = None
    canonical_url: str | None = None
    og_image_url: str | None = None
    reading_time_minutes: int | None = None
    word_count: int | None = None
    published_at: datetime | None = None
    status: str = "draft"
    scheduled_at: datetime | None = None
    preview_token: str | None = None
    sources: list[dict] = Field(default_factory=list)  # type: ignore[assignment]
    seo_metadata: dict = Field(default_factory=dict)  # type: ignore[assignment]

    model_config = ConfigDict(from_attributes=True)


class BlogPost(BlogPostInDB):
    categories: list[BlogCategory] | None = None  # type: ignore[assignment]
    tags: list[BlogTag] | None = None  # type: ignore[assignment]

    model_config = ConfigDict(from_attributes=True)


class BlogPostPreviewResponse(BaseModel):
    """Public-safe blog post representation returned by the preview-by-token endpoint.

    Omits sensitive/internal fields (preview_token, seo_metadata internals, etc.).
    """

    id: int
    title: str
    slug: str
    content: str
    excerpt: str | None = None
    cover_image_url: str | None = None
    status: str
    published_at: datetime | None = None
    created_at: datetime
    updated_at: datetime | None = None
    meta_title: str | None = None
    meta_description: str | None = None
    focus_keyword: str | None = None
    canonical_url: str | None = None
    og_image_url: str | None = None
    reading_time_minutes: int | None = None
    word_count: int | None = None
    sources: list[dict] = Field(default_factory=list)
    categories: list[BlogCategory] = Field(default_factory=list)
    tags: list[BlogTag] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


# AI generation schemas
class BlogGenerateFromTopicRequest(BaseModel):
    topic: str = Field(..., min_length=3, description="Topic to generate a blog for")


class BlogGenerateBulkRequest(BaseModel):
    count: int = Field(1, ge=1, le=20, description="Number of blogs to generate")


class BlogGenerationResult(BaseModel):
    blog: BlogPost
    images: list[str]
