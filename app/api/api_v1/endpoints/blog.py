from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.api_v1.dependencies.auth import (
    get_current_admin,
    get_current_user_optional,
)
from app.config import settings
from app.core.cache import CacheKeyPatterns, invalidate_cache
from app.core.database import get_db
from app.core.db_resilience import extract_db_error_code, is_transient_db_error
from app.core.exceptions import ServiceUnavailableException
from app.core.logging import get_logger
from app.models.enums import BlogPostStatus, UserRole
from app.schemas.blog import (
    BlogCategory,
    BlogCategoryCreate,
    BlogCategoryUpdate,
    BlogGenerateBulkRequest,
    BlogGenerateFromTopicRequest,
    BlogGenerationResult,
    BlogPost,
    BlogPostAdmin,
    BlogPostCreate,
    BlogPostPreviewResponse,
    BlogPostPreviewToken,
    BlogPostUpdate,
    BlogTag,
    BlogTagCreate,
    BlogTagUpdate,
)
from app.schemas.pagination import CursorPage, CursorParams, build_cursor_page
from app.schemas.user import User as UserSchema
from app.services.blog import (
    create_blog_post,
    create_category,
    create_tag,
    delete_blog_post,
    delete_category,
    delete_tag,
    generate_preview_token,
    get_blog_post,
    get_blog_post_cached,
    get_category,
    get_post_by_preview_token,
    get_tag,
    is_hrera_derived_digest,
    list_blog_posts,
    list_categories,
    list_categories_cached,
    list_posts_cached,
    list_tags,
    list_tags_cached,
    update_blog_post,
    update_category,
    update_tag,
)
from app.services.blog_service.generator import generate_bulk_blogs, generate_draft_from_topic

router = APIRouter()
logger = get_logger(__name__)


@router.post(
    "/posts",
    response_model=BlogPostAdmin,
    status_code=201,
    summary="Create blog post",
    openapi_extra={
        "requestBody": {
            "content": {
                "application/json": {
                    "examples": {
                        "create": {
                            "value": {
                                "title": "Top 10 Areas to Live in Bengaluru",
                                "content": "<p>Bengaluru offers a vibrant lifestyle...</p>",
                                "categories": ["guides"],
                                "tags": ["bengaluru", "real-estate"],
                                "focus_keyword": "best areas to live in bengaluru",
                            }
                        },
                    }
                }
            }
        }
    },
)
@invalidate_cache([CacheKeyPatterns.BLOG_POSTS])
async def create_post(
    payload: BlogPostCreate,
    db: AsyncSession = Depends(get_db),
    current_user: UserSchema = Depends(get_current_admin),
):
    """Create a new blog post (admin only)."""
    try:
        return await create_blog_post(db, payload, current_user)
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error in create_post: %s", e, exc_info=True)
        raise HTTPException(
            status_code=500, detail="Internal server error. Please try again later."
        ) from None


@router.get("/posts", response_model=CursorPage[BlogPost], summary="List blog posts")
async def list_posts(
    q: str | None = Query(None, description="Search query across title and content"),
    categories: list[str] | None = Query(None, description="Filter by category slugs or names"),
    tags: list[str] | None = Query(None, description="Filter by tag slugs or names"),
    status: BlogPostStatus | None = Query(
        None,
        description="Admin only: filter by lifecycle status (draft/published/archived/scheduled)",
    ),
    page: CursorParams = Depends(),
    db: AsyncSession = Depends(get_db),
    current_user: UserSchema | None = Depends(get_current_user_optional),
):
    """List blog posts with cursor pagination, filters for categories, tags, and text search."""
    try:
        is_admin = bool(
            current_user and getattr(current_user, "role", None) == UserRole.admin.value
        )
        if status is not None and not is_admin:
            # Public reads return published posts only. Do not drop the filter silently.
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "STATUS_FILTER_ADMIN_ONLY",
                    "message": "The status filter is available to admins only",
                    "field": "query.status",
                },
            )
        all_tags = tags or []
        filters: dict[str, Any] = {
            "q": q,
            "categories": categories,
            "tags": tags,
            "status": status.value if status is not None else None,
        }
        cursor_payload = page.decoded(filters)

        if is_admin:
            # Admin path: uncached, includes inactive posts, supports include_total
            # and optional status filtering.
            items, next_payload, count_total = await list_blog_posts(
                db,
                q=q,
                categories=categories,
                tags=all_tags,
                cursor_payload=cursor_payload,
                limit=page.limit,
                with_total=page.include_total,
                include_inactive=True,
                status=filters["status"],
            )
        elif page.include_total:
            # Public + include_total: bypass cache so count is always fresh
            items, next_payload, count_total = await list_blog_posts(
                db,
                q=q,
                categories=categories,
                tags=all_tags,
                cursor_payload=cursor_payload,
                limit=page.limit,
                with_total=True,
                include_inactive=False,
            )
        else:
            # Public common path: cached, keyed on all kwargs
            items, next_payload, count_total = await list_posts_cached(
                db,
                q=q,
                categories=categories,
                tags=all_tags,
                cursor_payload=cursor_payload,
                limit=page.limit,
            )

        if not is_admin and not settings.HRERA_DATA_ENABLED:
            items = [post for post in items if not is_hrera_derived_digest(post)]
        return build_cursor_page(
            items, limit=page.limit, next_payload=next_payload, total=count_total, filters=filters
        )
    except HTTPException:
        raise
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
        raise HTTPException(
            status_code=500, detail="Internal server error. Please try again later."
        ) from None


