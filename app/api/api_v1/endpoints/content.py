"""Public read API for generated content: one entity, and a manifest of what is served."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Path, Query, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.exceptions import NotFoundException
from app.models.content import SERVED_STATUSES, ContentBlock
from app.schemas.content import ContentBlockOut, ContentManifest, EntityType, Locale

router = APIRouter()

# Edge caches may hold a block for an hour and serve it stale for a day while revalidating.
CACHE_HEADER = "public, max-age=300, s-maxage=3600, stale-while-revalidate=86400"


@router.get("/manifest", response_model=ContentManifest, summary="List served content")
async def content_manifest(
    response: Response,
    entity_type: EntityType | None = Query(None),
    limit: int = Query(5000, ge=1, le=20000),
    db: AsyncSession = Depends(get_db),
) -> ContentManifest:
    """Every served (entity, locale) with its indexable flag and last update. For sitemaps and builds.

    Returns at most ``limit`` rows (default 5,000). ``truncated`` is true when there are more."""
    stmt = (
        select(
            ContentBlock.entity_type, ContentBlock.slug, ContentBlock.locale,
            ContentBlock.indexable, ContentBlock.updated_at,
        )
        .where(ContentBlock.review_status.in_(SERVED_STATUSES))
        .order_by(ContentBlock.entity_type, ContentBlock.slug, ContentBlock.locale)
        .limit(limit + 1)
    )
    if entity_type:
        stmt = stmt.where(ContentBlock.entity_type == entity_type)
    rows = [dict(r._mapping) for r in (await db.execute(stmt)).all()]
    response.headers["Cache-Control"] = CACHE_HEADER
    return ContentManifest.model_validate({"items": rows[:limit], "truncated": len(rows) > limit})


@router.get("/{entity_type}/{slug}", response_model=ContentBlockOut, summary="Get generated content")
async def get_content(
    response: Response,
    entity_type: EntityType,
    slug: str = Path(..., max_length=200),
    locale: Locale = Query("en"),
    db: AsyncSession = Depends(get_db),
) -> ContentBlock:
    row = (
        await db.execute(
            select(ContentBlock).where(
                ContentBlock.entity_type == entity_type,
                ContentBlock.slug == slug,
                ContentBlock.locale == locale,
                ContentBlock.review_status.in_(SERVED_STATUSES),
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise NotFoundException("No content for this entity", error_code="CONTENT_NOT_FOUND")
    response.headers["Cache-Control"] = CACHE_HEADER
    return row
