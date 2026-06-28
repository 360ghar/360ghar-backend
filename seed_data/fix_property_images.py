#!/usr/bin/env python3
"""Make the property catalog correct: keep ONLY the 109 real hardcoded
properties, deleting the synthetic generated ones.

Background
----------
The catalog had two populations:

  * 109 real hardcoded properties (loaded from ``hardcoded/properties/00xxx/``)
    — correct titles/data and each with its OWN matching Cloudinary images.
    Identified by ``features->>'slug'`` matching ``00%``.
  * ~102 synthetic generated properties (from ``generators/01_generate_seed_data``)
    — fabricated titles ("2BHK Apartment in Sector 43"), random type/purpose,
    and BORROWED images that don't match the listing. No real source data.

The user wants the catalog to be exclusively the real hardcoded properties.
This script deletes every synthetic property (all are ``is_seed_data=true`` —
no real user data is touched). Foreign keys cascade:

  * property_images, property_amenities, property_embeddings, visits, bookings
    → ON DELETE CASCADE (removed with the property)
  * user_swipes → ON DELETE SET NULL (kept, property_id cleared)

The seed pipeline itself is fixed so reseeds never recreate the synthetic
population: ``load_seed_properties`` is a no-op, the generator writes empty
property JSON, and generated activity references the hardcoded titles.

Modes:
    uv run python seed_data/fix_property_images.py --verify-only   # counts only
    uv run python seed_data/fix_property_images.py                  # dry-run preview
    uv run python seed_data/fix_property_images.py --apply          # commit

Idempotent: once the synthetic rows are gone, re-running deletes 0.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text

from app.core.database import AsyncSessionLocal
from app.core.logging import get_logger, setup_logging

logger = get_logger(__name__)

# Real hardcoded properties have features->>'slug' like "00101-...". Synthetic
# generated properties have no such slug.
HC_SLUG_LIKE = "00%"
# Predicate selecting the synthetic (non-hardcoded) properties.
SYNTHETIC_WHERE = "(features->>'slug') IS NULL OR (features->>'slug') NOT LIKE :p"


async def _counts(session) -> dict[str, int]:
    row = (await session.execute(text(
        f"""
        SELECT
          count(*) AS total,
          count(*) FILTER (WHERE (features->>'slug') LIKE :p) AS hardcoded,
          count(*) FILTER (WHERE {SYNTHETIC_WHERE}) AS synthetic,
          count(*) FILTER (WHERE ({SYNTHETIC_WHERE}) AND NOT is_seed_data) AS synthetic_real
        FROM properties
        """
    ), {"p": HC_SLUG_LIKE})).first()
    return {"total": row[0], "hardcoded": row[1], "synthetic": row[2], "synthetic_real": row[3]}


async def verify() -> None:
    async with AsyncSessionLocal() as session:
        c = await _counts(session)
    logger.info("=== PROPERTY CATALOG STATE ===")
    logger.info("  total properties        : %d", c["total"])
    logger.info("  real hardcoded (00%%)     : %d", c["hardcoded"])
    logger.info("  synthetic (to delete)   : %d", c["synthetic"])
    if c["synthetic_real"]:
        logger.error("  ✗ %d synthetic rows are NOT is_seed_data — aborting would be safer", c["synthetic_real"])
    else:
        logger.info("  ✓ all synthetic rows are is_seed_data (safe to delete)")


async def _delete_synthetic(session, *, apply: bool) -> int:
    """Delete synthetic (non-hardcoded) properties. Children cascade."""
    # Safety: never delete a non-seed property.
    real = (await session.execute(text(
        f"SELECT count(*) FROM properties WHERE ({SYNTHETIC_WHERE}) AND NOT is_seed_data"
    ), {"p": HC_SLUG_LIKE})).scalar()
    if real:
        raise RuntimeError(f"{real} synthetic-matched properties are not is_seed_data — refusing to delete")

    n = (await session.execute(text(
        f"SELECT count(*) FROM properties WHERE ({SYNTHETIC_WHERE})"
    ), {"p": HC_SLUG_LIKE})).scalar()

    if not apply:
        logger.info("[DRY-RUN] would delete %d synthetic properties (+ cascade children)", n)
        return n

    await session.execute(text(
        f"DELETE FROM properties WHERE ({SYNTHETIC_WHERE}) AND is_seed_data"
    ), {"p": HC_SLUG_LIKE})
    logger.info("[APPLY] deleted %d synthetic properties (children cascaded)", n)
    return n


async def _verify_post(session) -> bool:
    c = await _counts(session)
    ok = True
    logger.info("=== POST-STATE VERIFICATION ===")
    logger.info("  total properties : %d", c["total"])
    logger.info("  hardcoded (00%%)   : %d", c["hardcoded"])
    logger.info("  synthetic        : %d", c["synthetic"])

    if c["synthetic"]:
        logger.error("  ✗ %d synthetic properties remain", c["synthetic"])
        ok = False
    else:
        logger.info("  ✓ no synthetic properties remain")

    if c["total"] != c["hardcoded"]:
        logger.error("  ✗ total (%d) != hardcoded (%d)", c["total"], c["hardcoded"])
        ok = False
    else:
        logger.info("  ✓ catalog is exactly the hardcoded properties")

    # Every remaining property uses its OWN slug's images (no foreign/borrowed).
    foreign = (await session.execute(text(
        """
        SELECT count(*) FROM property_images pi JOIN properties p ON p.id = pi.property_id
        WHERE pi.image_url NOT LIKE '%/' || (p.features->>'slug') || '/%'
        """
    ))).scalar()
    if foreign:
        logger.error("  ✗ %d property_images do not belong to their property's own slug", foreign)
        ok = False
    else:
        logger.info("  ✓ all property_images belong to their own property (no borrowed images)")

    # No NULL main image, all http(s).
    null_main = (await session.execute(text(
        "SELECT count(*) FROM properties WHERE main_image_url IS NULL"
    ))).scalar()
    if null_main:
        logger.error("  ✗ %d properties have NULL main_image_url", null_main)
        ok = False
    else:
        logger.info("  ✓ no NULL main_image_url")

    non_http = (await session.execute(text(
        "SELECT count(*) FROM property_images WHERE image_url NOT LIKE 'http%'"
    ))).scalar()
    if non_http:
        logger.error("  ✗ %d property_images are not http(s) URLs", non_http)
        ok = False
    else:
        logger.info("  ✓ all property_images are http(s) URLs")

    # Every property that HAS an exterior image uses it as the main image.
    wrong_main = (await session.execute(text(
        """
        SELECT count(*) FROM properties p
        WHERE EXISTS (SELECT 1 FROM property_images x WHERE x.property_id = p.id AND x.image_category = 'exterior')
          AND NOT EXISTS (
            SELECT 1 FROM property_images m
            WHERE m.property_id = p.id AND m.image_url = p.main_image_url AND m.image_category = 'exterior'
          )
        """
    ))).scalar()
    if wrong_main:
        logger.error("  ✗ %d properties have an exterior image but a non-exterior main", wrong_main)
        ok = False
    else:
        logger.info("  ✓ every property with an exterior image uses it as the main image")

    return ok


async def run(*, apply: bool) -> None:
    mode = "APPLY" if apply else "DRY-RUN (no writes)"
    logger.info("=== %s: PRUNE SYNTHETIC PROPERTIES ===", mode)
    async with AsyncSessionLocal() as session:
        before = await _counts(session)
        logger.info("Before: total=%d hardcoded=%d synthetic=%d",
                    before["total"], before["hardcoded"], before["synthetic"])
        await _delete_synthetic(session, apply=apply)
        if apply:
            await session.commit()
            logger.info("Committed.")
            ok = await _verify_post(session)
            if not ok:
                logger.error("Post-state verification FAILED — review the errors above.")
                sys.exit(1)
            logger.info("All post-state checks passed.")
        else:
            logger.info("Dry-run complete. Re-run with --apply to commit.")


async def main() -> None:
    setup_logging()
    parser = argparse.ArgumentParser(description="Prune synthetic properties; keep only the real hardcoded catalog")
    parser.add_argument("--verify-only", action="store_true", help="Report counts only; no writes")
    parser.add_argument("--apply", action="store_true", help="Commit deletions (default is dry-run)")
    args = parser.parse_args()

    if args.verify_only:
        await verify()
        return
    await run(apply=args.apply)


if __name__ == "__main__":
    asyncio.run(main())