@router.get(
    "/posts/preview/{token}",
    response_model=BlogPostPreviewResponse,
    summary="Preview blog post by token",
)
async def get_post_by_preview(
    token: str,
    db: AsyncSession = Depends(get_db),
):
    """Publicly fetch a blog post (any status) using its preview token.

    No authentication required. Intended for sharing drafts/scheduled posts for
    review before they are published.
    """
    try:
        post = await get_post_by_preview_token(db, token)
        if not post or (
            not settings.HRERA_DATA_ENABLED and is_hrera_derived_digest(post)
        ):
            raise HTTPException(status_code=404, detail="Blog post not found")
        return BlogPostPreviewResponse.model_validate(post, from_attributes=True)
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error in get_post_by_preview: %s", e, exc_info=True)
        raise HTTPException(
            status_code=500, detail="Internal server error. Please try again later."
        ) from None


@router.post(
    "/posts/{post_id}/preview-token",
    response_model=BlogPostPreviewToken,
    summary="Generate preview token",
)
@invalidate_cache([CacheKeyPatterns.BLOG_POSTS])
async def create_preview_token(
    post_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: UserSchema = Depends(get_current_admin),
):
    """Generate (or rotate) a preview token for a blog post. Admin only."""
    try:
        post = await generate_preview_token(db, post_id)
        if post.preview_token is None:
            raise HTTPException(status_code=500, detail="Preview token was not generated")
        preview_url = f"/api/v1/blog/posts/preview/{post.preview_token}"
        return BlogPostPreviewToken(preview_token=post.preview_token, preview_url=preview_url)
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error in create_preview_token: %s", e, exc_info=True)
        raise HTTPException(
            status_code=500, detail="Internal server error. Please try again later."
        ) from None


@router.get("/posts/{identifier}", response_model=BlogPost, summary="Get blog post")
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
        if not post or (
            not is_admin
            and not settings.HRERA_DATA_ENABLED
            and is_hrera_derived_digest(post)
        ):
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
        raise HTTPException(
            status_code=500, detail="Internal server error. Please try again later."
        ) from None


@router.put(
    "/posts/{identifier}",
    response_model=BlogPostAdmin,
    summary="Update blog post",
    openapi_extra={
        "requestBody": {
            "content": {
                "application/json": {
                    "examples": {
                        "update": {
                            "value": {
                                "title": "Updated: Top 10 Areas to Live in Bengaluru",
                                "content": "<p>Updated content...</p>",
                                "active": True,
                            }
                        },
                    }
                }
            }
        }
    },
)
@invalidate_cache([CacheKeyPatterns.BLOG_POSTS])
async def update_post(
    identifier: str,
    payload: BlogPostUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: UserSchema = Depends(get_current_admin),
):
    """Update a blog post by ID or slug (admin only)."""
    try:
        return await update_blog_post(db, identifier, payload, current_user)
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error in update_post: %s", e, exc_info=True)
        raise HTTPException(
            status_code=500, detail="Internal server error. Please try again later."
        ) from None


