#!/usr/bin/env python3
"""
360Ghar Data Seeding — Master Orchestrator

Loads data in three categories with proper dependency ordering:
1. Hardcoded (team-curated)
2. Seed (deterministic generated)
3. Generated (simulated user activity)

Usage:
    python seed_data/01_load_all.py
    python seed_data/01_load_all.py --only hardcoded,seed
    python seed_data/01_load_all.py --quick
    python seed_data/01_load_all.py --dry-run
    python seed_data/01_load_all.py --skip-media
"""

from __future__ import annotations

import argparse
import asyncio
import importlib
import os
import sys
from datetime import datetime

# Project root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.core.database import AsyncSessionLocal
from app.core.logging import get_logger, setup_logging
from app.models.properties import Amenity, Property, PropertyAmenity, PropertyImage
from app.schemas.property import Property as PropertySchema

logger = get_logger(__name__)


async def _validate_loaded_properties(sample_size: int = 10) -> dict[str, int]:
    """Validate a random sample of loaded properties through PropertySchema.

    Reads properties from the DB with their eagerly-loaded relationships
    and runs ``PropertySchema.model_validate()`` on each, catching any
    schema/data mismatches at load time instead of at query time.
    """
    passed = 0
    failed = 0
    total = 0

    async with AsyncSessionLocal() as session:
        count_result = await session.execute(select(func.count(Property.id)))
        total = count_result.scalar() or 0
        if total == 0:
            logger.info("No properties found for post-load validation")
            return {"total": 0, "passed": 0, "failed": 0}

        sample = await session.execute(
            select(Property)
            .options(
                selectinload(Property.images).load_only(
                    PropertyImage.id,
                    PropertyImage.image_url,
                    PropertyImage.image_category,
                    PropertyImage.display_order,
                ),
                selectinload(Property.property_amenities)
                .selectinload(PropertyAmenity.amenity)
                .load_only(Amenity.id, Amenity.title, Amenity.icon, Amenity.category),
            )
            .order_by(func.random())
            .limit(min(sample_size, total))
        )
        properties = list(sample.scalars().all())

    for prop in properties:
        try:
            PropertySchema.model_validate(prop)
            passed += 1
        except Exception as e:
            failed += 1
            logger.error(
                "Schema validation FAILED for property %s (id=%d, title=%s): %s",
                prop.id, prop.id, prop.title, e,
            )

    if failed:
        logger.warning(
            "Post-load validation: %d/%d passed, %d/%d failed (sampled %d of %d total)",
            passed, len(properties), failed, len(properties), len(properties), total,
        )
    else:
        logger.info(
            "Post-load validation: %d/%d passed ✓ (sampled %d of %d total)",
            passed, len(properties), len(properties), total,
        )

    return {"total": total, "passed": passed, "failed": failed}


