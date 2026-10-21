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

from sqlalchemy import func, select, update
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
# It awaits ``before_call`` ahead of each model call and returns the extra body keys.
Throttle = Callable[[], Awaitable[None]]
Enricher = Callable[[AsyncSession, AIProvider, FactSheet, str, Throttle], Awaitable[dict[str, Any]]]
ENRICHERS: dict[str, Enricher] = {}


class BudgetExceeded(Exception):
    """A run limit was reached between model calls. ``reason`` becomes the stop reason."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


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
    lock = asyncio.Lock()  # callers queue, so two of them never wake on the same gap

    async def wait() -> None:
        nonlocal last
        async with lock:
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


async def _siblings(db: AsyncSession, entity_type: str, locale: str) -> dict[str, dedupe.Shingles]:
    rows = (
        await db.execute(
            select(ContentBlock.slug, ContentBlock.body).where(
                ContentBlock.entity_type == entity_type,
                ContentBlock.locale == locale,
                ContentBlock.review_status.in_([*SERVED_STATUSES, "needs_review"]),
            )
        )
    ).all()
    return {slug: dedupe.shingles(dedupe.content_text(body)) for slug, body in rows}


def _property_id(value: str) -> int:
    if not value.isdigit() or len(value) > 18:
        raise ValueError(f"invalid property id: {value!r}")
    return int(value)


async def _entity_slugs(
    db: AsyncSession, entity_type: str, after: str | None, slugs: list[str] | None, city: str | None
) -> list[str]:
    """Slugs in a stable order. Raises ValueError for a malformed property cursor or id."""
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
        pstmt = pstmt.where(Property.id > _property_id(after))
    if slugs:
        pstmt = pstmt.where(Property.id.in_([_property_id(s) for s in slugs]))
    return [str(i) for i in (await db.execute(pstmt)).scalars()]


async def build_sheet(db: AsyncSession, entity_type: str, slug: str) -> FactSheet | None:
    if entity_type == "locality":
        loc = await db.get(Locality, slug)
        return await build_locality_sheet(db, loc) if loc else None
    return await build_property_sheet(db, int(slug))


async def _store(db: AsyncSession, values: dict[str, Any]) -> None:
    stmt = insert(ContentBlock).values(**values)
    now = func.now()
    changes = {k: v for k, v in values.items() if k not in ("entity_type", "slug", "locale")}
    changes |= {"generated_at": now, "updated_at": now}
    await db.execute(
        stmt.on_conflict_do_update(index_elements=["entity_type", "slug", "locale"], set_=changes)
    )
    await db.commit()


async def _note_failure(db: AsyncSession, entity_type: str, slug: str, locale: str, notes: list[str]) -> None:
    """A failed regeneration keeps the block that is already served and only records why."""
    await db.execute(
        update(ContentBlock)
        .where(ContentBlock.entity_type == entity_type, ContentBlock.slug == slug, ContentBlock.locale == locale)
        .values(errors=notes, updated_at=ContentBlock.updated_at)  # a note must not move last-modified
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
    throttle: Throttle | None = None,
    after: str | None = None,
    slugs: list[str] | None = None,
    city: str | None = None,
    force: bool = False,
    retry_failed: bool = False,
) -> RunStats:
    """Generate content for up to ``max_entities`` changed entities, then stop.

    ``max_calls`` and ``max_seconds`` are enforced before every model call, so a slow or
    throttled call cannot run past them. ``throttle`` replaces the per-run call spacing, so
    several runs in one process can share one spacing clock.
    """
    stats = RunStats(next_after=after)
    started = time.monotonic()
    spacing = throttle or make_throttle(min_interval)

    async def before_call() -> None:
        if stats.calls >= max_calls:
            raise BudgetExceeded("call_limit")
        if time.monotonic() - started > max_seconds:
            raise BudgetExceeded("time_budget")
        stats.calls += 1
        await spacing()

    existing = {
        (slug, loc): (h, v, st, pending)
        for slug, loc, h, v, st, pending in (
            await db.execute(
                select(
                    ContentBlock.slug, ContentBlock.locale, ContentBlock.facts_hash,
                    ContentBlock.prompt_version, ContentBlock.review_status,
                    ContentBlock.body.has_key("enrichment_pending"),
                ).where(ContentBlock.entity_type == entity_type)
            )
        ).all()
    }
    siblings = {loc: await _siblings(db, entity_type, loc) for loc in locales}
    if entity_type == "property":
        # Importing the module registers its enricher. A caller that imports only the runner
        # (a script, a test) must still get alt text.
        from app.services.content import property_summary  # noqa: F401
    enrich = ENRICHERS.get(entity_type)
    todo = await _entity_slugs(db, entity_type, after, slugs, city)
    consecutive_errors = 0
    entities_done = 0
    frozen = False  # once an entity is unfinished the cursor stays before it

    def advance(slug: str) -> None:
        if not frozen:
            stats.next_after = slug

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
            advance(slug)
            continue
        if sheet.fact_count < MIN_FACTS_TO_GENERATE:
            stats.thin += 1
            advance(slug)
            continue
        digest = sheet.facts_hash()
        worked = False
        for locale in locales:
            calls_before = stats.calls
            prior = existing.get((slug, locale))
            if (
                prior
                and not force
                and prior[0] == digest
                and prior[1] == PROMPT_VERSION
                and not prior[3]
                and (prior[2] != "failed" or not retry_failed)
            ):
                stats.skipped += 1
                continue
            try:
                gen = await generate(provider, sheet, locale, before_call)
            except BudgetExceeded as exc:
                stats.stopped_reason = exc.reason
                return stats
            except AIProviderError as exc:
                frozen = True
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
            worked = True
            body = dict(gen.output or {})
            others = {k: v for k, v in siblings[locale].items() if k != slug}
            score, twin = dedupe.max_similarity(dedupe.content_text(body), others) if gen.ok else (0.0, None)
            status, indexable, notes = decide(sheet, gen, score, twin)
            budget_hit: str | None = None
            if enrich and status in ("auto", "needs_review"):
                # Only content that will be kept is enriched. If the budget runs out part way, the
                # validated body is still stored (it cost model calls) and marked for a later run.
                try:
                    body |= await enrich(db, provider, sheet, locale, before_call)
                except BudgetExceeded as exc:
                    body["enrichment_pending"] = True
                    budget_hit = exc.reason
                except AIProviderError as exc:
                    logger.warning("content enrichment provider error: %s", exc)
                    stats.provider_errors += 1
                    body["enrichment_pending"] = True
                    if is_quota_error(exc):
                        budget_hit = "rate_limited"
                    else:
                        frozen = True
            if status != "auto" and prior and prior[2] in SERVED_STATUSES:
                # A served block is never replaced by content that would not be served (failed,
                # rejected as a duplicate, or held for review). Record why and keep serving it.
                await _note_failure(db, entity_type, slug, locale, notes)
            else:
                await _store(
                    db,
                    {
                        "entity_type": entity_type, "slug": slug, "locale": locale, "body": body,
                        "sources": sheet.sources(), "facts_hash": digest, "fact_count": sheet.fact_count,
                        "key_fact": sheet.key_fact, "model": provider.config.model,
                        "prompt_version": PROMPT_VERSION, "data_as_of": sheet.data_as_of,
                        "review_status": status, "indexable": indexable,
                        "dup_score": score if gen.ok else None, "errors": notes,
                    },
                )
                if status in ("auto", "needs_review"):
                    siblings[locale][slug] = dedupe.shingles(dedupe.content_text(body))
            if budget_hit:
                stats.generated += 1
                stats.stopped_reason = budget_hit
                return stats
            stats.generated += status in ("auto", "needs_review")
            stats.failed += status == "failed"
            stats.rejected += status == "rejected"
            stats.needs_review += status == "needs_review"
            stats.items.append(
                {"slug": slug, "locale": locale, "status": status, "indexable": indexable,
                 "dup_score": round(score, 3), "calls": stats.calls - calls_before}
            )
        entities_done += worked
        advance(slug)  # the cursor only moves past finished entities
    else:
        stats.done = not frozen
        stats.next_after = None if not frozen else stats.next_after
    return stats
