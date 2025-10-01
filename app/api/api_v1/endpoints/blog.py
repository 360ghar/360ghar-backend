from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional, List
from app.core.database import get_db
from app.core.logging import get_logger
from app.api.api_v1.endpoints.auth import get_current_active_user, get_current_user_optional
from app.schemas.user import User as UserSchema
from app.schemas.blog import BlogPostCreate, BlogPost, BlogPostListResponse
from app.services.blog import create_blog_post, get_blog_post, list_blog_posts

router = APIRouter()
logger = get_logger(__name__)


@router.post("/posts", response_model=BlogPost)
async def create_post(
    payload: BlogPostCreate,
    db: AsyncSession = Depends(get_db),
    current_user: UserSchema = Depends(get_current_active_user),
):
    """Create a new blog post (admin only)."""
    try:
        return await create_blog_post(db, payload, current_user)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to create blog post: {e}", exc_info=True)
        raise


@router.get("/posts", response_model=BlogPostListResponse)
async def list_posts(
    q: Optional[str] = Query(None, description="Search query across title and content"),
    categories: Optional[List[str]] = Query(None, description="Filter by category slugs or names"),
    tags: Optional[List[str]] = Query(None, description="Filter by tag slugs or names"),
    keywords: Optional[List[str]] = Query(None, description="Alias for tags"),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    _current_user: Optional[UserSchema] = Depends(get_current_user_optional),
):
    """List blog posts with filters for categories, tags, and text search."""
    try:
        all_tags = (tags or []) + (keywords or [])
        items, total = await list_blog_posts(db, q=q, categories=categories, tags=all_tags, page=page, limit=limit)
        total_pages = (total + limit - 1) // limit
        return {
            "items": items,
            "total": total,
            "page": page,
            "limit": limit,
            "total_pages": total_pages,
            "has_next": page < total_pages,
            "has_prev": page > 1,
        }
    except Exception as e:
        logger.error(f"Failed to list blog posts: {e}", exc_info=True)
        raise


@router.get("/posts/{identifier}", response_model=BlogPost)
async def get_post(identifier: str, db: AsyncSession = Depends(get_db), _current_user: Optional[UserSchema] = Depends(get_current_user_optional)):
    post = await get_blog_post(db, identifier)
    if not post:
        raise HTTPException(status_code=404, detail="Blog post not found")
    return post
