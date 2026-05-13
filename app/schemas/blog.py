from pydantic import BaseModel, Field, ConfigDict
from typing import Optional, List, Any
from datetime import datetime


class BlogSource(BaseModel):
    """A single cited source for a blog post."""
    url: str = Field(..., min_length=1, description="Source URL")
    name: str = Field("", description="Display name of the source (e.g. 'Economic Times')")
    type: str = Field("article", description="Source type: primary, article, government, data, image, video, other")
    retrieved_at: Optional[str] = Field(None, description="ISO 8601 date when the source was accessed")


class BlogSEOMetadata(BaseModel):
    """Flexible SEO metadata container."""
    schema_markup: Optional[dict] = Field(None, description="JSON-LD structured data (Article, FAQPage, etc.)")
    keyword_analysis: Optional[dict] = Field(None, description="Keyword research data: volume, difficulty, related terms")
    trending_score: Optional[float] = Field(None, description="0-100 score indicating trend virality")
    secondary_keywords: Optional[List[str]] = Field(None, description="Additional target keywords")
    internal_links: Optional[List[str]] = Field(None, description="Slugs of related blog posts for internal linking")
    custom_data: Optional[dict] = Field(None, description="Any additional SEO data")


class BlogCategoryBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=200, description="Category name")
    slug: Optional[str] = Field(None, description="URL-friendly slug (auto-generated if not provided)")
    description: Optional[str] = Field(None, max_length=1000, description="Category description")


class BlogCategoryCreate(BlogCategoryBase):
    pass


class BlogCategoryUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=200, description="Category name")
    description: Optional[str] = Field(None, max_length=1000, description="Category description")


class BlogCategory(BlogCategoryBase):
    id: int
    created_at: datetime
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class BlogCategoryListResponse(BaseModel):
    items: List[BlogCategory]
    total: int
    page: int
    limit: int
    total_pages: int
    has_next: bool
    has_prev: bool


class BlogTagBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=100, description="Tag name")
    slug: Optional[str] = Field(None, description="URL-friendly slug (auto-generated if not provided)")


class BlogTagCreate(BlogTagBase):
    pass


class BlogTagUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100, description="Tag name")


class BlogTag(BlogTagBase):
    id: int
    created_at: datetime
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class BlogTagListResponse(BaseModel):
    items: List[BlogTag]
    total: int
    page: int
    limit: int
    total_pages: int
    has_next: bool
    has_prev: bool


class BlogPostBase(BaseModel):
    title: str = Field(..., min_length=1, max_length=500, description="Post title")
    content: str = Field(..., min_length=10, description="Post content (HTML/markdown)")
    excerpt: Optional[str] = Field(None, max_length=1000, description="Post excerpt/summary")
    cover_image_url: Optional[str] = Field(None, description="Cover image URL")

    # Accept category and tag identifiers (slugs or names)
    categories: Optional[List[str]] = Field(default=None, description="Category slugs or names")
    tags: Optional[List[str]] = Field(default=None, description="Tag slugs or names")

    # SEO fields
    meta_title: Optional[str] = Field(None, max_length=60, description="SEO title tag (distinct from display title)")
    meta_description: Optional[str] = Field(None, max_length=160, description="SERP snippet text")
    focus_keyword: Optional[str] = Field(None, max_length=200, description="Primary target keyword")
    canonical_url: Optional[str] = Field(None, max_length=500, description="Canonical URL for duplicate content")
    og_image_url: Optional[str] = Field(None, max_length=500, description="Open Graph / social share image URL")

    # Structured sources
    sources: Optional[List[BlogSource]] = Field(default=None, description="Cited sources for the blog post")

    # Flexible SEO metadata
    seo_metadata: Optional[BlogSEOMetadata] = Field(None, description="SEO analysis, schema markup, etc.")


class BlogPostCreate(BlogPostBase):
    active: Optional[bool] = Field(default=False, description="Publish status (defaults to draft)")
    published_at: Optional[datetime] = Field(None, description="Explicit publish timestamp (defaults to now if active=True)")


class BlogPostUpdate(BaseModel):
    title: Optional[str] = Field(None, min_length=1, max_length=500, description="Post title")
    content: Optional[str] = Field(None, min_length=10, description="Post content (HTML/markdown)")
    excerpt: Optional[str] = Field(None, max_length=1000, description="Post excerpt/summary")
    cover_image_url: Optional[str] = Field(None, description="Cover image URL")
    categories: Optional[List[str]] = Field(default=None, description="Category slugs or names")
    tags: Optional[List[str]] = Field(default=None, description="Tag slugs or names")
    active: Optional[bool] = Field(default=None, description="Publish status")
    meta_title: Optional[str] = Field(None, max_length=60, description="SEO title tag")
    meta_description: Optional[str] = Field(None, max_length=160, description="SERP snippet text")
    focus_keyword: Optional[str] = Field(None, max_length=200, description="Primary target keyword")
    canonical_url: Optional[str] = Field(None, max_length=500, description="Canonical URL")
    og_image_url: Optional[str] = Field(None, max_length=500, description="Open Graph image URL")
    sources: Optional[List[BlogSource]] = Field(default=None, description="Cited sources")
    seo_metadata: Optional[BlogSEOMetadata] = Field(None, description="SEO metadata")
    published_at: Optional[datetime] = Field(None, description="Publish timestamp")


class BlogPostInDB(BlogPostBase):
    id: int
    slug: str
    active: bool
    created_at: datetime
    updated_at: Optional[datetime] = None
    meta_title: Optional[str] = None
    meta_description: Optional[str] = None
    focus_keyword: Optional[str] = None
    canonical_url: Optional[str] = None
    og_image_url: Optional[str] = None
    reading_time_minutes: Optional[int] = None
    word_count: Optional[int] = None
    published_at: Optional[datetime] = None
    sources: List[dict] = Field(default_factory=list)
    seo_metadata: dict = Field(default_factory=dict)

    model_config = ConfigDict(from_attributes=True)


class BlogPost(BlogPostInDB):
    categories: Optional[List[BlogCategory]] = None
    tags: Optional[List[BlogTag]] = None

    model_config = ConfigDict(from_attributes=True)


class BlogPostListResponse(BaseModel):
    items: List[BlogPost]
    total: int
    page: int
    limit: int
    total_pages: int
    has_next: bool
    has_prev: bool


# AI generation schemas
class BlogGenerateFromTopicRequest(BaseModel):
    topic: str = Field(..., min_length=3, description="Topic to generate a blog for")


class BlogGenerateBulkRequest(BaseModel):
    count: int = Field(1, ge=1, le=20, description="Number of blogs to generate")


class BlogGenerationResult(BaseModel):
    blog: BlogPost
    images: List[str]