async def _dry_run_validate(only: list[str] | None = None) -> dict[str, int]:
    """Validate all seed data JSON against model schemas without writing to DB.

    Loads each JSON file, resolves references (using a mock IDMap),
    and tries to construct each model instance. Reports any
    enum/TypeError/missing-column errors that would crash a real load.
    Returns {"checked": N, "errors": N, "details": [...]}.
    """
    _mod = importlib.import_module
    load_json = _mod("seed_data.loaders.01_base").load_json
    resolve_refs = _mod("seed_data.loaders.01_base").resolve_refs
    IDMap = _mod("seed_data.loaders.01_base").IDMap
    SEED_DIR = _mod("seed_data.loaders.01_base").SEED_DIR
    HARDCODED_DIR = _mod("seed_data.loaders.01_base").HARDCODED_DIR
    GENERATED_DIR = SEED_DIR.parent / "generated"

    from app.models.agents import AgentInteraction
    from app.models.ai_conversations import AIConversation
    from app.models.blogs import BlogPost
    from app.models.bookings import Booking
    from app.models.conversations import Conversation, ConversationParticipant
    from app.models.conversations import Message as UserMessage
    from app.models.core import BugReport
    from app.models.data_hub import (
        AuctionAlert,
        BankAuction,
        BankRate,
        CircleRate,
        GazetteNotification,
        NeighbourhoodScore,
        ReraProject,
        ZoningData,
    )
    from app.models.pm_documents import Document
    from app.models.pm_finance import Expense, RentCharge, RentPayment
    from app.models.pm_inspections import InspectionChecklist
    from app.models.pm_leases import Lease
    from app.models.pm_maintenance import MaintenanceRequest
    from app.models.properties import Amenity, Property, Visit
    from app.models.social import (
        FlatmateProfileViewEvent,
        FlatmateSuperLikeUsage,
        MatchQnAAnswer,
        UserBlock,
        UserMatch,
        UserReport,
    )
    from app.models.tours import (
        AIJob,
        FloorPlan,
        Hotspot,
        MediaFile,
        Scene,
        Tour,
        TourAnalyticsEvent,
        TourBranding,
        TourLocation,
    )
    from app.models.users import User, UserSearchHistory, UserSwipe

    # Build a mock IDMap with fake IDs so refs resolve to dummy ints
    id_map = IDMap()
    _fake_id = 1
    for email in [
        "saksham1991999@gmail.com", "ravi786modi@gmail.com",
        "priya.designs@gmail.com", "amit.tech@gmail.com",
        "neha.writer@gmail.com", "vikram.realty@gmail.com",
    ]:
        id_map.put("user", email, _fake_id); _fake_id += 1
        id_map.put("user", f"+91{email[:8]}", _fake_id)
    for name in ["Property Manager", "Amit Verma", "Neha Singh", "Vikram Realty", "Rohit Homes", "Sonia Estates"]:
        id_map.put("agent", name, _fake_id); _fake_id += 1
    for title in ["Premium 3BHK Apartment", "1BHK Floor", "Studio Apartment", "4BHK Villa", "2BHK Apartment"]:
        id_map.put("property", title, _fake_id); _fake_id += 1
    for ref in ["lease_001", "lease_002", "lease_003", "lease_004", "lease_005"]:
        id_map.put("lease", ref, _fake_id); _fake_id += 1
    for ref in ["conv_001", "conv_002"]:
        id_map.put("conversation", ref, _fake_id); _fake_id += 1
    for ref in ["match_001", "match_002"]:
        id_map.put("match", ref, _fake_id); _fake_id += 1

    # Define all validation targets: (json_path, model, is_generated)
    load_hardcoded = only is None or "hardcoded" in only
    load_seed = only is None or "seed" in only
    load_generated = only is None or "generated" in only

    targets = []
    if load_hardcoded:
        targets += [
            (HARDCODED_DIR / "01_users.json", User),
            (HARDCODED_DIR / "03_amenities.json", Amenity),
        ]
    if load_seed:
        targets += [
            (SEED_DIR / "01_users.json", User),
            (SEED_DIR / "03_properties.json", Property),
            (SEED_DIR / "05_visits.json", Visit),
            (SEED_DIR / "06_bookings.json", Booking),
            (SEED_DIR / "07_tours.json", Tour),
            (SEED_DIR / "08_scenes.json", Scene),
            (SEED_DIR / "09_hotspots.json", Hotspot),
            (SEED_DIR / "10_tour_locations.json", TourLocation),
            (SEED_DIR / "11_floor_plans.json", FloorPlan),
            (SEED_DIR / "12_tour_branding.json", TourBranding),
            (SEED_DIR / "13_media_files.json", MediaFile),
            (SEED_DIR / "14_ai_jobs.json", AIJob),
            (SEED_DIR / "15_leases.json", Lease),
            (SEED_DIR / "17_rent_charges.json", RentCharge),
            (SEED_DIR / "18_rent_payments.json", RentPayment),
            (SEED_DIR / "19_expenses.json", Expense),
            (SEED_DIR / "20_maintenance_requests.json", MaintenanceRequest),
            (SEED_DIR / "21_documents.json", Document),
            (SEED_DIR / "22_inspections.json", InspectionChecklist),
            (SEED_DIR / "23_blog_posts.json", BlogPost),
            (SEED_DIR / "24_data_hub_circle_rates.json", CircleRate),
            (SEED_DIR / "25_data_hub_rera.json", ReraProject),
            (SEED_DIR / "26_data_hub_auctions.json", BankAuction),
            (SEED_DIR / "27_data_hub_gazette.json", GazetteNotification),
            (SEED_DIR / "28_data_hub_zoning.json", ZoningData),
            (SEED_DIR / "29_data_hub_bank_rates.json", BankRate),
            (SEED_DIR / "30_data_hub_neighbourhoods.json", NeighbourhoodScore),
            (SEED_DIR / "31_bug_reports.json", BugReport),
        ]
    if load_generated:
        targets += [
            (GENERATED_DIR / "01_swipes.json", UserSwipe),
            (GENERATED_DIR / "02_matches.json", UserMatch),
            (GENERATED_DIR / "03_match_qna.json", MatchQnAAnswer),
            (GENERATED_DIR / "04_conversations.json", Conversation),
            (GENERATED_DIR / "04b_conversation_participants.json", ConversationParticipant),
            (GENERATED_DIR / "05_messages.json", UserMessage),
            (GENERATED_DIR / "06_super_like_usage.json", FlatmateSuperLikeUsage),
            (GENERATED_DIR / "07_blocks.json", UserBlock),
            (GENERATED_DIR / "08_reports.json", UserReport),
            (GENERATED_DIR / "09_profile_view_events.json", FlatmateProfileViewEvent),
            (GENERATED_DIR / "10_flatmate_visits.json", Visit),
            (GENERATED_DIR / "11_agent_interactions.json", AgentInteraction),
            (GENERATED_DIR / "12_search_history.json", UserSearchHistory),
            (GENERATED_DIR / "13_tour_analytics.json", TourAnalyticsEvent),
            (GENERATED_DIR / "14_ai_conversations.json", AIConversation),
            (GENERATED_DIR / "15_auction_alerts.json", AuctionAlert),
        ]

    checked = 0
    errors = 0
    error_details: list[str] = []

    for json_path, model_cls in targets:
        records = load_json(json_path)
        if not records:
            continue
        for i, raw in enumerate(records):
            try:
                clean = resolve_refs(raw, id_map, media_urls=None, model=model_cls)
                # Strip keys that don't exist on the model (harmless extras from JSON)
                model_cols = set(model_cls.__table__.columns.keys())
                filtered = {k: v for k, v in clean.items() if k in model_cols}
                model_cls(**filtered)
                checked += 1
            except Exception as e:
                errors += 1
                record_id = raw.get("_lease_ref") or raw.get("_charge_ref") or raw.get("email") or raw.get("title") or raw.get("slug") or raw.get("name") or f"index_{i}"
                err_msg = f"{json_path.name}[{record_id}] -> {model_cls.__name__}: {type(e).__name__}: {e}"
                error_details.append(err_msg)
                if errors <= 20:
                    logger.error("[DRY RUN] %s", err_msg)

    logger.info("=" * 60)
    logger.info("[DRY RUN] VALIDATION SUMMARY")
    logger.info("=" * 60)
    logger.info("Records checked: %d", checked)
    logger.info("Errors found:    %d", errors)
    if errors > 20:
        logger.warning("... and %d more errors (showing first 20)", errors - 20)
    if errors:
        logger.error("[DRY RUN] FAILED — %d validation errors detected. Fix before running.", errors)
    else:
        logger.info("[DRY RUN] PASSED — all records valid.")

    return {"checked": checked, "errors": errors, "details": error_details}


