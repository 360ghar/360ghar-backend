"""Generate house-style art once per subject, store it in Cloudinary, compose OG card URLs.

Art is keyed by sha256(style version, subject, ratio, size) in ``generated_images``, so a
repeat call, or a second worker, never pays for the same image twice. The OG card is that art
plus a Cloudinary text layer, so the title, price and locality are exact, never drawn by the model.
"""

from __future__ import annotations

import asyncio
import base64
import re
import time
from dataclasses import asdict, dataclass, field
from datetime import timedelta
from typing import Any

from sqlalchemy import and_, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.exceptions import NotFoundException
from app.core.logging import get_logger
from app.core.utils import utc_now
from app.models.blogs import BlogPost
from app.models.content import SERVED_STATUSES, ContentBlock, GeneratedImage, Locality
from app.models.enums import PropertyPurpose, PropertyStatus, PropertyType
from app.models.properties import Property
from app.services.ai.image_gen.schemas import ImageGenMode, ImageGenRequest
from app.services.ai.imagery import style
from app.services.content.facts import inr
from app.services.storage_paths import StorageFolder

logger = get_logger(__name__)

CONCURRENCY = 4
PAGE = 500  # subjects read per query when looking for work
KINDS = ("city", "locality", "property", "blog")
# A pending row older than this is a worker that died. Another run may take it.
PENDING_TTL = timedelta(minutes=15)
QUOTA_RETRY = timedelta(minutes=30)
FAILURE_RETRY = timedelta(hours=6)
FALLBACK_OG = "https://360ghar.com/og-image-home.jpg"


@dataclass(frozen=True)
class Subject:
    subject_type: str
    slug: str
    name: str
    city: str | None = None


@dataclass
class ImageryStats:
    generated: int = 0
    skipped: int = 0
    failed: int = 0
    rate_limited: int = 0
    done: bool = False
    retry_after: int | None = None
    stopped_reason: str | None = None
    items: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


# ── OG card URL ─────────────────────────────────────────────────────────────


def _clip(text: str, limit: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 3].rstrip() + "..."


TITLE_MAX = 120  # characters. Longer text would not fit the card, so it is cut with "..."
LOCALITY_MAX = 80


def _title_size(title: str) -> int:
    """Smaller type for longer titles, so ordinary titles are shown whole."""
    return 60 if len(title) <= 40 else 48 if len(title) <= 70 else 38


def compose_og_url(
    art_public_id: str, title: str, *, price: str | None = None, locality: str | None = None
) -> str:
    """Cloudinary URL: the art at 1200x630, darkened, with the exact text laid on top."""
    from cloudinary.utils import cloudinary_url

    from app.services.cloudinary.service import get_cloudinary_service

    get_cloudinary_service()  # configures the SDK with the account credentials

    def layer(text: str, size: int, weight: str, y: int, family: str) -> dict[str, Any]:
        return {
            "overlay": {"font_family": family, "font_size": size, "font_weight": weight, "text": text},
            "color": "#FFFFFF",
            "gravity": "south_west",
            "x": 64,
            "y": y,
            "width": 1072,
            "crop": "fit",
        }

    chain: list[dict[str, Any]] = [
        {"width": 1200, "height": 630, "crop": "fill", "gravity": "auto", "effect": "brightness:-30"},
        layer(_clip(title, TITLE_MAX), _title_size(title), "bold", 150, "Georgia"),
    ]
    if price:
        chain.append(layer(price, 44, "bold", 84, "Arial"))
    if locality:
        chain.append(layer(_clip(locality, LOCALITY_MAX), 32, "normal", 36, "Arial"))
    chain.append({"fetch_format": "auto", "quality": "auto"})
    url, _ = cloudinary_url(art_public_id, transformation=chain, secure=True)
    return str(url)


def fallback_og_url() -> str:
    return settings.OG_FALLBACK_IMAGE_URL or FALLBACK_OG


# ── one image ───────────────────────────────────────────────────────────────


async def get_row(db: AsyncSession, key: str) -> GeneratedImage | None:
    return (await db.execute(select(GeneratedImage).where(GeneratedImage.key == key))).scalar_one_or_none()


def is_workable(row: GeneratedImage | None, now: Any) -> bool:
    """Whether a run may generate this image now."""
    if row is None:
        return True
    if row.status == "ready":
        return False
    if row.status == "failed":
        return row.retry_after is None or row.retry_after <= now
    return bool(row.updated_at is not None and row.updated_at <= now - PENDING_TTL)  # stale pending


async def _claim(db: AsyncSession, key: str, subject: Subject) -> bool:
    """Take the image for this worker. One statement decides the winner: the row is inserted, or
    taken over only when it is failed and due, or pending and stale. A ready row is never taken."""
    now = utc_now()
    base = insert(GeneratedImage).values(
        key=key, subject_type=subject.subject_type, subject_slug=subject.slug, status="pending"
    )
    stmt = base.on_conflict_do_update(
        index_elements=["key"],
        set_={"status": "pending", "retry_after": None, "updated_at": now},
        where=or_(
            and_(
                GeneratedImage.status == "failed",
                or_(GeneratedImage.retry_after.is_(None), GeneratedImage.retry_after <= now),
            ),
            and_(GeneratedImage.status == "pending", GeneratedImage.updated_at <= now - PENDING_TTL),
        ),
    ).returning(GeneratedImage.key)
    won = (await db.execute(stmt)).scalar_one_or_none() is not None
    await db.commit()
    return won


