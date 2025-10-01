from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional, List
from app.core.database import get_db
from app.core.logging import get_logger
from app.api.api_v1.endpoints.auth import get_current_active_user, get_current_user_optional
from app.schemas.user import User as UserSchema
from app.schemas.blog import (
    BlogPostCreate, BlogPostUpdate, BlogPost, BlogPostListResponse,
    BlogCategoryCreate, BlogCategoryUpdate, BlogCategory, BlogCategoryListResponse,
    BlogTagCreate, BlogTagUpdate, BlogTag, BlogTagListResponse
)
from app.services.blog import (
    create_blog_post, get_blog_post, list_blog_posts, update_blog_post, delete_blog_post,
    create_category, get_category, list_categories, update_category, delete_category,
    create_tag, get_tag, list_tags, update_tag, delete_tag
)

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
    """Get a specific blog post by ID or slug. Public endpoint."""
    post = await get_blog_post(db, identifier)
    if not post:
        raise HTTPException(status_code=404, detail="Blog post not found")
    return post


@router.put("/posts/{identifier}", response_model=BlogPost)
async def update_post(
    identifier: str,
    payload: BlogPostUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: UserSchema = Depends(get_current_active_user),
):
    """Update a blog post by ID or slug (admin only)."""
    try:
        return await update_blog_post(db, identifier, payload, current_user)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update blog post: {e}", exc_info=True)
        raise


@router.delete("/posts/{identifier}")
async def delete_post(
    identifier: str,
    db: AsyncSession = Depends(get_db),
    current_user: UserSchema = Depends(get_current_active_user),
):
    """Delete a blog post by ID or slug (admin only)."""
    try:
        success = await delete_blog_post(db, identifier, current_user)
        return {"message": "Blog post deleted successfully"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete blog post: {e}", exc_info=True)
        raise


# Category Management Endpoints
@router.post("/categories", response_model=BlogCategory, status_code=201)
async def create_category_endpoint(
    payload: BlogCategoryCreate,
    db: AsyncSession = Depends(get_db),
    current_user: UserSchema = Depends(get_current_active_user),
):
    """Create a new blog category (admin only)."""
    try:
        return await create_category(db, payload.name, payload.description)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to create category: {e}", exc_info=True)
        raise


@router.get("/categories", response_model=BlogCategoryListResponse)
async def list_categories_endpoint(
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(20, ge=1, le=100, description="Items per page"),
    db: AsyncSession = Depends(get_db),
    _current_user: Optional[UserSchema] = Depends(get_current_user_optional),
):
    """List all blog categories with pagination. Public endpoint."""
    try:
        categories, total = await list_categories(db, page, limit)
        total_pages = (total + limit - 1) // limit
        return {
            "items": categories,
            "total": total,
            "page": page,
            "limit": limit,
            "total_pages": total_pages,
            "has_next": page < total_pages,
            "has_prev": page > 1,
        }
    except Exception as e:
        logger.error(f"Failed to list categories: {e}", exc_info=True)
        raise


@router.get("/categories/{identifier}", response_model=BlogCategory)
async def get_category_endpoint(
    identifier: str,
    db: AsyncSession = Depends(get_db),
    _current_user: Optional[UserSchema] = Depends(get_current_user_optional),
):
    """Get a specific category by ID or slug. Public endpoint."""
    category = await get_category(db, identifier)
    if not category:
        raise HTTPException(status_code=404, detail="Category not found")
    return category


@router.put("/categories/{identifier}", response_model=BlogCategory)
async def update_category_endpoint(
    identifier: str,
    payload: BlogCategoryUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: UserSchema = Depends(get_current_active_user),
):
    """Update a category by ID or slug (admin only)."""
    try:
        return await update_category(db, identifier, payload.name, payload.description)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update category: {e}", exc_info=True)
        raise


@router.delete("/categories/{identifier}")
async def delete_category_endpoint(
    identifier: str,
    db: AsyncSession = Depends(get_db),
    current_user: UserSchema = Depends(get_current_active_user),
):
    """Delete a category by ID or slug (admin only)."""
    try:
        success = await delete_category(db, identifier)
        return {"message": "Category deleted successfully"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete category: {e}", exc_info=True)
        raise


# Tag Management Endpoints
@router.post("/tags", response_model=BlogTag, status_code=201)
async def create_tag_endpoint(
    payload: BlogTagCreate,
    db: AsyncSession = Depends(get_db),
    current_user: UserSchema = Depends(get_current_active_user),
):
    """Create a new blog tag (admin only)."""
    try:
        return await create_tag(db, payload.name)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to create tag: {e}", exc_info=True)
        raise


@router.get("/tags", response_model=BlogTagListResponse)
async def list_tags_endpoint(
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(20, ge=1, le=100, description="Items per page"),
    db: AsyncSession = Depends(get_db),
    _current_user: Optional[UserSchema] = Depends(get_current_user_optional),
):
    """List all blog tags with pagination. Public endpoint."""
    try:
        tags, total = await list_tags(db, page, limit)
        total_pages = (total + limit - 1) // limit
        return {
            "items": tags,
            "total": total,
            "page": page,
            "limit": limit,
            "total_pages": total_pages,
            "has_next": page < total_pages,
            "has_prev": page > 1,
        }
    except Exception as e:
        logger.error(f"Failed to list tags: {e}", exc_info=True)
        raise


@router.get("/tags/{identifier}", response_model=BlogTag)
async def get_tag_endpoint(
    identifier: str,
    db: AsyncSession = Depends(get_db),
    _current_user: Optional[UserSchema] = Depends(get_current_user_optional),
):
    """Get a specific tag by ID or slug. Public endpoint."""
    tag = await get_tag(db, identifier)
    if not tag:
        raise HTTPException(status_code=404, detail="Tag not found")
    return tag


@router.put("/tags/{identifier}", response_model=BlogTag)
async def update_tag_endpoint(
    identifier: str,
    payload: BlogTagUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: UserSchema = Depends(get_current_active_user),
):
    """Update a tag by ID or slug (admin only)."""
    try:
        return await update_tag(db, identifier, payload.name)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update tag: {e}", exc_info=True)
        raise


@router.delete("/tags/{identifier}")
async def delete_tag_endpoint(
    identifier: str,
    db: AsyncSession = Depends(get_db),
    current_user: UserSchema = Depends(get_current_active_user),
):
    """Delete a tag by ID or slug (admin only)."""
    try:
        success = await delete_tag(db, identifier)
        return {"message": "Tag deleted successfully"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete tag: {e}", exc_info=True)
        raise