async def run(
    only: list[str] | None = None,
    quick: bool = False,
    dry_run: bool = False,
    skip_media: bool = False,
    create_auth_users: bool = False,
    regenerate: bool = False,
) -> None:
    """Execute the full data loading pipeline."""
    # Numeric-prefixed modules require importlib (Python can't import modules starting with digits)
    def _mod(path: str):
        return importlib.import_module(path)

    gen_activity = _mod("seed_data.generators.02_generate_activity").main
    gen_seed = _mod("seed_data.generators.01_generate_seed_data").main
    gen_media = _mod("seed_data.generators.03_generate_media").main
    load_all_activity = _mod("seed_data.loaders.04_activity_loader").load_all_activity
    IDMap = _mod("seed_data.loaders.01_base").IDMap
    load_all_hardcoded = _mod("seed_data.loaders.02_hardcoded_loader").load_all_hardcoded
    upload_media = _mod("seed_data.loaders.05_media_loader").upload_media
    load_all_seed = _mod("seed_data.loaders.03_seed_loader").load_all_seed

    id_map = IDMap()
    start = datetime.now()

    # Determine which categories to load
    load_hardcoded = only is None or "hardcoded" in only
    load_seed = only is None or "seed" in only
    load_generated = only is None or "generated" in only
    load_media_only = only is not None and "media" in only and len(only) == 1
    load_media = not skip_media and (load_hardcoded or load_seed or load_media_only)

    # ── Step 0: Generate JSON if --regenerate flag is passed ────────
    # By default, load from committed JSON files (stable, deterministic).
    # Pass --regenerate to re-generate seed/activity JSON from generators.
    if regenerate and load_seed and not dry_run:
        logger.info("Regenerating Category 2 seed JSON files...")
        gen_seed()

    if regenerate and load_generated and not dry_run:
        logger.info("Regenerating Category 3 activity JSON files...")
        gen_activity(seed=42)

    # ── Step 0.25: Generate placeholder media files ──────────────
    if regenerate and load_media and not dry_run:
        logger.info("Generating placeholder media files...")
        gen_media()

    # ── Step 0.5: Upload media ─────────────────────────────────
    media_urls: dict[str, str] = {}
    if load_media and not dry_run:
        logger.info("Uploading media files to Cloudinary...")
        media_urls = await upload_media(dry_run=dry_run, user_id_override=1)
        logger.info("Media upload complete: %d files mapped", len(media_urls))
    elif load_media and dry_run:
        media_urls = await upload_media(dry_run=True, user_id_override=1)

    # ── Guard: alert when image URLs cannot be resolved ──────────
    # If media upload was skipped (--skip-media) or produced no mappings, every
    # media/ placeholder will be stored as NULL (resolvers never persist a
    # relative path). Warn loudly so the operator knows images will be blank.
    if (load_hardcoded or load_seed) and not dry_run and not media_urls:
        logger.error(
            "MEDIA NOT UPLOADED — image/avatar fields for %s data will be stored "
            "as NULL. To get real Cloudinary URLs, run WITHOUT --skip-media and "
            "ensure CLOUDINARY_* credentials are set. The load continues, but "
            "images will be blank until re-seeded or repaired via "
            "seed_data/fix_media_urls.py.",
            "hardcoded/seed" if load_hardcoded and load_seed else ("hardcoded" if load_hardcoded else "seed"),
        )

    # ── Step 1: Hardcoded data ─────────────────────────────────
    if load_hardcoded:
        logger.info("=" * 60)
        logger.info("LOADING CATEGORY 1: HARDCODED DATA")
        logger.info("=" * 60)
        if dry_run:
            logger.info("[DRY RUN] Validating hardcoded data schemas...")
        else:
            results = await load_all_hardcoded(id_map, media_urls)
            _print_results("Hardcoded", results)

    # ── Step 2: Seed data ──────────────────────────────────────
    if load_seed:
        logger.info("=" * 60)
        logger.info("LOADING CATEGORY 2: SEED DATA")
        logger.info("=" * 60)
        if dry_run:
            logger.info("[DRY RUN] Validating seed data schemas...")
        else:
            results = await load_all_seed(id_map, media_urls)
            _print_results("Seed", results)

    # ── Step 2.5: Validate loaded properties through Pydantic schemas ──
    if (load_hardcoded or load_seed) and not dry_run:
        logger.info("=" * 60)
        logger.info("POST-LOAD VALIDATION: PROPERTIES")
        logger.info("=" * 60)
        await _validate_loaded_properties(sample_size=20)

    # ── Step 2.75: Create Supabase Auth users for seed data ──────
    if create_auth_users and (load_hardcoded or load_seed) and not dry_run:
        logger.info("=" * 60)
        logger.info("CREATING SUPABASE AUTH USERS FOR SEED DATA")
        logger.info("=" * 60)
        try:
            create_auth = _mod("seed_data.03_create_auth_users").run
            await create_auth(password="Test@123", dry_run=False, confirm=True)
        except Exception as exc:
            logger.warning("Auth user creation failed (non-fatal): %s", exc)

    # ── Step 3: Generated activity ──────────────────────────────
    if load_generated:
        logger.info("=" * 60)
        logger.info("LOADING CATEGORY 3: GENERATED ACTIVITY")
        logger.info("=" * 60)
        if dry_run:
            logger.info("[DRY RUN] Validating generated activity schemas...")
        else:
            results = await load_all_activity(id_map)
            _print_results("Generated", results)

    # ── Dry-run validation pass ─────────────────────────────────
    if dry_run:
        logger.info("=" * 60)
        logger.info("[DRY RUN] SCHEMA VALIDATION")
        logger.info("=" * 60)
        validation = await _dry_run_validate(only=only)
        if validation["errors"] > 0:
            logger.error("[DRY RUN] Exiting with error code 1 due to %d validation failures", validation["errors"])
            sys.exit(1)

    # ── Summary ────────────────────────────────────────────────
    elapsed = datetime.now() - start
    logger.info("=" * 60)
    logger.info("DATA SEEDING COMPLETE")
    logger.info("=" * 60)
    logger.info("Elapsed: %.1f seconds", elapsed.total_seconds())
    logger.info("IDMap entries: %d", sum(len(v) for v in id_map._maps.values()))

    # Print IDMap summary
    for entity, keys in id_map._maps.items():
        logger.info("  %s: %d IDs resolved", entity, len(keys))


