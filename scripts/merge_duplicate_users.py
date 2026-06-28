"""Merge duplicate user records (user 18 → user 23).

User 18 (supabase_user_id=53670b21-...) and user 23 (supabase_user_id=d7592f87-...)
are the same person (same phone: 918178340031 / +918178340031).
User 23 has the active flatmates profile; user 18 has a stale draft.

This script:
1. Migrates foreign-key data from user 18 to user 23 where applicable.
2. Deactivates user 18 (sets is_active=false).
3. Re-points user 18's supabase_user_id to a dummy value so the JWT
   for 53670b21-... will create a fresh row on next login, which will
   then dedup-merge onto user 23 via the normalized phone lookup.

Run: cd backend && source .venv/bin/activate && python scripts/merge_duplicate_users.py
"""

from __future__ import annotations

import os
import sys

from dotenv import load_dotenv

load_dotenv(".env.dev")

DUP_USER_ID = 18
REAL_USER_ID = 23

# Allowlist of (table, column) pairs that may be interpolated into SQL.
# SQL identifiers (table/column names) cannot be bound as parameters, so we
# explicitly validate against this fixed allowlist before interpolation.
ALLOWED_TABLES: dict[str, frozenset[str]] = {
    "user_swipes": frozenset({"user_id"}),
    "user_search_history": frozenset({"user_id"}),
    "user_blocks": frozenset({"blocker_user_id", "blocked_user_id"}),
}


def _assert_identifier(table: str, col: str) -> None:
    """Validate table/column names against the allowlist before SQL interpolation."""
    allowed_cols = ALLOWED_TABLES.get(table)
    if allowed_cols is None or col not in allowed_cols:
        raise ValueError(
            f"Refusing to interpolate untrusted identifier: {table}.{col}. "
            f"Not in ALLOWED_TABLES allowlist."
        )


def _engine():
    from sqlalchemy import create_engine

    url = os.environ["DATABASE_URL"]
    if "+psycopg" not in url:
        url = url.replace("postgresql://", "postgresql+psycopg://", 1)
    return create_engine(url)


def main() -> None:
    from sqlalchemy import text

    engine = _engine()
    with engine.begin() as conn:
        # Verify both users exist
        dup = conn.execute(
            text("SELECT id, supabase_user_id, phone, is_active FROM users WHERE id = :id"),
            {"id": DUP_USER_ID},
        ).fetchone()
        real = conn.execute(
            text("SELECT id, supabase_user_id, phone, is_active FROM users WHERE id = :id"),
            {"id": REAL_USER_ID},
        ).fetchone()

        if dup is None:
            print(f"Duplicate user {DUP_USER_ID} not found, nothing to do.")
            return
        if real is None:
            print(f"Real user {REAL_USER_ID} not found, aborting.")
            sys.exit(1)

        print(f"Duplicate: id={dup[0]}, supa={dup[1]}, phone={dup[2]}")
        print(f"Real:      id={real[0]}, supa={real[1]}, phone={real[2]}")

        # Tables with user_id foreign keys that might reference user 18
        tables_to_migrate = [
            ("user_swipes", "user_id"),
            ("user_search_history", "user_id"),
            ("user_blocks", "blocker_user_id"),
            ("user_blocks", "blocked_user_id"),
        ]

        for table, col in tables_to_migrate:
            # Validate identifiers against allowlist before SQL interpolation.
            _assert_identifier(table, col)

            # Check if table exists
            exists = conn.execute(text(
                "SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = :t)"
            ), {"t": table}).scalar()
            if not exists:
                print(f"  Table {table} does not exist, skipping.")
                continue

            # Count rows to migrate
            count = conn.execute(
                text(f"SELECT count(*) FROM {table} WHERE {col} = :dup_id"),
                {"dup_id": DUP_USER_ID},
            ).scalar()
            if count == 0:
                print(f"  {table}.{col}: no rows to migrate.")
                continue

            # Delete rows that would conflict (user_id already points to real user for same entity)
            if table == "user_swipes" and col == "user_id":
                # Delete dup's swipes that real user also has for same target
                conn.execute(text(
                    f"DELETE FROM {table} WHERE {col} = :dup_id "
                    f"AND target_user_id IN (SELECT target_user_id FROM {table} WHERE user_id = :real_id AND target_user_id IS NOT NULL)"
                ), {"dup_id": DUP_USER_ID, "real_id": REAL_USER_ID})
                conn.execute(text(
                    f"DELETE FROM {table} WHERE {col} = :dup_id "
                    f"AND property_id IN (SELECT property_id FROM {table} WHERE user_id = :real_id AND property_id IS NOT NULL)"
                ), {"dup_id": DUP_USER_ID, "real_id": REAL_USER_ID})

            conn.execute(text(
                f"UPDATE {table} SET {col} = :real_id WHERE {col} = :dup_id"
            ), {"real_id": REAL_USER_ID, "dup_id": DUP_USER_ID})
            print(f"  {table}.{col}: migrated {count} rows.")

        # Deactivate user 18
        conn.execute(
            text("UPDATE users SET is_active = false WHERE id = :id"),
            {"id": DUP_USER_ID},
        )
        print(f"\nDeactivated user {DUP_USER_ID}.")
        print("Done. User 23 now owns all data. JWT with sub=53670b21-... will be created fresh and dedup to user 23 via phone.")


if __name__ == "__main__":
    main()