async def _finish(db: AsyncSession, key: str, **values: Any) -> None:
    row = await get_row(db, key)
    if row is None:
        return
    for name, value in values.items():
        setattr(row, name, value)
    row.updated_at = utc_now()
    await db.commit()


def _upload(png: bytes, subject: Subject, key: str) -> dict[str, Any]:
    from app.services.cloudinary.service import get_cloudinary_service

    return get_cloudinary_service().upload_file(
        png,
        public_id=f"{subject.subject_type}/{subject.slug}-{key[:10]}",
        folder=StorageFolder.AI_ART.value,
        content_type="image/png",
        is_image=True,
        overwrite=True,
    )


async def ensure_art(
    db: AsyncSession,
    subject: Subject,
    *,
    ratio: str = style.OG_RATIO,
    size: str = style.OG_SIZE,
    lock: asyncio.Lock | None = None,
) -> tuple[str, int | None]:
    """Make the art for one subject. Returns (status, retry_seconds).

    status is ``ready``, ``skipped`` (already done or being done), ``failed`` or ``rate_limited``.
    ``lock`` serialises the DB work when several workers share one session.
    """
    from app.services.ai.image_gen.service import generate_image

    lock = lock or asyncio.Lock()
    key = style.image_key(subject.subject_type, subject.slug, ratio, size)
    async with lock:
        if not await _claim(db, key, subject):
            return "skipped", None

    request = ImageGenRequest(
        mode=ImageGenMode.TEXT_TO_IMAGE,
        prompt=style.build_prompt(subject.subject_type, _clip(subject.name, 120), subject.city),
        image=None,
        mime_type=None,
        ratio=ratio,
    )
    result = await generate_image(request, size=size, instruction=style.HOUSE_STYLE)
    if not result.success or not result.image:
        quota = result.code == "QUOTA_EXCEEDED"
        wait = QUOTA_RETRY if quota else FAILURE_RETRY
        async with lock:
            await _finish(db, key, status="failed", retry_after=utc_now() + wait)
        return ("rate_limited" if quota else "failed"), int(wait.total_seconds())

    try:
        png = base64.b64decode(result.image.split(",", 1)[1])
        stored = await asyncio.to_thread(_upload, png, subject, key)
    except Exception as exc:  # upload or decode: keep the row retryable
        logger.error("Imagery upload failed for %s/%s: %s", subject.subject_type, subject.slug, exc)
        async with lock:
            await _finish(db, key, status="failed", retry_after=utc_now() + FAILURE_RETRY)
        return "failed", int(FAILURE_RETRY.total_seconds())
    async with lock:
        await _finish(
            db, key, status="ready", public_id=stored["public_id"], url=stored["secure_url"],
            retry_after=None,
        )
    return "ready", None


# ── subjects ────────────────────────────────────────────────────────────────


async def list_subjects(db: AsyncSession, kind: str, limit: int, offset: int = 0) -> list[Subject]:
    """Entities that should have art: cities with listings or localities, localities with served
    content, available properties, published posts. One page of ``limit`` from ``offset``."""
    if kind == "city":
        names: set[str | None] = set((await db.execute(select(Locality.city).distinct())).scalars().all())
        names |= set(
            (
                await db.execute(
                    select(Property.city)
                    .where(Property.status == PropertyStatus.available, Property.is_available.is_(True))
                    .distinct()
                )
            ).scalars().all()
        )
        by_slug = {slugify(c): c for c in sorted(n for n in names if n) if slugify(c)}
        return [Subject("city", slug, name) for slug, name in sorted(by_slug.items())][offset : offset + limit]
    if kind == "locality":
        lrows = (
            await db.execute(
                select(Locality.slug, Locality.name, Locality.city)
                .join(ContentBlock, (ContentBlock.slug == Locality.slug) & (ContentBlock.entity_type == "locality"))
                .where(ContentBlock.review_status.in_(SERVED_STATUSES), ContentBlock.indexable.is_(True))
                .distinct()
                .order_by(Locality.slug)
                .limit(limit)
                .offset(offset)
            )
        ).all()
        return [Subject("locality", r.slug, r.name, r.city) for r in lrows]
    if kind == "property":
        prows = (
            await db.execute(
                select(Property.id, Property.property_type, Property.locality, Property.city)
                .where(Property.status == PropertyStatus.available, Property.is_available.is_(True))
                .order_by(Property.id)
                .limit(limit)
                .offset(offset)
            )
        ).all()
        return [
            Subject("property", str(r.id), r.locality or r.city or "the city", r.city if r.locality else None)
            for r in prows
        ]
    brows = (
        await db.execute(
            select(BlogPost.slug, BlogPost.title)
            .where(BlogPost.status == "published")
            .order_by(BlogPost.published_at.desc(), BlogPost.slug)
            .limit(limit)
            .offset(offset)
        )
    ).all()
    return [Subject("blog", r.slug, r.title) for r in brows]


