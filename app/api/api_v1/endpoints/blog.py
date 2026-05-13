
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.api_v1.dependencies.auth import get_current_active_user, get_current_user_optional
from app.config import settings
from app.core.cache import CacheKeyPatterns, cached, invalidate_cache
from app.core.database import get_db
from app.core.db_resilience import extract_db_error_code, is_transient_db_error
from app.core.exceptions import ServiceUnavailableException
from app.core.logging import get_logger
from app.models.enums import UserRole
from app.schemas.blog import (
    BlogCategory,
    BlogCategoryCreate,
    BlogCategoryListResponse,
    BlogCategoryUpdate,
    BlogGenerateBulkRequest,
    BlogGenerateFromTopicRequest,
    BlogGenerationResult,
    BlogPost,
    BlogPostCreate,
    BlogPostListResponse,
    BlogPostUpdate,
    BlogTag,
    BlogTagCreate,
    BlogTagListResponse,
    BlogTagUpdate,
)
from app.schemas.user import User as UserSchema
from app.services.blog import (
    create_blog_post,
    create_category,
    create_tag,
    delete_blog_post,
    delete_category,
    delete_tag,
    get_blog_post,
    get_blog_post_cached,
    get_category,
    get_tag,
    list_blog_posts,
    list_categories,
    list_tags,
    update_blog_post,
    update_category,
    update_tag,
)
from app.services.blog_service.generator import generate_bulk_blogs, generate_draft_from_topic

router = APIRouter()
logger = get_logger(__name__)


# Cached helper functions for reference data
@cached("blog:posts", ttl=settings.CACHE_TTL_BLOG_POSTS)
async def list_posts_cached(
    db: AsyncSession,
    q: str | None,
    categories: list[str] | None,
    tags: list[str] | None,
    page: int,
    limit: int,
):
    """Cached version of list_blog_posts for public (non-admin) traffic."""
    return await list_blog_posts(db, q=q, categories=categories, tags=tags, page=page, limit=limit, include_inactive=False)


@cached("blog:categories", ttl=settings.CACHE_TTL_BLOG_CATEGORIES)
async def get_categories_cached(db: AsyncSession, page: int, limit: int):
    """Cached version of list_categories."""
    return await list_categories(db, page, limit)


@cached("blog:tags", ttl=settings.CACHE_TTL_BLOG_CATEGORIES)
async def get_tags_cached(db: AsyncSession, page: int, limit: int):
    """Cached version of list_tags."""
    return await list_tags(db, page, limit)


@router.post("/posts", response_model=BlogPost)
@invalidate_cache([CacheKeyPatterns.BLOG_POSTS])
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
        logger.error("Error in create_post: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error. Please try again later.") from None


@router.get("/posts", response_model=BlogPostListResponse)
async def list_posts(
    q: str | None = Query(None, description="Search query across title and content"),
    categories: list[str] | None = Query(None, description="Filter by category slugs or names"),
    tags: list[str] | None = Query(None, description="Filter by tag slugs or names"),
    keywords: list[str] | None = Query(None, description="Alias for tags"),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: UserSchema | None = Depends(get_current_user_optional),
):
    """List blog posts with filters for categories, tags, and text search."""
    try:
        all_tags = (tags or []) + (keywords or [])
        is_admin = bool(current_user and getattr(current_user, "role", None) == UserRole.admin.value)
        if is_admin:
            items, total = await list_blog_posts(
                db,
                q=q,
                categories=categories,
                tags=all_tags,
                page=page,
                limit=limit,
                include_inactive=True,
            )
        else:
            items, total = await list_posts_cached(
                db,
                q=q,
                categories=categories,
                tags=all_tags,
                page=page,
                limit=limit,
            )
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
        if is_transient_db_error(e):
            error_code = extract_db_error_code(e) or "TRANSIENT_DB_ERROR"
            logger.error(
                "Blog list transient DB failure",
                extra={"endpoint": "list_posts", "error_code": error_code},
                exc_info=True,
            )
            raise ServiceUnavailableException(
                detail="Blog listing is temporarily unavailable. Please retry shortly.",
                details={"error_code": error_code, "endpoint": "list_posts"},
            ) from e
        logger.error("Error in list_posts: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error. Please try again later.") from None


