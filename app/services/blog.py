from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_, func
from sqlalchemy.orm import selectinload
from typing import Optional, List, Tuple
from app.core.logging import get_logger
from app.models.blogs import BlogPost, BlogCategory, BlogTag, BlogPostCategory, BlogPostTag

logger = get_logger(__name__)


def _slugify(value: str) -> str:
    import re
    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9\-\s]", "", value)
    value = re.sub(r"\s+", "-", value)
    value = re.sub(r"-+", "-", value)
    return value


async def _get_or_create_categories(db: AsyncSession, identifiers: List[str]) -> List[BlogCategory]:
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

    categories: List[BlogCategory] = list(existing.values())
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


async def _get_or_create_tags(db: AsyncSession, identifiers: List[str]) -> List[BlogTag]:
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

    tags: List[BlogTag] = list(existing.values())
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


async def create_blog_post(db: AsyncSession, data, actor) -> "app.schemas.blog.BlogPost":
    from app.schemas.blog import BlogPost as BlogPostSchema

    if actor.role != "admin":
        from fastapi import HTTPException, status
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only admins can create blog posts")

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

    post = BlogPost(
        title=data.title,
        slug=slug,
        content=data.content,
        excerpt=data.excerpt,
        cover_image_url=data.cover_image_url,
        author_id=getattr(actor, "id", None),
    )
    db.add(post)
    await db.flush()
    await db.refresh(post)

    # Link categories and tags
    if categories:
        for c in categories:
            db.add(BlogPostCategory(post_id=post.id, category_id=c.id))
    if tags:
        for t in tags:
            db.add(BlogPostTag(post_id=post.id, tag_id=t.id))
    await db.flush()

    # Reload with relationships
    result = await db.execute(
        select(BlogPost)
        .options(selectinload(BlogPost.categories), selectinload(BlogPost.tags))
        .where(BlogPost.id == post.id)
    )
    created = result.scalar_one()
    return BlogPostSchema.model_validate(created)


async def get_blog_post(db: AsyncSession, identifier: str) -> Optional["app.schemas.blog.BlogPost"]:
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
    result = await db.execute(stmt)
    post = result.scalar_one_or_none()
    if not post:
        return None
    return BlogPostSchema.model_validate(post)


async def list_blog_posts(
    db: AsyncSession,
    q: Optional[str],
    categories: Optional[List[str]],
    tags: Optional[List[str]],
    page: int,
    limit: int,
) -> Tuple[List["app.schemas.blog.BlogPost"], int]:
    from app.schemas.blog import BlogPost as BlogPostSchema

    query = select(BlogPost).options(selectinload(BlogPost.categories), selectinload(BlogPost.tags))
    count_query = select(func.count(BlogPost.id))

    conditions = []

    if q:
        like = f"%{q}%"
        conditions.append(or_(BlogPost.title.ilike(like), BlogPost.content.ilike(like)))

    # Category filter (ANY match)
    if categories:
        idents = [s.strip() for s in categories if s and s.strip()]
        if idents:
            cats_res = await db.execute(
                select(BlogCategory.id).where(or_(BlogCategory.slug.in_(idents), BlogCategory.name.in_(idents)))
            )
            cat_ids = [row[0] for row in cats_res.fetchall()]
            if cat_ids:
                subq = select(BlogPostCategory.post_id).where(BlogPostCategory.category_id.in_(cat_ids))
                conditions.append(BlogPost.id.in_(subq))

    # Tag filter (ANY match)
    if tags:
        idents = [s.strip() for s in tags if s and s.strip()]
        if idents:
            tags_res = await db.execute(
                select(BlogTag.id).where(or_(BlogTag.slug.in_(idents), BlogTag.name.in_(idents)))
            )
            tag_ids = [row[0] for row in tags_res.fetchall()]
            if tag_ids:
                subq = select(BlogPostTag.post_id).where(BlogPostTag.tag_id.in_(tag_ids))
                conditions.append(BlogPost.id.in_(subq))

    if conditions:
        query = query.where(and_(*conditions))
        count_query = count_query.where(and_(*conditions))

    query = query.order_by(BlogPost.created_at.desc()).offset((page - 1) * limit).limit(limit)

    result = await db.execute(query)
    items = result.scalars().all()

    total = (await db.execute(count_query)).scalar() or 0

    return [BlogPostSchema.model_validate(i) for i in items], int(total)
