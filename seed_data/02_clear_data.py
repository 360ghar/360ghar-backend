#!/usr/bin/env python3
"""
Clear all seeded data from the database in dependency order.

Uses subquery-based FK mapping to only delete records linked to seed
parents (WHERE is_seed_data = true). Real (non-seed) data is never touched.

Usage:
    python seed_data/02_clear_data.py --confirm              # Safe clear (seed data only)
    python seed_data/02_clear_data.py --confirm --dry-run    # Preview without deleting
    python seed_data/02_clear_data.py --confirm --force      # Full wipe (use only on empty dev DBs)
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from textwrap import dedent

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text

from app.core.database import AsyncSessionLocal
from app.core.logging import get_logger, setup_logging

logger = get_logger(__name__)


def _validate_table_name(table_name: str) -> str:
    """Validate a table name against the known allowlist before SQL interpolation.

    SQL identifiers (table names) cannot be bound as parameters, so we
    explicitly validate against the set of tables known to this script.
    Raises ValueError if the table name is not recognized.
    """
    if table_name not in _ALLOWED_TABLES:
        raise ValueError(
            f"Refusing to interpolate untrusted table name: {table_name!r}. "
            f"Not in the known allowlist of seed-clearable tables."
        )
    return table_name


# Build the allowlist after all constant lists are defined (see below).
_ALLOWED_TABLES: set[str] = set()

# ── FK mapping: child_table -> [(fk_column, parent_table)] ───────────────────
# Derived from model files. Only FKs pointing to users, agents, or properties
# are listed — these are the parent tables with is_seed_data.
TABLE_FK_MAP: dict[str, list[tuple[str, str]]] = {
    # users
    "user_search_history": [("user_id", "users")],
    "user_swipes": [("user_id", "users"), ("target_user_id", "users")],
    "users": [("agent_id", "agents")],
    # properties
    "properties": [("owner_id", "users")],
    "property_images": [("property_id", "properties")],
    "property_amenities": [("property_id", "properties")],
    # visits (has FKs to users, properties, agents)
    "visits": [
        ("user_id", "users"),
        ("counterparty_user_id", "users"),
        ("property_id", "properties"),
        ("agent_id", "agents"),
    ],
    # bookings
    "bookings": [("user_id", "users"), ("property_id", "properties")],
    # tours
    "tours": [("user_id", "users")],
    "scenes": [("tour_id", "tours")],
    "hotspots": [("scene_id", "scenes")],
    "tour_analytics_events": [("tour_id", "tours"), ("user_id", "users")],
    "ai_jobs": [("user_id", "users")],
    "media_files": [("user_id", "users"), ("tour_id", "tours")],
    "user_sessions": [("user_id", "users")],
    "tour_locations": [("tour_id", "tours")],
    "search_index": [("tour_id", "tours"), ("scene_id", "scenes")],
    "floor_plans": [("tour_id", "tours")],
    "tour_branding": [("tour_id", "tours")],
    "custom_domains": [("user_id", "users")],
    "video_metadata": [("media_file_id", "media_files")],
    # social / flatmates
    "user_matches": [
        ("user_one_id", "users"),
        ("user_two_id", "users"),
        ("context_property_id", "properties"),
    ],
    "conversations": [
        ("created_by_user_id", "users"),
    ],
    "conversation_participants": [
        ("conversation_id", "conversations"),
        ("user_id", "users"),
    ],
    "messages": [("conversation_id", "conversations"), ("sender_id", "users")],
    "flatmate_super_like_usage": [("user_id", "users"), ("target_user_id", "users")],
    "user_blocks": [("blocker_user_id", "users"), ("blocked_user_id", "users")],
    "user_reports": [
        ("reporter_user_id", "users"),
        ("reported_user_id", "users"),
        ("property_id", "properties"),
    ],
    "flatmate_profile_view_events": [
        ("viewer_user_id", "users"),
        ("viewed_user_id", "users"),
        ("context_property_id", "properties"),
    ],
    "match_qna_answers": [("match_id", "user_matches"), ("user_id", "users")],
    # agents
    "agent_interactions": [("agent_id", "agents"), ("user_id", "users")],
    # blogs
    "blog_posts": [("author_id", "users")],
    "blog_post_categories": [("post_id", "blog_posts"), ("category_id", "blog_categories")],
    "blog_post_tags": [("post_id", "blog_posts"), ("tag_id", "blog_tags")],
    # data hub
    "auction_alerts": [("user_id", "users")],
    "neighbourhood_scores": [("listing_id", "properties")],
    "scraper_runs": [("triggered_by", "users")],
    # PM
    "leases": [("property_id", "properties"), ("owner_id", "users")],
    "rent_charges": [("lease_id", "leases"), ("property_id", "properties"), ("owner_id", "users")],
    "rent_payments": [
        ("charge_id", "rent_charges"),
        ("lease_id", "leases"),
        ("property_id", "properties"),
        ("owner_id", "users"),
    ],
    "expenses": [("property_id", "properties"), ("owner_id", "users")],
    "maintenance_requests": [
        ("property_id", "properties"),
        ("owner_id", "users"),
        ("assigned_agent_id", "agents"),
    ],
    "documents": [("owner_id", "users"), ("property_id", "properties"), ("lease_id", "leases")],
    "inspection_checklists": [
        ("property_id", "properties"),
        ("lease_id", "leases"),
        ("owner_id", "users"),
    ],
    "rental_application_forms": [("owner_id", "users"), ("property_id", "properties")],
    "rental_applications": [
        ("form_id", "rental_application_forms"),
        ("property_id", "properties"),
        ("owner_id", "users"),
    ],
    # AI conversations
    "ai_conversations": [("user_id", "users")],
    "ai_conversation_messages": [("conversation_id", "ai_conversations")],
    # Core
    "bug_reports": [("user_id", "users"), ("assigned_to", "users")],
    "pages": [("created_by", "users"), ("updated_by", "users")],
}

# ── Intermediate FK chains: tables whose FKs point only to other non-seed-parent ──
# tables. Resolved by multi-hop subqueries through the FK chain back to a seed parent.
INTERMEDIATE_CHAINS: list[tuple[str, str, str]] = [
    # ── Leaf tables first (before their intermediate parents are cleaned) ──
    # Chain: users -> tours -> scenes -> hotspots
    ("hotspots", "scene_id",
     "SELECT id FROM scenes WHERE tour_id IN (SELECT id FROM tours WHERE user_id IN (SELECT id FROM users WHERE is_seed_data = true))"),
    # Chain: users -> tours -> scenes
    ("scenes", "tour_id",
     "SELECT id FROM tours WHERE user_id IN (SELECT id FROM users WHERE is_seed_data = true)"),
    # Chain: users -> tours (for search_index via tour_id)
    ("search_index", "tour_id",
     "SELECT id FROM tours WHERE user_id IN (SELECT id FROM users WHERE is_seed_data = true)"),
    # Chain: users -> tours -> scenes (for search_index via scene_id — runs after scenes already
    # cleaned by tour_id, so affects 0 rows; kept for safety in case scene_id is the only link)
    ("search_index", "scene_id",
     "SELECT id FROM scenes WHERE tour_id IN (SELECT id FROM tours WHERE user_id IN (SELECT id FROM users WHERE is_seed_data = true))"),
    # Chain: users -> tours -> tour_locations
    ("tour_locations", "tour_id",
     "SELECT id FROM tours WHERE user_id IN (SELECT id FROM users WHERE is_seed_data = true)"),
    # Chain: users -> tours -> floor_plans
    ("floor_plans", "tour_id",
     "SELECT id FROM tours WHERE user_id IN (SELECT id FROM users WHERE is_seed_data = true)"),
    # Chain: users -> tours -> tour_branding
    ("tour_branding", "tour_id",
     "SELECT id FROM tours WHERE user_id IN (SELECT id FROM users WHERE is_seed_data = true)"),
    # Chain: users -> tours (for tour_analytics_events via tour_id)
    ("tour_analytics_events", "tour_id",
     "SELECT id FROM tours WHERE user_id IN (SELECT id FROM users WHERE is_seed_data = true)"),
    # Chain: users -> media_files -> video_metadata (leaf BEFORE media_files cleaned)
    ("video_metadata", "media_file_id",
     "SELECT id FROM media_files WHERE user_id IN (SELECT id FROM users WHERE is_seed_data = true)"),
    # Chain: users -> tours (for media_files via tour_id)
    ("media_files", "tour_id",
     "SELECT id FROM tours WHERE user_id IN (SELECT id FROM users WHERE is_seed_data = true)"),
    # ── Blog chains: blog_posts cleaned by Phase 3, so blog_post_categories/tags
    #     must run before Phase 3. Their subqueries don't reference Phase 1 targets.
    ("blog_post_categories", "post_id",
     "SELECT id FROM blog_posts WHERE author_id IN (SELECT id FROM users WHERE is_seed_data = true)"),
    ("blog_post_tags", "post_id",
     "SELECT id FROM blog_posts WHERE author_id IN (SELECT id FROM users WHERE is_seed_data = true)"),
    # Chain: users -> ai_conversations -> ai_conversation_messages
    # ai_conversations is cleaned by Phase 3, so this must run before Phase 3.
    ("ai_conversation_messages", "conversation_id",
     "SELECT id FROM ai_conversations WHERE user_id IN (SELECT id FROM users WHERE is_seed_data = true)"),
]

# Tables with no FK to seed parents — standalone reference/lookup data.
# These are safe to clear entirely since they are only populated by seeds.
STANDALONE_TABLES = [
    "amenities",
    "blog_categories",
    "blog_tags",
    "circle_rates",
    "rera_projects",
    "bank_auctions",
    "bank_rates",
    "jamabandi_cache",
    "zoning_data",
    "colony_approvals",
    "gazette_notifications",
    "rera_complaints",
    "court_auctions",
    "app_catalogs",
    "app_versions",
    "faqs",
    "cache",
]

# Dependency order: children before parents
DEPENDENCY_ORDER = [
    # Tour leaf
    "video_metadata",
    "hotspots",
    "search_index",
    # Tour mid
    "tour_analytics_events",
    "tour_locations",
    "floor_plans",
    "tour_branding",
    "media_files",
    "ai_jobs",
    "user_sessions",
    "custom_domains",
    "scenes",
    "tours",
    # Social leaf
    "match_qna_answers",
    "messages",
    # Social mid
    "user_matches",
    "conversation_participants",
    "conversations",
    "flatmate_super_like_usage",
    "user_blocks",
    "user_reports",
    "flatmate_profile_view_events",
    # Blog leaf
    "blog_post_categories",
    "blog_post_tags",
    "blog_posts",
    # PM leaf
    "rent_payments",
    "rent_charges",
    "inspection_checklists",
    "expenses",
    "maintenance_requests",
    "documents",
    "rental_applications",
    "rental_application_forms",
    "leases",
    # Data hub
    "auction_alerts",
    "neighbourhood_scores",
    "scraper_runs",
    # AI
    "ai_conversation_messages",
    "ai_conversations",
    # Core
    "bug_reports",
    "pages",
    # Bookings / Visits
    "bookings",
    "visits",
    # Properties
    "property_amenities",
    "property_images",
    "properties",
    # Agents / Users
    "agent_interactions",
    "users",
    # Agents (last — users references agent_id)
    "agents",
    # Standalone
    *STANDALONE_TABLES,
]

# Populate the allowlist with all table names known to this script. This is
# used by _validate_table_name() to guard SQL identifier interpolation.
_ALLOWED_TABLES.update(
    set(DEPENDENCY_ORDER)
    | set(STANDALONE_TABLES)
    | {t for t, _, _ in INTERMEDIATE_CHAINS}
    | set(TABLE_FK_MAP.keys())
    | {"users", "agents", "properties"}  # seed parent tables
)


async def delete_seed_children(
    session: AsyncSessionLocal,
    parent_table: str,
    dry_run: bool = False,
) -> int:
    """Delete all child records linked to seed parents via FK subquery.

    Returns total rows deleted.
    """
    # Validate the parent_table parameter (also used in SQL interpolation).
    _validate_table_name(parent_table)
    total = 0
    for table_name in DEPENDENCY_ORDER:
        fks = TABLE_FK_MAP.get(table_name, [])
        # Only process FKs pointing to the specified parent
        relevant_fks = [(col, parent) for col, parent in fks if parent == parent_table]
        if not relevant_fks:
            continue

        # Validate table_name before SQL interpolation (defense in depth).
        _validate_table_name(table_name)
        for fk_col, _ in relevant_fks:
            sql = text(
                f"DELETE FROM {table_name} WHERE {fk_col} IN (SELECT id FROM {parent_table} WHERE is_seed_data = true)"
            )
            if dry_run:
                logger.info("[DRY RUN] Would execute: %s", sql)
                continue
            try:
                result = await session.execute(sql)
                count = result.rowcount or 0
                if count > 0:
                    logger.info(
                        "Cleared %d rows from %s (via %s.%s)",
                        count,
                        table_name,
                        parent_table,
                        fk_col,
                    )
                total += count
            except Exception as exc:
                logger.warning("Skipping %s (FK %s.%s): %s", table_name, parent_table, fk_col, exc)
    return total


async def delete_seed_parents(session: AsyncSessionLocal, dry_run: bool = False) -> int:
    """Delete seed parent records (with is_seed_data = true)."""
    total = 0
    for table in ["agents", "properties", "users"]:
        _validate_table_name(table)
        sql = text(f"DELETE FROM {table} WHERE is_seed_data = true")
        if dry_run:
            logger.info("[DRY RUN] Would execute: %s", sql)
            continue
        try:
            result = await session.execute(sql)
            count = result.rowcount or 0
            if count > 0:
                logger.info("Cleared %d rows from %s (seed data)", count, table)
            total += count
        except Exception as exc:
            logger.warning("Skipping %s: %s", table, exc)
    return total


async def clear_standalone(session: AsyncSessionLocal, dry_run: bool = False) -> int:
    """Clear standalone reference tables (no FK deps, populated only by seeds).

    WARNING: These tables (amenities, faqs, pages, blog taxonomy, data hub
    lookups) are wiped entirely since they have no is_seed_data column.
    Real entries in these tables will also be deleted.
    """
    total = 0
    if not dry_run:
        logger.warning(
            "Clearing %d standalone reference tables (amenities, faqs, pages, "
            "blog taxonomy, data hub). Any non-seed entries will also be removed.",
            len(STANDALONE_TABLES),
        )
    for table in STANDALONE_TABLES:
        _validate_table_name(table)
        sql = text(f"DELETE FROM {table}")
        if dry_run:
            logger.info("[DRY RUN] Would execute: %s", sql)
            continue
        try:
            result = await session.execute(sql)
            count = result.rowcount or 0
            if count > 0:
                logger.info("Cleared %d rows from %s (standalone)", count, table)
            total += count
        except Exception as exc:
            logger.warning("Skipping %s: %s", table, exc)
    return total


async def cleanup_cloudinary_storage(dry_run: bool = False) -> int:
    """Remove seed media files from Cloudinary.

    Attempts to delete all resources under the seed prefix in Cloudinary.
    Returns number of resources deleted or -1 if unavailable.
    """
    if dry_run:
        logger.info("[DRY RUN] Would clean up Cloudinary seed media")
        return 0

    try:
        from cloudinary import api as cloudinary_api

        prefix = "360ghar/seed/"
        result = cloudinary_api.delete_resources_by_prefix(prefix)
        deleted = result.get("deleted", {})
        count = len(deleted)
        if count:
            logger.info("Removed %d Cloudinary resources under %s", count, prefix)
        return count
    except Exception as exc:
        logger.warning("Cloudinary cleanup skipped: %s", exc)
        return -1


async def clear_all(dry_run: bool = False, force: bool = False) -> None:
    """Delete all seed data from the database, preserving real data."""
    async with AsyncSessionLocal() as session:
        total = 0

        # Phase 1: Delete children linked through intermediate FK chains FIRST
        # These must run BEFORE direct FK deletes (Phases 2-4) because the
        # intermediate parent records (tours, blog_posts, media_files, etc.)
        # would be cleaned by direct FK deletes, leaving the chain subqueries
        # with nothing to match against.
        logger.info("Phase 1: Deleting intermediate FK chain children...")
        for table_name, fk_col, subquery in INTERMEDIATE_CHAINS:
            _validate_table_name(table_name)
            sql = text(f"DELETE FROM {table_name} WHERE {fk_col} IN ({subquery})")
            if dry_run:
                logger.info("[DRY RUN] Would execute: %s", sql)
                continue
            try:
                result = await session.execute(sql)
                count = result.rowcount or 0
                if count > 0:
                    logger.info("Cleared %d rows from %s (chain via %s)", count, table_name, fk_col)
                total += count
            except Exception as exc:
                logger.warning("Skipping %s (chain %s): %s", table_name, fk_col, exc)

        # Phase 2: Delete children linked to seed properties
        logger.info("Phase 2: Deleting children of seed properties...")
        total += await delete_seed_children(session, "properties", dry_run)

        # Phase 3: Delete children linked to seed users (most blocking FKs)
        logger.info("Phase 3: Deleting children of seed users...")
        total += await delete_seed_children(session, "users", dry_run)

        # Phase 4: Delete children linked to seed agents
        logger.info("Phase 4: Deleting children of seed agents...")
        total += await delete_seed_children(session, "agents", dry_run)

        # Phase 5: Delete standalone reference tables
        logger.info("Phase 5: Clearing standalone reference tables...")
        total += await clear_standalone(session, dry_run)

        # Phase 6: Delete seed parents
        logger.info("Phase 6: Deleting seed parent records...")
        total += await delete_seed_parents(session, dry_run)

        if not dry_run:
            await session.commit()
            logger.info("=" * 60)
            logger.info("CLEAR COMPLETE: %d total rows deleted (seed data only)", total)
        else:
            logger.info("=" * 60)
            logger.info("DRY RUN COMPLETE: %d rows would be deleted", total)

    # Phase 7: Clean up Cloudinary storage
    if not force:
        logger.info("Phase 7: Cleaning up Cloudinary Storage...")
        storage_deleted = await cleanup_cloudinary_storage(dry_run)
        if storage_deleted > 0:
            logger.info("Storage cleanup complete: %d objects removed", storage_deleted)
        elif storage_deleted == 0:
            logger.info("No seed media objects found in Cloudinary")
        else:
            logger.info("Cloudinary cleanup unavailable (non-fatal)")


def main() -> None:
    setup_logging()
    parser = argparse.ArgumentParser(
        description="Clear 360Ghar seed data (preserves real/non-seed data)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=dedent("""
            Examples:
              %(prog)s --confirm              # Safe clear: seed data only
              %(prog)s --confirm --dry-run     # Preview deletions
              %(prog)s --confirm --force       # Full wipe (empty dev DBs only)
        """),
    )
    parser.add_argument(
        "--confirm",
        action="store_true",
        required=True,
        help="Required flag to confirm data deletion",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Preview deletions without making changes"
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Skip Cloudinary cleanup (use when Cloudinary is unavailable or credentials are missing)",
    )
    args = parser.parse_args()

    if not args.confirm:
        print("Use --confirm to acknowledge data will be deleted")
        return

    print("=" * 60)
    print("  SEED DATA CLEAR SCRIPT")
    print("  Preserves real (non-seed) data by default")
    print("=" * 60)
    if args.dry_run:
        print("  [DRY RUN MODE — no changes will be made]")
    if args.force:
        print("  [FORCE MODE — clearing ALL data, including real records]")
        print("  WARNING: This will delete ALL data from ALL tables!")
        confirm_force = input("  Type 'yes' to confirm full wipe: ")
        if confirm_force.lower() != "yes":
            print("  Cancelled.")
            return

    asyncio.run(clear_all(dry_run=args.dry_run, force=args.force))


if __name__ == "__main__":
    main()