@router.get("/posts/{identifier}", response_model=BlogPost)
async def get_post(
    identifier: str,
    db: AsyncSession = Depends(get_db),
    current_user: UserSchema | None = Depends(get_current_user_optional),
):
    """Get a specific blog post by ID or slug. Public endpoint."""
    is_admin = bool(current_user and getattr(current_user, "role", None) == UserRole.admin.value)
    try:
        if is_admin:
            post = await get_blog_post(db, identifier, include_inactive=True)
        else:
            post = await get_blog_post_cached(db, identifier=identifier)
        if not post:
            raise HTTPException(status_code=404, detail="Blog post not found")
        return post
    except HTTPException:
        raise
    except Exception as e:
        if is_transient_db_error(e):
            error_code = extract_db_error_code(e) or "TRANSIENT_DB_ERROR"
            logger.error(
                "Blog get transient DB failure",
                extra={"endpoint": "get_post", "error_code": error_code},
                exc_info=True,
            )
            raise ServiceUnavailableException(
                detail="Blog post is temporarily unavailable. Please retry shortly.",
                details={"error_code": error_code, "endpoint": "get_post"},
            ) from e
        logger.error("Error in get_post: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error. Please try again later.") from None


@router.put("/posts/{identifier}", response_model=BlogPost)
@invalidate_cache([CacheKeyPatterns.BLOG_POSTS])
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
        logger.error("Error in update_post: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error. Please try again later.") from None


