"""Bounded, resumable content generation.

One run walks entities in slug order from a cursor, skips any whose fact hash is
unchanged, and stops at a call, time or provider limit. State lives in content_blocks,
so a stopped run resumes by calling again with the returned ``next_after``.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.content import SERVED_STATUSES, ContentBlock, Locality
from app.models.enums import PropertyStatus
from app.models.properties import Property
from app.services.ai.base import AIProvider, AIProviderConfig, AIProviderError
from app.services.content import dedupe, validator
from app.services.content.facts import FactSheet, build_locality_sheet, build_property_sheet
from app.services.content.prompts import PROMPT_VERSION, SCHEMAS, build_messages

logger = get_logger(__name__)

MAX_ATTEMPTS = 3  # first try plus two retries with the errors fed back
MAX_CONSECUTIVE_PROVIDER_ERRORS = 3
# A sheet with fewer facts cannot support a 40-word summary without padding. No model call.
MIN_FACTS_TO_GENERATE = 3
ENTITY_TYPES = ("locality", "property")

# Optional per-type step that adds to the body after validation (property image alt text).
# It returns the extra body keys and the number of model calls it made.
Throttle = Callable[[], Awaitable[None]]
Enricher = Callable[
    [AsyncSession, AIProvider, FactSheet, str, Throttle], Awaitable[tuple[dict[str, Any], int]]
]


def _enricher(entity_type: str) -> Enricher | None:
    if entity_type == "property":
        from app.services.content.property_summary import enrich_property

        return enrich_property
    return None


@dataclass
class RunStats:
    generated: int = 0
    skipped: int = 0
    thin: int = 0
    failed: int = 0
    needs_review: int = 0
    rejected: int = 0
    calls: int = 0
    provider_errors: int = 0
    done: bool = False
    next_after: str | None = None
    stopped_reason: str | None = None
    items: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Generation:
    output: dict[str, Any] | None
    errors: list[str]
    calls: int
    ok: bool


def make_provider() -> AIProvider:
    """A provider with settings suited to grounded writing: low temperature, bounded output."""
    from app.config import settings
    from app.services.ai.providers.agnes import AgnesProvider

    if not settings.AGNES_AI_API_KEY:
        raise ValueError("AGNES_AI_API_KEY is not configured")
    return AgnesProvider(
        AIProviderConfig(
            api_key=settings.AGNES_AI_API_KEY,
            model=settings.AGNES_TEXT_MODEL,
            max_tokens=2500,
            temperature=0.3,
            timeout=120,
        )
    )


def is_quota_error(exc: AIProviderError) -> bool:
    text = f"{exc} {exc.response_body or ''}".lower()
    return exc.status_code == 429 or "usage limit" in text or "quota" in text


def make_throttle(interval: float) -> Throttle:
    """An awaitable that keeps at least ``interval`` seconds between the calls that await it."""
    last = 0.0

    async def wait() -> None:
        nonlocal last
        gap = interval - (time.monotonic() - last)
        if gap > 0:
            await asyncio.sleep(gap)
        last = time.monotonic()

    return wait


async def generate(
    provider: AIProvider,
    sheet: FactSheet,
    locale: str,
    throttle: Throttle | None = None,
) -> Generation:
    """Call the model up to MAX_ATTEMPTS times, feeding validator errors back each time."""
    previous: dict[str, Any] | None = None
    errors: list[str] = []
    calls = 0
    for _ in range(MAX_ATTEMPTS):
        if throttle:
            await throttle()
        calls += 1
        try:
            output = await provider.complete_json(
                messages=build_messages(sheet, locale, previous, errors),
                json_schema=SCHEMAS[sheet.entity_type],
            )
        except AIProviderError as exc:
            if "Failed to parse JSON" not in str(exc):
                raise
            previous, errors = None, ["the answer was not valid JSON"]
            continue
        result = validator.validate(output, sheet, locale)
        if result.ok:
            return Generation(output, [], calls, True)
        previous, errors = output, result.errors
    return Generation(previous, errors, calls, False)


async def _siblings(db: AsyncSession, entity_type: str, locale: str) -> dict[str, str]:
    rows = (
        await db.execute(
            select(ContentBlock.slug, ContentBlock.body).where(
                ContentBlock.entity_type == entity_type,
                ContentBlock.locale == locale,
                ContentBlock.review_status.in_([*SERVED_STATUSES, "needs_review"]),
            )
        )
    ).all()
    return {slug: dedupe.content_text(body) for slug, body in rows}


async def _entity_slugs(
    db: AsyncSession, entity_type: str, after: str | None, slugs: list[str] | None, city: str | None
) -> list[str]:
    if entity_type == "locality":
        stmt = select(Locality.slug).order_by(Locality.slug)
        if after:
            stmt = stmt.where(Locality.slug > after)
        if slugs:
            stmt = stmt.where(Locality.slug.in_(slugs))
        if city:
            stmt = stmt.where(Locality.city == city)
        return list((await db.execute(stmt)).scalars())
    pstmt = (
        select(Property.id)
        .where(Property.status == PropertyStatus.available, Property.is_available.is_(True))
        .order_by(Property.id)
    )
    if after:
        pstmt = pstmt.where(Property.id > int(after))
    if slugs:
        pstmt = pstmt.where(Property.id.in_([int(s) for s in slugs]))
    return [str(i) for i in (await db.execute(pstmt)).scalars()]


async def build_sheet(db: AsyncSession, entity_type: str, slug: str) -> FactSheet | None:
    if entity_type == "locality":
        loc = await db.get(Locality, slug)
        return await build_locality_sheet(db, loc) if loc else None
    return await build_property_sheet(db, int(slug))


async def _store(db: AsyncSession, values: dict[str, Any]) -> None:
    stmt = insert(ContentBlock).values(**values)
    update = {k: v for k, v in values.items() if k not in ("entity_type", "slug", "locale")}
    await db.execute(
        stmt.on_conflict_do_update(index_elements=["entity_type", "slug", "locale"], set_=update)
    )
    await db.commit()


def decide(sheet: FactSheet, gen: Generation, score: float, twin: str | None) -> tuple[str, bool, list[str]]:
    """Review status, indexable flag and notes for a finished generation."""
    if not gen.ok:
        return "failed", False, gen.errors
    verdict = dedupe.decision(score)
    if verdict == "reject":
        return "rejected", False, [f"near-duplicate of {twin} (score {score:.2f})"]
    if verdict == "review":
        return "needs_review", False, [f"similar to {twin} (score {score:.2f})"]
    return "auto", sheet.meets_threshold, []


async def run_batch(
    db: AsyncSession,
    provider: AIProvider,
    *,
    entity_type: str,
    locales: list[str],
    max_entities: int = 20,
    max_calls: int = 120,
    max_seconds: float = 240.0,
    min_interval: float = 0.0,
    after: str | None = None,
    slugs: list[str] | None = None,
    city: str | None = None,
    force: bool = False,
    retry_failed: bool = False,
) -> RunStats:
    """Generate content for up to ``max_entities`` changed entities, then stop."""
    stats = RunStats()
    started = time.monotonic()
    throttle = make_throttle(min_interval)
    existing = {
        (slug, loc): (h, v, st)
        for slug, loc, h, v, st in (
            await db.execute(
                select(
                    ContentBlock.slug, ContentBlock.locale, ContentBlock.facts_hash,
                    ContentBlock.prompt_version, ContentBlock.review_status,
                ).where(ContentBlock.entity_type == entity_type)
            )
        ).all()
    }
    siblings = {loc: await _siblings(db, entity_type, loc) for loc in locales}
    enrich = _enricher(entity_type)
    todo = await _entity_slugs(db, entity_type, after, slugs, city)
    consecutive_errors = 0
    entities_done = 0

    for slug in todo:
        if entities_done >= max_entities:
            stats.stopped_reason = "entity_limit"
            break
        if stats.calls >= max_calls:
            stats.stopped_reason = "call_limit"
            break
        if time.monotonic() - started > max_seconds:
            stats.stopped_reason = "time_budget"
            break
        sheet = await build_sheet(db, entity_type, slug)
        if sheet is None:
            stats.next_after = slug
            continue
        if sheet.fact_count < MIN_FACTS_TO_GENERATE:
            stats.thin += 1
            stats.next_after = slug
            continue
        digest = sheet.facts_hash()
        worked = False
        for locale in locales:
            prior = existing.get((slug, locale))
            if (
                prior
                and not force
                and prior[0] == digest
                and prior[1] == PROMPT_VERSION
                and (prior[2] != "failed" or not retry_failed)
            ):
                stats.skipped += 1
                continue
            try:
                gen = await generate(provider, sheet, locale, throttle)
            except AIProviderError as exc:
                stats.provider_errors += 1
                consecutive_errors += 1
                logger.warning("content generation provider error: %s", exc)
                if is_quota_error(exc):
                    stats.stopped_reason = "rate_limited"
                    return stats
                if consecutive_errors >= MAX_CONSECUTIVE_PROVIDER_ERRORS:
                    stats.stopped_reason = "provider_errors"
                    return stats
                continue
            consecutive_errors = 0
            stats.calls += gen.calls
            worked = True
            body = gen.output or {}
            others = {k: v for k, v in siblings[locale].items() if k != slug}
            score, twin = dedupe.max_similarity(dedupe.content_text(body), others) if gen.ok else (0.0, None)
            status, indexable, notes = decide(sheet, gen, score, twin)
            if gen.ok and status in ("auto", "needs_review") and enrich:
                extra, extra_calls = await enrich(db, provider, sheet, locale, throttle)
                body = {**body, **extra}
                stats.calls += extra_calls
            await _store(
                db,
                {
                    "entity_type": entity_type, "slug": slug, "locale": locale, "body": body,
                    "sources": sheet.sources(), "facts_hash": digest, "fact_count": sheet.fact_count,
                    "key_fact": sheet.key_fact, "model": provider.config.model,
                    "prompt_version": PROMPT_VERSION, "data_as_of": sheet.data_as_of,
                    "review_status": status, "indexable": indexable, "dup_score": score if gen.ok else None,
                    "errors": notes,
                },
            )
            if status in ("auto", "needs_review"):
                siblings[locale][slug] = dedupe.content_text(body)
            stats.generated += status in ("auto", "needs_review")
            stats.failed += status == "failed"
            stats.rejected += status == "rejected"
            stats.needs_review += status == "needs_review"
            stats.items.append(
                {"slug": slug, "locale": locale, "status": status, "indexable": indexable,
                 "dup_score": round(score, 3), "calls": gen.calls}
            )
        entities_done += worked
        stats.next_after = slug  # the cursor only moves past finished entities
    else:
        stats.done = True
        stats.next_after = None
    return stats
