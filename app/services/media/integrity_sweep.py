"""Nightly integrity sweep: HEAD-check stored image URLs and alert on 404s.

This catches CDN-side drift that no insert-time check can prevent (deleted
assets, renamed buckets, broken migrations). Per the user's choice, this
sweep is **alert-only**: it never mutates the database.

Usage
-----
Designed to be invoked by an existing scheduler hook. If no scheduler is
available, run it ad-hoc::

    python -c "import asyncio; \\
      from app.services.media.integrity_sweep import run_image_integrity_sweep; \\
      print(asyncio.run(run_image_integrity_sweep()))"

The sample size is controlled by ``IMAGE_SWEEP_SAMPLE_SIZE`` (default 200)
and stratified 50/50 between recent and random rows so both new uploads and
legacy data are covered.
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass, field

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.properties import Property, PropertyImage
from app.services.media.url_verifier import verify_image_url

logger = get_logger(__name__)

DEFAULT_SAMPLE_SIZE = 200


@dataclass
class SweepReport:
    """Result of one integrity sweep run."""

    checked: int = 0
    broken: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def broken_count(self) -> int:
        return len(self.broken)

    def __str__(self) -> str:  # pragma: no cover - cosmetic
        return (
            f"SweepReport(checked={self.checked}, "
            f"broken={self.broken_count}, errors={len(self.errors)})"
        )


def _sample_size() -> int:
    raw = os.environ.get("IMAGE_SWEEP_SAMPLE_SIZE")
    if not raw:
        return DEFAULT_SAMPLE_SIZE
    try:
        n = int(raw)
        return max(1, n)
    except ValueError:
        return DEFAULT_SAMPLE_SIZE


async def _sample_urls(db: AsyncSession, sample_size: int) -> list[tuple[str, str]]:
    """Return [(source, url), ...] stratified 50/50 recent vs random.

    ``source`` is a short tag like ``properties.main:<id>`` or
    ``property_images:<id>`` for logging.
    """
    half = max(1, sample_size // 2)

    # Recent 50%: newest rows by id.
    recent_main = (
        select(Property.id, Property.main_image_url)
        .where(Property.main_image_url.is_not(None))
        .order_by(Property.id.desc())
        .limit(half)
    )
    recent_img = (
        select(PropertyImage.id, PropertyImage.image_url)
        .order_by(PropertyImage.id.desc())
        .limit(half)
    )

    # Random 50% across the whole table.
    rand_main = (
        select(Property.id, Property.main_image_url)
        .where(Property.main_image_url.is_not(None))
        .order_by(func.random())
        .limit(half)
    )
    rand_img = (
        select(PropertyImage.id, PropertyImage.image_url)
        .order_by(func.random())
        .limit(half)
    )

    out: list[tuple[str, str]] = []
    seen: set[str] = set()

    def _add(tag: str, rows) -> None:
        for row in rows:
            url = row[1]
            if url and url not in seen:
                seen.add(url)
                out.append((f"{tag}:{row[0]}", url))

    _add("properties.main", (await db.execute(recent_main)).all())
    _add("property_images", (await db.execute(recent_img)).all())
    _add("properties.main", (await db.execute(rand_main)).all())
    _add("property_images", (await db.execute(rand_img)).all())

    # Cap at requested sample size after dedup.
    return out[:sample_size]


async def run_image_integrity_sweep(
    db: AsyncSession,
    *,
    sample_size: int | None = None,
) -> SweepReport:
    """Sample stored image URLs, HEAD-check each, log/aggregate broken ones.

    Alert-only: never mutates the database. Emits one WARN log per broken
    URL and one aggregate ERROR log if any were found (so log-based alerts
    can fire on the aggregate line).
    """
    n = sample_size if sample_size is not None else _sample_size()
    report = SweepReport()

    samples = await _sample_urls(db, n)
    report.checked = len(samples)
    if not samples:
        logger.info("Image integrity sweep: no sampled URLs to check.")
        return report

    # Verify concurrently for speed; verify_image_url never raises.
    urls = [u for _, u in samples]
    results = await asyncio.gather(
        *(verify_image_url(u) for u in urls), return_exceptions=False
    )

    for (source_tag, url), ok in zip(samples, results, strict=True):
        if not ok:
            report.broken.append(url)
            logger.warning(
                "Image integrity sweep: BROKEN %s -- %s", source_tag, url
            )

    if report.broken_count:
        logger.error(
            "Image integrity sweep found %d broken URL(s) out of %d checked.",
            report.broken_count,
            report.checked,
        )
    else:
        logger.info(
            "Image integrity sweep: all %d sampled URLs OK.", report.checked
        )

    return report
