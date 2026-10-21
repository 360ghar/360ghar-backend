"""Content engine admin: a cron-triggered run, and the admin review queue."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.api_v1.dependencies.auth import get_current_admin
from app.api.api_v1.dependencies.cron import require_cron_secret
from app.config import settings
from app.core.database import get_db
from app.core.exceptions import ConflictException, NotFoundException, ServiceUnavailableException
from app.models.content import ContentBlock
from app.models.users import User
from app.schemas.content import (
    ContentReviewItem,
    ContentRunRequest,
    ContentRunResult,
    ContentStatusUpdate,
    EntityType,
    Locale,
    MarketDigestResult,
)
from app.schemas.pagination import (
    CursorPage,
    CursorParams,
    build_cursor_page,
    keyset_filter,
    trim_keyset_lookahead,
    validate_keyset_payload,
)
from app.services.content import digest, runner
from app.services.content.facts import MIN_FACTS_FOR_INDEX
from app.services.content.runner import make_provider

router = APIRouter()

REVIEW_STATUSES = ("auto", "needs_review", "approved", "rejected", "failed")


@router.post(
    "/run",
    response_model=ContentRunResult,
    summary="Generate content for changed entities (cron)",
    dependencies=[Depends(require_cron_secret)],
)
async def run_content(body: ContentRunRequest, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    """One bounded batch. Entities whose facts are unchanged are skipped, so repeating a call
    is cheap and safe. Call again with ``next_after`` until ``done`` is true. Overlapping calls
    only waste quota: each result is an upsert on (entity, slug, locale)."""
    try:
        provider = make_provider()
    except ValueError as exc:
        raise ServiceUnavailableException(str(exc), error_code="AI_NOT_CONFIGURED") from exc
    try:
        stats = await runner.run_batch(
            db,
            provider,
            entity_type=body.entity_type,
            locales=list(body.locales),
            max_entities=body.max_entities,
            max_calls=body.max_entities * len(body.locales) * runner.MAX_ATTEMPTS,
            max_seconds=body.max_seconds,
            min_interval=settings.CONTENT_MIN_CALL_INTERVAL_S,
            after=body.after,
            slugs=body.slugs,
            city=body.city,
            force=body.force,
            retry_failed=body.retry_failed,
        )
    finally:
        await provider.close()
    return stats.as_dict()


@router.post(
    "/market-digest",
    response_model=MarketDigestResult,
    summary="Write the weekly market digest (cron)",
    dependencies=[Depends(require_cron_secret)],
)
async def run_market_digest(db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    """Build the digest from data-hub changes in the last 7 days. Skips with fewer than 3 changes.
    Saves a blog post: published when it validates, otherwise a draft tagged needs-review.
    Calling twice in one week saves one post."""
    try:
        provider = make_provider()
    except ValueError as exc:
        raise ServiceUnavailableException(str(exc), error_code="AI_NOT_CONFIGURED") from exc
    try:
        return await digest.generate_market_digest(
            db, provider, throttle=runner.make_throttle(settings.CONTENT_MIN_CALL_INTERVAL_S)
        )
    finally:
        await provider.close()


@router.get(
    "/review",
    response_model=CursorPage[ContentReviewItem],
    summary="List content for review (admin)",
)
async def review_list(
    page: CursorParams = Depends(),
    review_status: str | None = Query(None, pattern="^(auto|needs_review|approved|rejected|failed)$"),
    entity_type: EntityType | None = Query(None),
    locale: Locale | None = Query(None),
    _: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Newest first. Filter by review status, entity type or locale."""
    binding: dict[str, Any] = {"review_status": review_status, "entity_type": entity_type, "locale": locale}
    cursor = page.decoded(binding)
    validate_keyset_payload(cursor, "datetime", id_kind="int8")
    stmt = select(ContentBlock).order_by(ContentBlock.updated_at.desc(), ContentBlock.id.desc())
    for column, value in (
        (ContentBlock.review_status, review_status),
        (ContentBlock.entity_type, entity_type),
        (ContentBlock.locale, locale),
    ):
        if value:
            stmt = stmt.where(column == value)
    total = None
    if page.include_total:
        total = (await db.execute(select(func.count()).select_from(stmt.order_by(None).subquery()))).scalar_one()
    predicate = keyset_filter(ContentBlock.updated_at, ContentBlock.id, cursor, descending=True)
    if predicate is not None:
        stmt = stmt.where(predicate)
    rows = list((await db.execute(stmt.limit(page.limit + 1))).scalars().all())
    items, next_payload = trim_keyset_lookahead(
        rows, limit=page.limit, sort_value=lambda r: r.updated_at, item_id=lambda r: r.id
    )
    return build_cursor_page(
        [ContentReviewItem.model_validate(r) for r in items],
        limit=page.limit,
        next_payload=next_payload,
        total=total,
        filters=binding,
    )


@router.patch(
    "/{block_id}/status",
    response_model=ContentReviewItem,
    summary="Approve or reject a content block (admin)",
)
async def update_status(
    block_id: int,
    body: ContentStatusUpdate,
    _: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> ContentBlock:
    """Approve serves the block. It is indexable only with enough verified facts. A failed block
    has invalid text and cannot be approved: run it again instead."""
    block = await db.get(ContentBlock, block_id)
    if block is None:
        raise NotFoundException("Content block not found", error_code="CONTENT_NOT_FOUND")
    if block.review_status == "failed" and body.review_status == "approved":
        raise ConflictException("A failed block cannot be approved", error_code="CONTENT_FAILED")
    block.review_status = body.review_status
    block.indexable = body.review_status == "approved" and block.fact_count >= MIN_FACTS_FOR_INDEX and block.key_fact
    await db.commit()
    await db.refresh(block)
    return block