@router.delete("/posts/{identifier}")
@invalidate_cache([CacheKeyPatterns.BLOG_POSTS])
async def delete_post(
    identifier: str,
    db: AsyncSession = Depends(get_db),
    current_user: UserSchema = Depends(get_current_active_user),
):
    """Delete a blog post by ID or slug (admin only)."""
    try:
        await delete_blog_post(db, identifier, current_user)
        return {"message": "Blog post deleted successfully"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error in delete_post: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error. Please try again later.") from None


# AI-powered generation endpoints
@router.post("/generate-from-topic", response_model=BlogGenerationResult)
async def generate_from_topic(
    payload: BlogGenerateFromTopicRequest,
    db: AsyncSession = Depends(get_db),
    current_user: UserSchema = Depends(get_current_active_user),
):
    """Generate a draft blog from a given topic using Perplexity and fetch images via Google Images (SerpAPI). Admin only."""
    try:
        result = await generate_draft_from_topic(db, topic=payload.topic, actor=current_user)
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error in generate_from_topic: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error. Please try again later.") from None


@router.post("/generate-bulk", response_model=list[BlogGenerationResult])
async def generate_bulk(
    payload: BlogGenerateBulkRequest,
    db: AsyncSession = Depends(get_db),
    current_user: UserSchema = Depends(get_current_active_user),
):
    """Generate multiple draft blogs by first researching topics, then generating each one. Admin only."""
    try:
        results = await generate_bulk_blogs(db, count=payload.count, actor=current_user)
        return results
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error in generate_bulk: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error. Please try again later.") from None


# Category Management Endpoints
@router.post("/categories", response_model=BlogCategory, status_code=201)
@invalidate_cache([CacheKeyPatterns.BLOG_CATEGORIES])
async def create_category_endpoint(
    payload: BlogCategoryCreate,
    db: AsyncSession = Depends(get_db),
    current_user: UserSchema = Depends(get_current_active_user),
):
    """Create a new blog category (admin only). Invalidates category cache."""
    try:
        return await create_category(db, payload.name, payload.description)
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error in create_category_endpoint: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error. Please try again later.") from None


@router.get("/categories", response_model=BlogCategoryListResponse)
async def list_categories_endpoint(
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(20, ge=1, le=100, description="Items per page"),
    db: AsyncSession = Depends(get_db),
    _current_user: UserSchema | None = Depends(get_current_user_optional),
):
    """List all blog categories with pagination. Public endpoint (cached 6hrs)."""
    try:
        categories, total = await get_categories_cached(db, page, limit)
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
        logger.error("Error in list_categories_endpoint: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error. Please try again later.") from None


@router.get("/categories/{identifier}", response_model=BlogCategory)
async def get_category_endpoint(
    identifier: str,
    db: AsyncSession = Depends(get_db),
    _current_user: UserSchema | None = Depends(get_current_user_optional),
):
    """Get a specific category by ID or slug. Public endpoint."""
    category = await get_category(db, identifier)
    if not category:
        raise HTTPException(status_code=404, detail="Category not found")
    return category


@router.put("/categories/{identifier}", response_model=BlogCategory)
@invalidate_cache([CacheKeyPatterns.BLOG_CATEGORIES])
async def update_category_endpoint(
    identifier: str,
    payload: BlogCategoryUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: UserSchema = Depends(get_current_active_user),
):
    """Update a category by ID or slug (admin only). Invalidates category cache."""
    try:
        return await update_category(db, identifier, payload.name, payload.description)
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error in update_category_endpoint: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error. Please try again later.") from None


@router.delete("/categories/{identifier}")
@invalidate_cache([CacheKeyPatterns.BLOG_CATEGORIES])
async def delete_category_endpoint(
    identifier: str,
    db: AsyncSession = Depends(get_db),
    current_user: UserSchema = Depends(get_current_active_user),
):
    """Delete a category by ID or slug (admin only). Invalidates category cache."""
    try:
        await delete_category(db, identifier)
        return {"message": "Category deleted successfully"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error in delete_category_endpoint: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error. Please try again later.") from None


# Tag Management Endpoints
@router.post("/tags", response_model=BlogTag, status_code=201)
@invalidate_cache([CacheKeyPatterns.BLOG_TAGS])
async def create_tag_endpoint(
    payload: BlogTagCreate,
    db: AsyncSession = Depends(get_db),
    current_user: UserSchema = Depends(get_current_active_user),
):
    """Create a new blog tag (admin only). Invalidates tag cache."""
    try:
        return await create_tag(db, payload.name)
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error in create_tag_endpoint: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error. Please try again later.") from None


@router.get("/tags", response_model=BlogTagListResponse)
async def list_tags_endpoint(
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(20, ge=1, le=100, description="Items per page"),
    db: AsyncSession = Depends(get_db),
    _current_user: UserSchema | None = Depends(get_current_user_optional),
):
    """List all blog tags with pagination. Public endpoint (cached 6hrs)."""
    try:
        tags, total = await get_tags_cached(db, page, limit)
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
        logger.error("Error in list_tags_endpoint: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error. Please try again later.") from None


@router.get("/tags/{identifier}", response_model=BlogTag)
async def get_tag_endpoint(
    identifier: str,
    db: AsyncSession = Depends(get_db),
    _current_user: UserSchema | None = Depends(get_current_user_optional),
):
    """Get a specific tag by ID or slug. Public endpoint."""
    tag = await get_tag(db, identifier)
    if not tag:
        raise HTTPException(status_code=404, detail="Tag not found")
    return tag


@router.put("/tags/{identifier}", response_model=BlogTag)
@invalidate_cache([CacheKeyPatterns.BLOG_TAGS])
async def update_tag_endpoint(
    identifier: str,
    payload: BlogTagUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: UserSchema = Depends(get_current_active_user),
):
    """Update a tag by ID or slug (admin only). Invalidates tag cache."""
    try:
        return await update_tag(db, identifier, payload.name or "")
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error in update_tag_endpoint: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error. Please try again later.") from None


@router.delete("/tags/{identifier}")
@invalidate_cache([CacheKeyPatterns.BLOG_TAGS])
async def delete_tag_endpoint(
    identifier: str,
    db: AsyncSession = Depends(get_db),
    current_user: UserSchema = Depends(get_current_active_user),
):
    """Delete a tag by ID or slug (admin only). Invalidates tag cache."""
    try:
        await delete_tag(db, identifier)
        return {"message": "Tag deleted successfully"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error in delete_tag_endpoint: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error. Please try again later.") from None
