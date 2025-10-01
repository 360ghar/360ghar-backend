from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime


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

    class Config:
        from_attributes = True


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

    class Config:
        from_attributes = True


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


class BlogPostCreate(BlogPostBase):
    pass


class BlogPostUpdate(BaseModel):
    title: Optional[str] = Field(None, min_length=1, max_length=500, description="Post title")
    content: Optional[str] = Field(None, min_length=10, description="Post content (HTML/markdown)")
    excerpt: Optional[str] = Field(None, max_length=1000, description="Post excerpt/summary")
    cover_image_url: Optional[str] = Field(None, description="Cover image URL")
    categories: Optional[List[str]] = Field(default=None, description="Category slugs or names")
    tags: Optional[List[str]] = Field(default=None, description="Tag slugs or names")


class BlogPostInDB(BlogPostBase):
    id: int
    slug: str
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class BlogPost(BlogPostInDB):
    categories: Optional[List[BlogCategory]] = None
    tags: Optional[List[BlogTag]] = None

    class Config:
        from_attributes = True


class BlogPostListResponse(BaseModel):
    items: List[BlogPost]
    total: int
    page: int
    limit: int
    total_pages: int
    has_next: bool
    has_prev: bool