async def pending_subjects(
    db: AsyncSession, kinds: list[str], limit: int, *, ratio: str = style.OG_RATIO, size: str = style.OG_SIZE
) -> list[Subject]:
    """Subjects whose art is missing or due for retry, in kind order, at most ``limit``."""
    now = utc_now()
    out: list[Subject] = []
    for kind in kinds:
        offset = 0
        while len(out) < limit:
            page = await list_subjects(db, kind, PAGE, offset)
            if not page:
                break
            offset += PAGE
            keys = {style.image_key(s.subject_type, s.slug, ratio, size): s for s in page}
            found = (await db.execute(select(GeneratedImage).where(GeneratedImage.key.in_(list(keys))))).scalars()
            rows = {r.key: r for r in found}
            for key, subject in keys.items():
                if is_workable(rows.get(key), now):
                    out.append(subject)
                    if len(out) >= limit:
                        return out
            if len(page) < PAGE:
                break
    return out


async def run_batch(
    db: AsyncSession,
    kinds: list[str],
    *,
    max_items: int,
    max_seconds: float,
    ratio: str = style.OG_RATIO,
    size: str = style.OG_SIZE,
) -> ImageryStats:
    """Generate art for up to ``max_items`` subjects, ``CONCURRENCY`` at a time.

    Stops starting new items after ``max_seconds`` or on a 429 from the provider; the stats then
    carry ``retry_after`` so the caller waits instead of hammering."""
    stats = ImageryStats()
    todo = await pending_subjects(db, kinds, max_items, ratio=ratio, size=size)
    stats.done = len(todo) < max_items
    deadline = time.monotonic() + max_seconds
    sem = asyncio.Semaphore(CONCURRENCY)
    lock = asyncio.Lock()
    stop = asyncio.Event()

    async def work(subject: Subject) -> None:
        async with sem:
            if stop.is_set() or time.monotonic() > deadline:
                stats.stopped_reason = stats.stopped_reason or ("rate_limited" if stop.is_set() else "time")
                stats.done = False
                return
            status, retry = await ensure_art(db, subject, ratio=ratio, size=size, lock=lock)
            if status == "ready":
                stats.generated += 1
            elif status == "skipped":
                stats.skipped += 1
            elif status == "rate_limited":
                stats.rate_limited += 1
                stats.retry_after = retry
                stats.stopped_reason = "rate_limited"
                stop.set()
            else:
                stats.failed += 1
            stats.items.append({"kind": subject.subject_type, "slug": subject.slug, "status": status})

    await asyncio.gather(*(work(s) for s in todo))
    return stats


# ── share card text ─────────────────────────────────────────────────────────


def _not_found() -> NotFoundException:
    return NotFoundException("Not found", error_code="NOT_FOUND")


async def card_text(db: AsyncSession, kind: str, slug: str) -> tuple[str, str | None, str | None]:
    """(title, price line, locality line) for one subject. NotFound when it is not public."""
    if kind == "property":
        row = None
        if slug.isascii() and slug.isdigit() and len(slug) < 18:
            row = (await db.execute(select(Property).where(Property.id == int(slug)))).scalar_one_or_none()
        if row is None:
            raise _not_found()
        # Same rule as the property detail route: a flatmate or PG listing that is not live is hidden.
        if row.property_type in (PropertyType.flatmate, PropertyType.pg):
            if ((row.listing_preferences or {}).get("moderation_status") or "live") != "live":
                raise _not_found()
        price = None  # each purpose has its own price column. Never show another purpose's price.
        if row.purpose == PropertyPurpose.rent and row.monthly_rent:
            price = f"{inr(row.monthly_rent)} / month"
        elif row.purpose == PropertyPurpose.short_stay and row.daily_rate:
            price = f"{inr(row.daily_rate)} / night"
        elif row.purpose == PropertyPurpose.buy and row.base_price:
            price = inr(row.base_price)
        where = ", ".join(p for p in (row.locality, row.city) if p)
        return row.title, price, where or None
    if kind == "locality":
        loc = (await db.execute(select(Locality).where(Locality.slug == slug))).scalar_one_or_none()
        if loc is None:
            raise _not_found()
        return loc.name, None, loc.city
    if kind == "blog":
        title = (
            await db.execute(select(BlogPost.title).where(BlogPost.slug == slug, BlogPost.status == "published"))
        ).scalar_one_or_none()
        if title is None:
            raise _not_found()
        return title, None, "360Ghar"
    cities: list[str | None] = [
        *(await db.execute(select(Locality.city).distinct())).scalars().all(),
        *(await db.execute(select(Property.city).distinct())).scalars().all(),
    ]
    name = next((c for c in cities if c and slugify(c) == slug), None)
    if name is None:
        raise _not_found()
    return name, None, "Real estate on 360Ghar"