@router.delete("/posts/{identifier}", status_code=204, summary="Delete blog post")
@invalidate_cache([CacheKeyPatterns.BLOG_POSTS])
async def delete_post(
    identifier: str,
    db: AsyncSession = Depends(get_db),
    current_user: UserSchema = Depends(get_current_admin),
):
    """Delete a blog post by ID or slug (admin only)."""
    try:
        await delete_blog_post(db, identifier, current_user)
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error in delete_post: %s", e, exc_info=True)
        raise HTTPException(
            status_code=500, detail="Internal server error. Please try again later."
        ) from None


# AI-powered generation endpoints
@router.post(
    "/generate-from-topic",
    response_model=BlogGenerationResult,
    status_code=201,
    summary="Generate blog from topic",
)
async def generate_from_topic(
    payload: BlogGenerateFromTopicRequest,
    db: AsyncSession = Depends(get_db),
    current_user: UserSchema = Depends(get_current_admin),
):
    """Generate a draft blog from a given topic using Perplexity and fetch images via Google Images (SerpAPI). Admin only."""
    try:
        result = await generate_draft_from_topic(db, topic=payload.topic, actor=current_user)
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error in generate_from_topic: %s", e, exc_info=True)
        raise HTTPException(
            status_code=500, detail="Internal server error. Please try again later."
        ) from None


@router.post(
    "/generate-bulk",
    response_model=CursorPage[BlogGenerationResult],
    status_code=201,
    summary="Generate blogs in bulk",
)
async def generate_bulk(
    payload: BlogGenerateBulkRequest,
    db: AsyncSession = Depends(get_db),
    current_user: UserSchema = Depends(get_current_admin),
):
    """Generate multiple draft blogs by first researching topics, then generating each one. Admin only."""
    try:
        results = await generate_bulk_blogs(db, count=payload.count, actor=current_user)
        # ponytail: the batch is generated in one call, so the page holds every result.
        return build_cursor_page(results, limit=len(results), next_payload=None)
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error in generate_bulk: %s", e, exc_info=True)
        raise HTTPException(
            status_code=500, detail="Internal server error. Please try again later."
        ) from None


# Category Management Endpoints
@router.post(
    "/categories", response_model=BlogCategory, status_code=201, summary="Create blog category"
)
@invalidate_cache([CacheKeyPatterns.BLOG_CATEGORIES])
async def create_category_endpoint(
    payload: BlogCategoryCreate,
    db: AsyncSession = Depends(get_db),
    current_user: UserSchema = Depends(get_current_admin),
):
    """Create a new blog category (admin only). Invalidates category cache."""
    try:
        return await create_category(db, payload.name, payload.description, payload.slug)
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error in create_category_endpoint: %s", e, exc_info=True)
        raise HTTPException(
            status_code=500, detail="Internal server error. Please try again later."
        ) from None


