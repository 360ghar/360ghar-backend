from __future__ import annotations

import re as _re
import secrets
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.core.cache import cached
from app.core.db_resilience import execute_with_transient_retry
from app.core.exceptions import (
    BadRequestException,
    BlogNotFoundException,
    CategoryNotFoundException,
    ConflictException,
    ForbiddenException,
    TagNotFoundException,
)
from app.core.logging import get_logger
from app.models.blogs import BlogCategory, BlogPost, BlogPostCategory, BlogPostTag, BlogTag
from app.models.enums import BlogPostStatus, UserRole
from app.schemas.pagination import keyset_filter, keyset_payload, keyset_sort_value
from app.utils.validators import ValidationUtils

if TYPE_CHECKING:
    from app.schemas.blog import BlogPost as BlogPostSchema

logger = get_logger(__name__)


def _slugify(value: str) -> str:
    import re
    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9\-\s]", "", value)
    value = re.sub(r"\s+", "-", value)
    value = re.sub(r"-+", "-", value)
    return value


def _compute_word_count(content: str) -> int:
    text = _re.sub(r"<[^>]+>", " ", content or "")
    text = _re.sub(r"\s+", " ", text).strip()
    return len(text.split()) if text else 0


def _compute_reading_time(word_count: int) -> int:
    return max(1, (word_count + 199) // 200)


def _auto_meta_title(title: str) -> str:
    title = title.strip()
    if len(title) <= 57:
        return title
    cut = title[:57]
    last_space = cut.rfind(" ")
    if last_space > 34:
        return title[:last_space] + "…"
    return cut.rstrip() + "…"


def _auto_meta_description(excerpt: str | None, content: str) -> str:
    if excerpt and excerpt.strip():
        src = excerpt.strip()
    else:
        src = _re.sub(r"<[^>]+>", " ", content or "")
        src = _re.sub(r"\s+", " ", src).strip()
    if len(src) <= 157:
        return src
    cut = src[:157]
    last_space = cut.rfind(" ")
    if last_space > 94:
        return src[:last_space] + "…"
    return cut.rstrip() + "…"


def _serialize_sources(sources) -> list[dict]:
    """Convert BlogSource objects or dicts to plain dicts for JSONB storage."""
    if not sources:
        return []
    result = []
    for s in sources:
        if isinstance(s, dict):
            result.append(s)
        elif hasattr(s, "model_dump"):
            result.append(s.model_dump())
        else:
            result.append({"url": str(s)})
    return result


def _serialize_seo_metadata(seo_metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    """Convert BlogSEOMetadata object or dict to plain dict for JSONB storage."""
    if not seo_metadata:
        return {}
    if isinstance(seo_metadata, dict):
        return seo_metadata
    if hasattr(seo_metadata, "model_dump"):
        return dict(seo_metadata.model_dump(exclude_none=True))
    logger.warning("Unsupported seo_metadata type %s; storing empty metadata", type(seo_metadata).__name__)
    return {}


def _coerce_status(value: Any) -> BlogPostStatus:
    if isinstance(value, BlogPostStatus):
        return value
    if value is None or value == "":
        return BlogPostStatus.draft
    return BlogPostStatus(str(value))


def _resolve_status_for_create(data: Any) -> tuple[str, bool, datetime | None]:
    """Resolve (status, active, published_at) for a new blog post.

    ``status`` takes precedence over the legacy ``active`` flag. ``active`` is
    always kept in sync with ``status == published``.
    """
    requested_status = getattr(data, "status", None)
    scheduled_at = getattr(data, "scheduled_at", None)
    published_at = getattr(data, "published_at", None)

    if requested_status is not None:
        status = _coerce_status(requested_status)
    else:
        is_active = bool(getattr(data, "active", False) or False)
        status = BlogPostStatus.published if is_active else BlogPostStatus.draft

    if status == BlogPostStatus.scheduled and not scheduled_at:
        raise BadRequestException(
            detail="scheduled_at is required when status is scheduled",
            error_code="BLOG_SCHEDULED_AT_REQUIRED",
        )

    is_active = status == BlogPostStatus.published
    if is_active and not published_at:
        published_at = datetime.now(timezone.utc)

    return status.value, is_active, published_at


def _apply_status_update(post: BlogPost, data: Any) -> None:
    """Apply status/active sync logic during an update.

    If ``status`` is provided it takes precedence; otherwise a provided
    ``active`` flag derives the new status. ``active`` is always kept in sync
    with ``status == published``.
    """
    requested_status = getattr(data, "status", None)
    requested_scheduled_at = getattr(data, "scheduled_at", None)
    requested_active = getattr(data, "active", None)

    if requested_status is not None:
        status = _coerce_status(requested_status)
        effective_scheduled_at = (
            requested_scheduled_at if requested_scheduled_at is not None else post.scheduled_at
        )
        if status == BlogPostStatus.scheduled and not effective_scheduled_at:
            raise BadRequestException(
                detail="scheduled_at is required when status is scheduled",
                error_code="BLOG_SCHEDULED_AT_REQUIRED",
            )
        post.status = status.value
        post.active = status == BlogPostStatus.published
        if status == BlogPostStatus.published and not post.published_at:
            post.published_at = datetime.now(timezone.utc)
    elif requested_active is not None:
        post.active = bool(requested_active)
        post.status = (
            BlogPostStatus.published.value if post.active else BlogPostStatus.draft.value
        )
        if post.active and not post.published_at:
            post.published_at = datetime.now(timezone.utc)

    if requested_scheduled_at is not None:
        post.scheduled_at = requested_scheduled_at


async def _get_or_create_categories(db: AsyncSession, identifiers: list[str]) -> list[BlogCategory]:
    if not identifiers:
        return []

    names_or_slugs = [str(x).strip() for x in identifiers if str(x).strip()]
    if not names_or_slugs:
        return []

    slugified = [_slugify(x) for x in names_or_slugs]
    stmt = select(BlogCategory).where(
        or_(BlogCategory.slug.in_(list(dict.fromkeys(names_or_slugs + slugified))), BlogCategory.name.in_(names_or_slugs))
    )
    result = await db.execute(stmt)
    existing = {c.slug: c for c in result.scalars().all()}

    categories: list[BlogCategory] = list(existing.values())
    for ident in names_or_slugs:
        slug = _slugify(ident)
        if slug not in existing:
            cat = BlogCategory(name=ident, slug=slug)
            db.add(cat)
            await db.flush()
            await db.refresh(cat)
            categories.append(cat)
            existing[slug] = cat
    return categories


async def _get_or_create_tags(db: AsyncSession, identifiers: list[str]) -> list[BlogTag]:
    if not identifiers:
        return []

    names_or_slugs = [str(x).strip() for x in identifiers if str(x).strip()]
    if not names_or_slugs:
        return []

    slugified = [_slugify(x) for x in names_or_slugs]
    stmt = select(BlogTag).where(
        or_(BlogTag.slug.in_(list(dict.fromkeys(names_or_slugs + slugified))), BlogTag.name.in_(names_or_slugs))
    )
    result = await db.execute(stmt)
    existing = {t.slug: t for t in result.scalars().all()}

    tags: list[BlogTag] = list(existing.values())
    for ident in names_or_slugs:
        slug = _slugify(ident)
        if slug not in existing:
            tag = BlogTag(name=ident, slug=slug)
            db.add(tag)
            await db.flush()
            await db.refresh(tag)
            tags.append(tag)
            existing[slug] = tag
    return tags


async def create_blog_post(db: AsyncSession, data, actor) -> BlogPostSchema:
    from app.schemas.blog import BlogPost as BlogPostSchema

    if actor.role != UserRole.admin.value:
        raise ForbiddenException(detail="Only admins can create blog posts")

    slug = _slugify(data.title)

    # Ensure slug uniqueness by appending numeric suffix if needed
    suffix = 1
    base_slug = slug
    while True:
        exists_stmt = select(func.count(BlogPost.id)).where(BlogPost.slug == slug)
        exists = (await db.execute(exists_stmt)).scalar()
        if not exists:
            break
        suffix += 1
        slug = f"{base_slug}-{suffix}"

    categories = await _get_or_create_categories(db, data.categories or [])
    tags = await _get_or_create_tags(db, data.tags or [])

    # Auto-compute reading analytics
    word_count = _compute_word_count(data.content)
    reading_time = _compute_reading_time(word_count)

    # Auto-generate meta fields if not provided
    meta_title = getattr(data, "meta_title", None) or _auto_meta_title(data.title)
    meta_description = getattr(data, "meta_description", None) or _auto_meta_description(
        getattr(data, "excerpt", None), data.content
    )
    og_image_url = getattr(data, "og_image_url", None) or getattr(data, "cover_image_url", None) or None
    if data.cover_image_url is not None and not ValidationUtils.is_absolute_url(data.cover_image_url):
        logger.warning("Non-absolute cover_image_url for blog post: %s", data.cover_image_url)
    if og_image_url is not None and not ValidationUtils.is_absolute_url(og_image_url):
        logger.warning("Non-absolute og_image_url for blog post: %s", og_image_url)

    # Serialize structured data for JSONB
    sources = _serialize_sources(getattr(data, "sources", None) or [])
    seo_metadata = _serialize_seo_metadata(getattr(data, "seo_metadata", None))

    # Determine status (and keep `active` in sync: active == (status == published)).
    status_value, is_active, published_at = _resolve_status_for_create(data)

    post = BlogPost(
        title=data.title,
        slug=slug,
        content=data.content,
        excerpt=data.excerpt,
        cover_image_url=data.cover_image_url,
        active=is_active,
        author_id=getattr(actor, "id", None),
        meta_title=meta_title,
        meta_description=meta_description,
        focus_keyword=getattr(data, "focus_keyword", None),
        canonical_url=getattr(data, "canonical_url", None),
        og_image_url=og_image_url,
        reading_time_minutes=reading_time,
        word_count=word_count,
        published_at=published_at,
        status=status_value,
        scheduled_at=getattr(data, "scheduled_at", None),
        sources=sources,
        seo_metadata=seo_metadata,
    )
    db.add(post)
    await db.flush()

    # Link categories and tags
    if categories:
        for c in categories:
            db.add(BlogPostCategory(post_id=post.id, category_id=c.id))
    if tags:
        for t in tags:
            db.add(BlogPostTag(post_id=post.id, tag_id=t.id))
    await db.flush()
    await db.refresh(post, ["categories", "tags"])

    return BlogPostSchema.model_validate(post)


async def get_blog_post(
    db: AsyncSession,
    identifier: str,
    include_inactive: bool = False,
) -> BlogPostSchema | None:
    from app.schemas.blog import BlogPost as BlogPostSchema

    cond = None
    try:
        # If identifier is an integer string, search by id
        ident_int = int(identifier)
        cond = BlogPost.id == ident_int
    except ValueError:
        cond = BlogPost.slug == identifier

    stmt = (
        select(BlogPost)
        .options(selectinload(BlogPost.categories), selectinload(BlogPost.tags))
        .where(cond)
    )
    if not include_inactive:
        # Public visibility: published status (back-compat: also accept active=true
        # for rows created before the status column existed).
        stmt = stmt.where(
            or_(
                BlogPost.status == BlogPostStatus.published.value,
                BlogPost.active.is_(True),
            )
        )

    result = await db.execute(stmt)
    post = result.scalar_one_or_none()
    if not post:
        return None
    return BlogPostSchema.model_validate(post)


@cached("blog:post", ttl=settings.CACHE_TTL_BLOG_POSTS, key_params=["identifier"])
async def get_blog_post_cached(
    db: AsyncSession,
    identifier: str,
) -> BlogPostSchema | None:
    """Cached wrapper — only caches active posts (include_inactive=False)."""
    return await get_blog_post(db, identifier, include_inactive=False)


@cached("blog:posts", ttl=settings.CACHE_TTL_BLOG_POSTS)
async def list_posts_cached(
    db: AsyncSession,
    *,
    q: str | None,
    categories: list[str] | None,
    tags: list[str] | None,
    cursor_payload: dict,
    limit: int,
) -> tuple[list[BlogPostSchema], dict | None, int | None]:
    """Cached wrapper for public (non-admin) blog post listing.

    Cache key includes all kwargs: q, categories, tags, cursor_payload, limit.
    with_total is always False for cached results (include_total=True bypasses cache
    via the uncached service call in the endpoint). Only active posts are cached.
    """
    return await list_blog_posts(
        db,
        q=q,
        categories=categories,
        tags=tags,
        cursor_payload=cursor_payload,
        limit=limit,
        with_total=False,
        include_inactive=False,
    )


@cached("blog:categories", ttl=settings.CACHE_TTL_BLOG_CATEGORIES)
async def list_categories_cached(
    db: AsyncSession,
    *,
    cursor_payload: dict,
    limit: int,
) -> tuple[list[BlogCategory], dict | None, int | None]:
    """Cached wrapper for public blog category listing.

    Cache key includes cursor_payload and limit. with_total is always False
    for cached results (include_total=True bypasses cache in the endpoint).
    """
    return await list_categories(db, cursor_payload=cursor_payload, limit=limit, with_total=False)


@cached("blog:tags", ttl=settings.CACHE_TTL_BLOG_TAGS)
async def list_tags_cached(
    db: AsyncSession,
    *,
    cursor_payload: dict,
    limit: int,
) -> tuple[list[BlogTag], dict | None, int | None]:
    """Cached wrapper for public blog tag listing.

    Cache key includes cursor_payload and limit. with_total is always False
    for cached results (include_total=True bypasses cache in the endpoint).
    """
    return await list_tags(db, cursor_payload=cursor_payload, limit=limit, with_total=False)


async def list_blog_posts(
    db: AsyncSession,
    q: str | None,
    categories: list[str] | None,
    tags: list[str] | None,
    cursor_payload: dict,
    limit: int = 20,
    with_total: bool = False,
    include_inactive: bool = False,
    status: str | None = None,
) -> tuple[list[BlogPostSchema], dict | None, int | None]:
    from app.schemas.blog import BlogPost as BlogPostSchema

    query = select(BlogPost).options(selectinload(BlogPost.categories), selectinload(BlogPost.tags))
    count_query = select(func.count(BlogPost.id))

    conditions: list[Any] = []

    if not include_inactive:
        # Public visibility: published status (back-compat: also accept active=true
        # for rows created before the status column existed).
        conditions.append(
            or_(
                BlogPost.status == BlogPostStatus.published.value,
                BlogPost.active.is_(True),
            )
        )

    # Admin status filter (only meaningful when include_inactive=True).
    if status:
        conditions.append(BlogPost.status == status)

    if q:
        like = f"%{q}%"
        conditions.append(or_(BlogPost.title.ilike(like), BlogPost.content.ilike(like)))

    # Category filter (ANY match)
    if categories:
        idents = [s.strip() for s in categories if s and s.strip()]
        if idents:
            cats_res = await execute_with_transient_retry(
                db,
                lambda: db.execute(
                    select(BlogCategory.id).where(
                        or_(BlogCategory.slug.in_(idents), BlogCategory.name.in_(idents))
                    )
                ),
                operation_name="blog_posts_category_lookup",
            )
            cat_ids = [row[0] for row in cats_res.fetchall()]
            if cat_ids:
                subq = select(BlogPostCategory.post_id).where(BlogPostCategory.category_id.in_(cat_ids))
                conditions.append(BlogPost.id.in_(subq))

    # Tag filter (ANY match)
    if tags:
        idents = [s.strip() for s in tags if s and s.strip()]
        if idents:
            tags_res = await execute_with_transient_retry(
                db,
                lambda: db.execute(
                    select(BlogTag.id).where(or_(BlogTag.slug.in_(idents), BlogTag.name.in_(idents)))
                ),
                operation_name="blog_posts_tag_lookup",
            )
            tag_ids = [row[0] for row in tags_res.fetchall()]
            if tag_ids:
                subq = select(BlogPostTag.post_id).where(BlogPostTag.tag_id.in_(tag_ids))
                conditions.append(BlogPost.id.in_(subq))

    if conditions:
        query = query.where(and_(*conditions))
        count_query = count_query.where(and_(*conditions))

    # Count BEFORE applying keyset predicate (count the full filtered set)
    count_total: int | None = None
    if with_total:
        count_total = (
            await execute_with_transient_retry(
                db,
                lambda: db.execute(count_query),
                operation_name="blog_posts_count",
            )
        ).scalar_one() or 0

    # Apply keyset predicate for cursor-based pagination
    predicate = keyset_filter(BlogPost.created_at, BlogPost.id, cursor_payload, descending=True)
    if predicate is not None:
        query = query.where(predicate)

    query = query.order_by(BlogPost.created_at.desc(), BlogPost.id.desc()).limit(limit + 1)

    result = await execute_with_transient_retry(
        db,
        lambda: db.execute(query),
        operation_name="blog_posts_query",
    )
    rows = list(result.scalars().all())

    next_payload: dict | None = None
    if len(rows) > limit:
        rows = rows[:limit]
        next_payload = keyset_payload(keyset_sort_value(rows[-1].created_at), rows[-1].id)

    return [BlogPostSchema.model_validate(i) for i in rows], next_payload, count_total


# Category CRUD operations
async def create_category(db: AsyncSession, name: str, description: str | None = None) -> BlogCategory:
    """Create a new blog category."""
    slug = _slugify(name)

    # Check if category already exists
    existing_stmt = select(BlogCategory).where(
        or_(BlogCategory.slug == slug, BlogCategory.name == name)
    )
    existing = (await db.execute(existing_stmt)).scalar_one_or_none()
    if existing:
        raise ConflictException(
            detail=f"Category with name '{name}' or slug '{slug}' already exists"
        )

    category = BlogCategory(name=name, slug=slug, description=description)
    db.add(category)
    await db.commit()
    await db.refresh(category)
    return category


async def get_category(db: AsyncSession, identifier: str) -> BlogCategory | None:
    """Get category by ID or slug."""
    try:
        # Try to parse as ID
        ident_int = int(identifier)
        stmt = select(BlogCategory).where(BlogCategory.id == ident_int)
    except ValueError:
        # Treat as slug
        stmt = select(BlogCategory).where(BlogCategory.slug == identifier)

    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def list_categories(
    db: AsyncSession,
    cursor_payload: dict,
    limit: int = 20,
    with_total: bool = False,
) -> tuple[list[BlogCategory], dict | None, int | None]:
    """List all categories with keyset cursor pagination (ASC name order)."""
    count_total: int | None = None
    if with_total:
        count_stmt = select(func.count(BlogCategory.id))
        count_total = (await db.execute(count_stmt)).scalar_one() or 0

    stmt = select(BlogCategory)
    predicate = keyset_filter(BlogCategory.name, BlogCategory.id, cursor_payload, descending=False)
    if predicate is not None:
        stmt = stmt.where(predicate)
    stmt = stmt.order_by(BlogCategory.name.asc(), BlogCategory.id.asc()).limit(limit + 1)

    result = await db.execute(stmt)
    rows = list(result.scalars().all())

    next_payload: dict | None = None
    if len(rows) > limit:
        rows = rows[:limit]
        next_payload = keyset_payload(keyset_sort_value(rows[-1].name), rows[-1].id)

    return rows, next_payload, count_total


async def update_category(db: AsyncSession, identifier: str, name: str | None = None, description: str | None = None) -> BlogCategory:
    """Update category by ID or slug."""
    category = await get_category(db, identifier)
    if not category:
        raise CategoryNotFoundException()

    if name:
        # Check for conflicts
        existing_stmt = select(BlogCategory).where(
            and_(
                or_(BlogCategory.slug == _slugify(name), BlogCategory.name == name),
                BlogCategory.id != category.id
            )
        )
        existing = (await db.execute(existing_stmt)).scalar_one_or_none()
        if existing:
            raise ConflictException(
                detail=f"Category with name '{name}' already exists"
            )

        category.name = name
        category.slug = _slugify(name)

    if description is not None:
        category.description = description

    await db.commit()
    await db.refresh(category)
    return category


async def delete_category(db: AsyncSession, identifier: str) -> bool:
    """Delete category by ID or slug."""
    category = await get_category(db, identifier)
    if not category:
        raise CategoryNotFoundException()

    await db.delete(category)
    await db.commit()
    return True


# Tag CRUD operations
async def create_tag(db: AsyncSession, name: str) -> BlogTag:
    """Create a new blog tag."""
    slug = _slugify(name)

    # Check if tag already exists
    existing_stmt = select(BlogTag).where(
        or_(BlogTag.slug == slug, BlogTag.name == name)
    )
    existing = (await db.execute(existing_stmt)).scalar_one_or_none()
    if existing:
        raise ConflictException(
            detail=f"Tag with name '{name}' or slug '{slug}' already exists"
        )

    tag = BlogTag(name=name, slug=slug)
    db.add(tag)
    await db.commit()
    await db.refresh(tag)
    return tag


async def get_tag(db: AsyncSession, identifier: str) -> BlogTag | None:
    """Get tag by ID or slug."""
    try:
        # Try to parse as ID
        ident_int = int(identifier)
        stmt = select(BlogTag).where(BlogTag.id == ident_int)
    except ValueError:
        # Treat as slug
        stmt = select(BlogTag).where(BlogTag.slug == identifier)

    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def list_tags(
    db: AsyncSession,
    cursor_payload: dict,
    limit: int = 20,
    with_total: bool = False,
) -> tuple[list[BlogTag], dict | None, int | None]:
    """List all tags with keyset cursor pagination (ASC name order)."""
    count_total: int | None = None
    if with_total:
        count_stmt = select(func.count(BlogTag.id))
        count_total = (await db.execute(count_stmt)).scalar_one() or 0

    stmt = select(BlogTag)
    predicate = keyset_filter(BlogTag.name, BlogTag.id, cursor_payload, descending=False)
    if predicate is not None:
        stmt = stmt.where(predicate)
    stmt = stmt.order_by(BlogTag.name.asc(), BlogTag.id.asc()).limit(limit + 1)

    result = await db.execute(stmt)
    rows = list(result.scalars().all())

    next_payload: dict | None = None
    if len(rows) > limit:
        rows = rows[:limit]
        next_payload = keyset_payload(keyset_sort_value(rows[-1].name), rows[-1].id)

    return rows, next_payload, count_total


async def update_tag(db: AsyncSession, identifier: str, name: str) -> BlogTag:
    """Update tag by ID or slug."""
    tag = await get_tag(db, identifier)
    if not tag:
        raise TagNotFoundException()

    # Check for conflicts
    existing_stmt = select(BlogTag).where(
        and_(
            or_(BlogTag.slug == _slugify(name), BlogTag.name == name),
            BlogTag.id != tag.id
        )
    )
    existing = (await db.execute(existing_stmt)).scalar_one_or_none()
    if existing:
        raise ConflictException(
            detail=f"Tag with name '{name}' already exists"
        )

    tag.name = name
    tag.slug = _slugify(name)

    await db.commit()
    await db.refresh(tag)
    return tag


async def delete_tag(db: AsyncSession, identifier: str) -> bool:
    """Delete tag by ID or slug."""
    tag = await get_tag(db, identifier)
    if not tag:
        raise TagNotFoundException()

    await db.delete(tag)
    await db.commit()
    return True


# Blog Post CRUD operations (additional)
async def update_blog_post(db: AsyncSession, identifier: str, data, actor) -> BlogPostSchema:
    """Update blog post by ID or slug."""
    from app.schemas.blog import BlogPost as BlogPostSchema

    if actor.role != UserRole.admin.value:
        raise ForbiddenException(detail="Only admins can update blog posts")

    # Get the post
    cond = None
    try:
        ident_int = int(identifier)
        cond = BlogPost.id == ident_int
    except ValueError:
        cond = BlogPost.slug == identifier

    stmt = select(BlogPost).where(cond)
    result = await db.execute(stmt)
    post = result.scalar_one_or_none()

    if not post:
        raise BlogNotFoundException()

    # Update fields
    if data.title:
        post.title = data.title
        # Regenerate slug if title changed
        slug = _slugify(data.title)
        if slug != post.slug:
            # Ensure new slug is unique
            suffix = 1
            base_slug = slug
            while True:
                exists_stmt = select(func.count(BlogPost.id)).where(and_(BlogPost.slug == slug, BlogPost.id != post.id))
                exists = (await db.execute(exists_stmt)).scalar()
                if not exists:
                    break
                suffix += 1
                slug = f"{base_slug}-{suffix}"
            post.slug = slug

    if data.content:
        post.content = data.content
        # Recompute reading analytics when content changes
        post.word_count = _compute_word_count(data.content)
        post.reading_time_minutes = _compute_reading_time(post.word_count)
    if data.excerpt is not None:
        post.excerpt = data.excerpt
    if data.cover_image_url is not None:
        if not ValidationUtils.is_absolute_url(data.cover_image_url):
            logger.warning("Non-absolute cover_image_url for blog post %s: %s", post.id, data.cover_image_url)
        post.cover_image_url = data.cover_image_url
    # Status / active sync (status takes precedence over the legacy active flag).
    _apply_status_update(post, data)

    # Update SEO fields if provided
    if getattr(data, "meta_title", None) is not None:
        post.meta_title = data.meta_title
    if getattr(data, "meta_description", None) is not None:
        post.meta_description = data.meta_description
    if getattr(data, "focus_keyword", None) is not None:
        post.focus_keyword = data.focus_keyword
    if getattr(data, "canonical_url", None) is not None:
        post.canonical_url = data.canonical_url
    if getattr(data, "og_image_url", None) is not None:
        if not ValidationUtils.is_absolute_url(data.og_image_url):
            logger.warning("Non-absolute og_image_url for blog post %s: %s", post.id, data.og_image_url)
        post.og_image_url = data.og_image_url
    if getattr(data, "sources", None) is not None:
        post.sources = _serialize_sources(data.sources)
    if getattr(data, "seo_metadata", None) is not None:
        post.seo_metadata = _serialize_seo_metadata(data.seo_metadata)
    if getattr(data, "published_at", None) is not None:
        post.published_at = data.published_at

    # Update categories and tags if provided
    if data.categories is not None:
        # Remove existing categories
        delete_rel_stmt = select(BlogPostCategory).where(BlogPostCategory.post_id == post.id)
        existing_rels = (await db.execute(delete_rel_stmt)).scalars().all()
        for rel in existing_rels:
            await db.delete(rel)

        # Add new categories
        categories = await _get_or_create_categories(db, data.categories)
        for c in categories:
            db.add(BlogPostCategory(post_id=post.id, category_id=c.id))

    if data.tags is not None:
        # Remove existing tags
        delete_tag_rel_stmt = select(BlogPostTag).where(BlogPostTag.post_id == post.id)
        existing_tag_rels = (await db.execute(delete_tag_rel_stmt)).scalars().all()
        for tag_rel in existing_tag_rels:
            await db.delete(tag_rel)

        # Add new tags
        tags = await _get_or_create_tags(db, data.tags)
        for t in tags:
            db.add(BlogPostTag(post_id=post.id, tag_id=t.id))

    await db.commit()
    # Full column refresh so server-side `onupdate` fields (e.g. updated_at) are
    # loaded and do not trigger lazy-load IO during serialization.
    await db.refresh(post)
    await db.refresh(post, ["categories", "tags"])

    return BlogPostSchema.model_validate(post)


async def delete_blog_post(db: AsyncSession, identifier: str, actor) -> bool:
    """Delete blog post by ID or slug."""
    if actor.role != UserRole.admin.value:
        raise ForbiddenException(detail="Only admins can delete blog posts")

    # Get the post
    cond = None
    try:
        ident_int = int(identifier)
        cond = BlogPost.id == ident_int
    except ValueError:
        cond = BlogPost.slug == identifier

    stmt = select(BlogPost).where(cond)
    result = await db.execute(stmt)
    post = result.scalar_one_or_none()

    if not post:
        raise BlogNotFoundException()

    await db.delete(post)
    await db.commit()
    return True


# --------------------------------------------------------------------------- #
# Draft / preview / scheduling helpers
# --------------------------------------------------------------------------- #


async def generate_preview_token(db: AsyncSession, post_id: int) -> BlogPost:
    """Generate (or rotate) a preview token for a blog post.

    The token allows public access to a post of any status via the
    ``GET /posts/preview/{token}`` endpoint, enabling draft sharing for review.
    """
    stmt = select(BlogPost).where(BlogPost.id == post_id)
    post = (await db.execute(stmt)).scalar_one_or_none()
    if not post:
        raise BlogNotFoundException()

    post.preview_token = secrets.token_urlsafe(16)
    await db.flush()
    await db.refresh(post)
    return post


async def get_post_by_preview_token(db: AsyncSession, token: str) -> BlogPost | None:
    """Fetch a blog post by its preview token (works for any status)."""
    if not token:
        return None
    stmt = (
        select(BlogPost)
        .options(selectinload(BlogPost.categories), selectinload(BlogPost.tags))
        .where(BlogPost.preview_token == token)
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def publish_scheduled_posts(db: AsyncSession) -> int:
    """Publish all scheduled posts whose ``scheduled_at`` has passed.

    Returns the number of posts published. ``active`` is kept in sync with the
    new ``published`` status.
    """
    now = datetime.now(timezone.utc)
    stmt = (
        select(BlogPost)
        .where(
            BlogPost.status == BlogPostStatus.scheduled.value,
            BlogPost.scheduled_at.is_not(None),
            BlogPost.scheduled_at <= now,
        )
    )
    posts = list((await db.execute(stmt)).scalars().all())
    for post in posts:
        post.status = BlogPostStatus.published.value
        post.active = True
        if not post.published_at:
            post.published_at = now
    if posts:
        await db.flush()
    return len(posts)