def _print_results(category: str, results: dict) -> None:
    total_created = sum(r.get("created", 0) for r in results.values())
    total_skipped = sum(r.get("skipped", 0) for r in results.values())
    logger.info("%s total: %d created, %d skipped across %d entity types",
                category, total_created, total_skipped, len(results))


def main() -> None:
    setup_logging()
    parser = argparse.ArgumentParser(description="360Ghar Data Seeding Orchestrator")
    parser.add_argument("--only", type=str, default=None,
                        help="Comma-separated categories to load: hardcoded,seed,generated,media")
    parser.add_argument("--quick", action="store_true", help="Reduced data for faster loading")
    parser.add_argument("--dry-run", action="store_true", help="Validate without DB writes")
    parser.add_argument("--skip-media", action="store_true", help="Skip media upload")
    parser.add_argument("--create-auth-users", action="store_true",
                        help="Create Supabase Auth users for seed users with password Test@123")
    parser.add_argument("--regenerate", action="store_true",
                        help="Re-generate seed/activity JSON from generators before loading (default: use committed JSON)")
    args = parser.parse_args()

    only = args.only.split(",") if args.only else None
    asyncio.run(run(
        only=only,
        quick=args.quick,
        dry_run=args.dry_run,
        skip_media=args.skip_media,
        create_auth_users=args.create_auth_users,
        regenerate=args.regenerate,
    ))


if __name__ == "__main__":
    main()
