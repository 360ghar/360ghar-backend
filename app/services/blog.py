from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_, func
from sqlalchemy.orm import selectinload
from typing import Optional, List, Tuple
from app.core.logging import get_logger
from app.models.blogs import BlogPost, BlogCategory, BlogTag, BlogPostCategory, BlogPostTag
from app.models.enums import UserRole

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

    if actor.role != UserRole.admin.value:
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
        active=getattr(data, "active", False) or False,
        author_id=getattr(actor, "id", None),
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
) -> Optional["app.schemas.blog.BlogPost"]:
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


async def list_blog_posts(
    db: AsyncSession,
    q: Optional[str],
    categories: Optional[List[str]],
    tags: Optional[List[str]],
    page: int,
    limit: int,
    include_inactive: bool = False,
) -> Tuple[List["app.schemas.blog.BlogPost"], int]:
    from app.schemas.blog import BlogPost as BlogPostSchema

    query = select(BlogPost).options(selectinload(BlogPost.categories), selectinload(BlogPost.tags))
    count_query = select(func.count(BlogPost.id))

    conditions = []

    if not include_inactive:
        conditions.append(BlogPost.active.is_(True))

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


# Category CRUD operations
async def create_category(db: AsyncSession, name: str, description: Optional[str] = None) -> BlogCategory:
    """Create a new blog category."""
    slug = _slugify(name)

    # Check if category already exists
    existing_stmt = select(BlogCategory).where(
        or_(BlogCategory.slug == slug, BlogCategory.name == name)
    )
    existing = (await db.execute(existing_stmt)).scalar_one_or_none()
    if existing:
        from fastapi import HTTPException, status
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Category with name '{name}' or slug '{slug}' already exists"
        )

    category = BlogCategory(name=name, slug=slug, description=description)
    db.add(category)
    await db.commit()
    await db.refresh(category)
    return category


async def get_category(db: AsyncSession, identifier: str) -> Optional[BlogCategory]:
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


async def list_categories(db: AsyncSession, page: int = 1, limit: int = 100) -> Tuple[List[BlogCategory], int]:
    """List all categories with pagination."""
    count_stmt = select(func.count(BlogCategory.id))
    total = (await db.execute(count_stmt)).scalar() or 0

    stmt = select(BlogCategory).order_by(BlogCategory.name).offset((page - 1) * limit).limit(limit)
    result = await db.execute(stmt)
    categories = result.scalars().all()

    return list(categories), int(total)


async def update_category(db: AsyncSession, identifier: str, name: Optional[str] = None, description: Optional[str] = None) -> BlogCategory:
    """Update category by ID or slug."""
    category = await get_category(db, identifier)
    if not category:
        from fastapi import HTTPException, status
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Category not found")

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
            from fastapi import HTTPException, status
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
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
        from fastapi import HTTPException, status
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Category not found")

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
        from fastapi import HTTPException, status
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Tag with name '{name}' or slug '{slug}' already exists"
        )

    tag = BlogTag(name=name, slug=slug)
    db.add(tag)
    await db.commit()
    await db.refresh(tag)
    return tag


async def get_tag(db: AsyncSession, identifier: str) -> Optional[BlogTag]:
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


async def list_tags(db: AsyncSession, page: int = 1, limit: int = 100) -> Tuple[List[BlogTag], int]:
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
        from fastapi import HTTPException, status
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tag not found")

    # Check for conflicts
    existing_stmt = select(BlogTag).where(
        and_(
            or_(BlogTag.slug == _slugify(name), BlogTag.name == name),
            BlogTag.id != tag.id
        )
    )
    existing = (await db.execute(existing_stmt)).scalar_one_or_none()
    if existing:
        from fastapi import HTTPException, status
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
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
        from fastapi import HTTPException, status
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tag not found")

    await db.delete(tag)
    await db.commit()
    return True


# Blog Post CRUD operations (additional)
async def update_blog_post(db: AsyncSession, identifier: str, data, actor) -> "app.schemas.blog.BlogPost":
    """Update blog post by ID or slug."""
    from app.schemas.blog import BlogPost as BlogPostSchema

    if actor.role != UserRole.admin.value:
        from fastapi import HTTPException, status
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only admins can update blog posts")

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
        from fastapi import HTTPException, status
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Blog post not found")

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
    if data.excerpt is not None:
        post.excerpt = data.excerpt
    if data.cover_image_url is not None:
        post.cover_image_url = data.cover_image_url
    if getattr(data, "active", None) is not None:
        post.active = bool(data.active)

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
        delete_rel_stmt = select(BlogPostTag).where(BlogPostTag.post_id == post.id)
        existing_rels = (await db.execute(delete_rel_stmt)).scalars().all()
        for rel in existing_rels:
            await db.delete(rel)

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
        from fastapi import HTTPException, status
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only admins can delete blog posts")

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
        from fastapi import HTTPException, status
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Blog post not found")

    await db.delete(post)
    await db.commit()
    return True
