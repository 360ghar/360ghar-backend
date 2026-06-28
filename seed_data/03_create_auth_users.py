#!/usr/bin/env python3
"""
Create Supabase Auth users for all seed users with a shared password.

Reads users where ``is_seed_data = true`` and ``supabase_user_id`` is a
placeholder (``seed-*`` or ``PLACEHOLDER_*``), creates a real Supabase
Auth user via the GoTrue Admin API, and updates the local ``users`` row
with the real ``supabase_user_id`` UUID.

Usage:
    uv run python seed_data/03_create_auth_users.py
    uv run python seed_data/03_create_auth_users.py --password MyP@ss1
    uv run python seed_data/03_create_auth_users.py --dry-run
    uv run python seed_data/03_create_auth_users.py --confirm
"""

from __future__ import annotations

import argparse
import asyncio
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select, update

from app.core.auth import admin_create_user, admin_get_user_by_email
from app.core.database import AsyncSessionLocal
from app.core.logging import get_logger, setup_logging
from app.models.users import User

logger = get_logger(__name__)

PLACEHOLDER_PATTERN = re.compile(r"^(seed-|PLACEHOLDER_)")


@dataclass
class UserToProcess:
    id: int
    email: str
    name: str
    old_supabase_id: str


async def find_seed_users_without_auth() -> list[UserToProcess]:
    """Find all users that still have placeholder supabase_user_id

    (``seed-*`` or ``PLACEHOLDER_*``). Uses raw column selection to avoid
    pulling columns that may not exist on the remote DB (e.g. ``email_verified``).
    """
    users: list[UserToProcess] = []
    async with AsyncSessionLocal() as session:
        stmt = select(
            User.id,
            User.email,
            User.full_name,
            User.supabase_user_id,
        ).where(
            User.email.isnot(None),
        )
        result = await session.execute(stmt)
        for row in result.all():
            if row.supabase_user_id and PLACEHOLDER_PATTERN.match(str(row.supabase_user_id)):
                users.append(
                    UserToProcess(
                        id=row.id,
                        email=row.email,
                        name=row.full_name or row.email,
                        old_supabase_id=row.supabase_user_id,
                    )
                )
    logger.info("Found %d users needing auth user creation", len(users))
    return users


async def process_user(
    user: UserToProcess,
    password: str,
    dry_run: bool,
) -> str:
    """Create a Supabase Auth user for a single seed user.

    Returns a status string: 'created', 'skipped (already exists)',
    'skipped (no email)', or 'failed: <reason>'.
    """
    if not user.email:
        return "skipped (no email)"

    # Check if Supabase Auth user already exists
    existing = await admin_get_user_by_email(user.email)
    if existing:
        supabase_id = existing["id"]
        if not dry_run:
            async with AsyncSessionLocal() as session:
                await session.execute(
                    update(User)
                    .where(User.id == user.id)
                    .values(supabase_user_id=supabase_id, is_seed_data=True)
                )
                await session.commit()
        logger.info(
            "%s → already exists (supabase_user_id=%s%s)",
            user.email, supabase_id, " [DRY RUN]" if dry_run else "",
        )
        return "skipped (already exists)"

    if dry_run:
        logger.info("%s → would create with password='%s'", user.email, password)
        return "would create (dry-run)"

    # Create Supabase Auth user
    created = await admin_create_user(
        email=user.email,
        password=password,
        email_confirm=True,
        user_metadata={"full_name": user.name, "is_seed_data": True},
    )
    if not created:
        logger.warning("Failed to create auth user for %s", user.email)
        return "failed"

    supabase_id = created["id"]

    # Update the local user row with the real Supabase Auth UUID and seed flag
    async with AsyncSessionLocal() as session:
        await session.execute(
            update(User)
            .where(User.id == user.id)
            .values(supabase_user_id=supabase_id, is_seed_data=True)
        )
        await session.commit()

    logger.info(
        "%s → created (supabase_user_id=%s)",
        user.email, supabase_id,
    )
    return "created"


async def run(
    password: str = "Test@123",
    dry_run: bool = False,
    confirm: bool = False,
) -> None:
    """Main execution: find seed users, create auth users, update supabase_user_id."""
    start = datetime.now()

    users = await find_seed_users_without_auth()
    if not users:
        logger.info("No seed users need auth user creation. All set!")
        return

    if not dry_run and not confirm:
        logger.warning(
            "This will create %d Supabase Auth users with password='%s'. "
            "Pass --confirm to proceed (or --dry-run to preview).",
            len(users), password,
        )
        return

    summary = {"created": 0, "skipped (already exists)": 0, "failed": 0}
    for user in users:
        status = await process_user(user, password, dry_run)
        if status in summary:
            summary[status] += 1
        elif status.startswith("skipped"):
            summary["skipped (already exists)"] += 1

    elapsed = datetime.now() - start
    logger.info("=" * 60)
    logger.info("AUTH USER CREATION COMPLETE")
    logger.info("=" * 60)
    logger.info("Total seed users processed: %d", len(users))
    for key, count in summary.items():
        logger.info("  %s: %d", key, count)
    if dry_run:
        logger.info("DRY RUN — no changes were made")
    logger.info("Elapsed: %.1f seconds", elapsed.total_seconds())


def main() -> None:
    setup_logging()
    parser = argparse.ArgumentParser(
        description="Create Supabase Auth users for seed data",
    )
    parser.add_argument(
        "--password", type=str, default="Test@123",
        help="Password for all seed users (default: Test@123)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Preview which users would be created without making changes",
    )
    parser.add_argument(
        "--confirm", action="store_true",
        help="Confirm and proceed with auth user creation",
    )
    args = parser.parse_args()

    if args.dry_run:
        logger.info("DRY RUN MODE — no changes will be made")

    asyncio.run(run(
        password=args.password,
        dry_run=args.dry_run,
        confirm=args.confirm or args.dry_run,
    ))


if __name__ == "__main__":
    main()