@router.get("/categories", response_model=CursorPage[BlogCategory], summary="List blog categories")
async def list_categories_endpoint(
    page: CursorParams = Depends(),
    db: AsyncSession = Depends(get_db),
    _current_user: UserSchema | None = Depends(get_current_user_optional),
):
    """List all blog categories with cursor pagination. Public endpoint."""
    try:
        cursor_payload = page.decoded()
        if page.include_total:
            # include_total bypasses cache so count is always fresh
            categories, next_payload, count_total = await list_categories(
                db,
                cursor_payload=cursor_payload,
                limit=page.limit,
                with_total=True,
            )
        else:
            # Common public path: cached, keyed on cursor_payload + limit
            categories, next_payload, count_total = await list_categories_cached(
                db,
                cursor_payload=cursor_payload,
                limit=page.limit,
            )
        return build_cursor_page(
            categories, limit=page.limit, next_payload=next_payload, total=count_total
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error in list_categories_endpoint: %s", e, exc_info=True)
        raise HTTPException(
            status_code=500, detail="Internal server error. Please try again later."
        ) from None


@router.get("/categories/{identifier}", response_model=BlogCategory, summary="Get blog category")
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


@router.put("/categories/{identifier}", response_model=BlogCategory, summary="Update blog category")
@invalidate_cache([CacheKeyPatterns.BLOG_CATEGORIES])
async def update_category_endpoint(
    identifier: str,
    payload: BlogCategoryUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: UserSchema = Depends(get_current_admin),
):
    """Update a category by ID or slug (admin only). Invalidates category cache."""
    try:
        return await update_category(db, identifier, payload.name, payload.description)
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error in update_category_endpoint: %s", e, exc_info=True)
        raise HTTPException(
            status_code=500, detail="Internal server error. Please try again later."
        ) from None


@router.delete("/categories/{identifier}", status_code=204, summary="Delete blog category")
@invalidate_cache([CacheKeyPatterns.BLOG_CATEGORIES])
async def delete_category_endpoint(
    identifier: str,
    db: AsyncSession = Depends(get_db),
    current_user: UserSchema = Depends(get_current_admin),
):
    """Delete a category by ID or slug (admin only). Invalidates category cache."""
    try:
        await delete_category(db, identifier)
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error in delete_category_endpoint: %s", e, exc_info=True)
        raise HTTPException(
            status_code=500, detail="Internal server error. Please try again later."
        ) from None


# Tag Management Endpoints
@router.post("/tags", response_model=BlogTag, status_code=201, summary="Create blog tag")
@invalidate_cache([CacheKeyPatterns.BLOG_TAGS])
async def create_tag_endpoint(
    payload: BlogTagCreate,
    db: AsyncSession = Depends(get_db),
    current_user: UserSchema = Depends(get_current_admin),
):
    """Create a new blog tag (admin only). Invalidates tag cache."""
    try:
        return await create_tag(db, payload.name, payload.slug)
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error in create_tag_endpoint: %s", e, exc_info=True)
        raise HTTPException(
            status_code=500, detail="Internal server error. Please try again later."
        ) from None


@router.get("/tags", response_model=CursorPage[BlogTag], summary="List blog tags")
async def list_tags_endpoint(
    page: CursorParams = Depends(),
    db: AsyncSession = Depends(get_db),
    _current_user: UserSchema | None = Depends(get_current_user_optional),
):
    """List all blog tags with cursor pagination. Public endpoint."""
    try:
        cursor_payload = page.decoded()
        if page.include_total:
            # include_total bypasses cache so count is always fresh
            tags, next_payload, count_total = await list_tags(
                db,
                cursor_payload=cursor_payload,
                limit=page.limit,
                with_total=True,
            )
        else:
            # Common public path: cached, keyed on cursor_payload + limit
            tags, next_payload, count_total = await list_tags_cached(
                db,
                cursor_payload=cursor_payload,
                limit=page.limit,
            )
        return build_cursor_page(
            tags, limit=page.limit, next_payload=next_payload, total=count_total
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error in list_tags_endpoint: %s", e, exc_info=True)
        raise HTTPException(
            status_code=500, detail="Internal server error. Please try again later."
        ) from None


@router.get("/tags/{identifier}", response_model=BlogTag, summary="Get blog tag")
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


@router.put("/tags/{identifier}", response_model=BlogTag, summary="Update blog tag")
@invalidate_cache([CacheKeyPatterns.BLOG_TAGS])
async def update_tag_endpoint(
    identifier: str,
    payload: BlogTagUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: UserSchema = Depends(get_current_admin),
):
    """Update a tag by ID or slug (admin only). Invalidates tag cache."""
    try:
        if not payload.name:
            raise HTTPException(status_code=400, detail="Tag name is required")
        return await update_tag(db, identifier, payload.name)
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error in update_tag_endpoint: %s", e, exc_info=True)
        raise HTTPException(
            status_code=500, detail="Internal server error. Please try again later."
        ) from None


@router.delete("/tags/{identifier}", status_code=204, summary="Delete blog tag")
@invalidate_cache([CacheKeyPatterns.BLOG_TAGS])
async def delete_tag_endpoint(
    identifier: str,
    db: AsyncSession = Depends(get_db),
    current_user: UserSchema = Depends(get_current_admin),
):
    """Delete a tag by ID or slug (admin only). Invalidates tag cache."""
    try:
        await delete_tag(db, identifier)
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error in delete_tag_endpoint: %s", e, exc_info=True)
        raise HTTPException(
            status_code=500, detail="Internal server error. Please try again later."
        ) from None
