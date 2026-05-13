from __future__ import annotations

import re as _re
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.core.cache import cached
from app.core.db_resilience import execute_with_transient_retry
from app.core.exceptions import (
    BlogNotFoundException,
    CategoryNotFoundException,
    ConflictException,
    ForbiddenException,
    TagNotFoundException,
)
from app.core.logging import get_logger
from app.models.blogs import BlogCategory, BlogPost, BlogPostCategory, BlogPostTag, BlogTag
from app.models.enums import UserRole

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
    return dict(seo_metadata) if isinstance(seo_metadata, dict) else {}


async def _get_or_create_categories(db: AsyncSession, identifiers: list[str]) -> list[BlogCategory]:
    if not identifiers:
        return []

    names_or_slugs = [str(x).strip() for x in identifiers if str(x).strip()]
    if not names_or_slugs:
        return []

    stmt = select(BlogCategory).where(
        or_(BlogCategory.slug.in_(names_or_slugs), BlogCategory.name.in_(names_or_slugs))
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

    stmt = select(BlogTag).where(
        or_(BlogTag.slug.in_(names_or_slugs), BlogTag.name.in_(names_or_slugs))
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

    # Serialize structured data for JSONB
    sources = _serialize_sources(getattr(data, "sources", None) or [])
    seo_metadata = _serialize_seo_metadata(getattr(data, "seo_metadata", None))

    # Determine published_at
    is_active = getattr(data, "active", False) or False
    published_at = getattr(data, "published_at", None)
    if is_active and not published_at:
        published_at = datetime.now(timezone.utc)

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
        stmt = stmt.where(BlogPost.active.is_(True))

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


async def list_blog_posts(
    db: AsyncSession,
    q: str | None,
    categories: list[str] | None,
    tags: list[str] | None,
    page: int,
    limit: int,
    include_inactive: bool = False,
) -> tuple[list[BlogPostSchema], int]:
    from app.schemas.blog import BlogPost as BlogPostSchema

    query = select(BlogPost).options(selectinload(BlogPost.categories), selectinload(BlogPost.tags))
    count_query = select(func.count(BlogPost.id))

    conditions: list[Any] = []

    if not include_inactive:
        conditions.append(BlogPost.active.is_(True))

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

    query = query.order_by(BlogPost.created_at.desc()).offset((page - 1) * limit).limit(limit)

    result = await execute_with_transient_retry(
        db,
        lambda: db.execute(query),
        operation_name="blog_posts_query",
    )
    items = result.scalars().all()

    total = (
        await execute_with_transient_retry(
            db,
            lambda: db.execute(count_query),
            operation_name="blog_posts_count",
        )
    ).scalar() or 0

    return [BlogPostSchema.model_validate(i) for i in items], int(total)


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


async def list_categories(db: AsyncSession, page: int = 1, limit: int = 100) -> tuple[list[BlogCategory], int]:
    """List all categories with pagination."""
    count_stmt = select(func.count(BlogCategory.id))
    total = (await db.execute(count_stmt)).scalar() or 0

    stmt = select(BlogCategory).order_by(BlogCategory.name).offset((page - 1) * limit).limit(limit)
    result = await db.execute(stmt)
    categories = result.scalars().all()

    return list(categories), int(total)


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


async def list_tags(db: AsyncSession, page: int = 1, limit: int = 100) -> tuple[list[BlogTag], int]:
    """List all tags with pagination."""
    count_stmt = select(func.count(BlogTag.id))
    total = (await db.execute(count_stmt)).scalar() or 0

    stmt = select(BlogTag).order_by(BlogTag.name).offset((page - 1) * limit).limit(limit)
    result = await db.execute(stmt)
    tags = result.scalars().all()

    return list(tags), int(total)


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
        post.cover_image_url = data.cover_image_url
    if getattr(data, "active", None) is not None:
        post.active = bool(data.active)
        # Set published_at when first activating
        if post.active and not post.published_at:
            post.published_at = datetime.now(timezone.utc)

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
