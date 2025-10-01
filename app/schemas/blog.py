from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime


class BlogCategoryBase(BaseModel):
    name: str
    slug: Optional[str] = None
    description: Optional[str] = None


class BlogCategoryCreate(BlogCategoryBase):
    pass


class BlogCategory(BlogCategoryBase):
    id: int
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class BlogTagBase(BaseModel):
    name: str
    slug: Optional[str] = None


class BlogTagCreate(BlogTagBase):
    pass


class BlogTag(BlogTagBase):
    id: int
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class BlogPostBase(BaseModel):
    title: str
    content: str
    excerpt: Optional[str] = None
    cover_image_url: Optional[str] = None

    # Accept category and tag identifiers (slugs or names)
    categories: Optional[List[str]] = Field(default=None, description="Category slugs or names")
    tags: Optional[List[str]] = Field(default=None, description="Tag slugs or names")


class BlogPostCreate(BlogPostBase):
    pass


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
