#!/usr/bin/env python3
"""Run Supabase SQL migrations against the remote database.

Reads DATABASE_URL from the environment or a .env file, connects directly
to Postgres, and applies each migration in supabase/migrations/ in order.

Migrations are tracked in a ``schema_migrations`` table so running this
script multiple times is safe — only pending migrations are executed.

Usage:
    uv run python scripts/run_supabase_migrations.py              # apply all pending (uses .env.dev)
    uv run python scripts/run_supabase_migrations.py --dry-run    # preview only
    uv run python scripts/run_supabase_migrations.py --file 20260621000008_flatmates_social.sql
    uv run python scripts/run_supabase_migrations.py --env .env.prod  # use a different env file
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

MIGRATIONS_DIR = Path(__file__).resolve().parents[1] / "supabase" / "migrations"

# ── Migration tracking DDL ────────────────────────────────────────────────────

_CREATE_MIGRATIONS_TABLE = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version TEXT PRIMARY KEY,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
"""


def _discover_sql_files(target_file: str | None = None) -> list[Path]:
    """Return sorted list of .sql files from the migrations directory."""
    if not MIGRATIONS_DIR.is_dir():
        print(f"ERROR: Migrations directory not found: {MIGRATIONS_DIR}", file=sys.stderr)
        sys.exit(1)

    files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    if not files:
        print(f"WARNING: No .sql files found in {MIGRATIONS_DIR}", file=sys.stderr)
        return []

    if target_file:
        matches = [f for f in files if f.name == target_file]
        if not matches:
            print(f"ERROR: Migration file not found: {target_file}", file=sys.stderr)
            print("Available files:", file=sys.stderr)
            for f in files:
                print(f"  {f.name}", file=sys.stderr)
            sys.exit(1)
        return matches

    return files


def _get_applied_versions(cursor) -> set[str]:
    """Return the set of migration versions already recorded."""
    cursor.execute("SELECT version FROM schema_migrations ORDER BY version")
    return {row[0] for row in cursor.fetchall()}


def _normalise_database_url(url: str) -> str:
    """Percent-encode special characters (like ``@``) in the password field."""
    from urllib.parse import quote, urlparse, urlunparse

    parsed = urlparse(url)
    if parsed.password:
        encoded_password = quote(parsed.password, safe="")
        netloc = f"{parsed.username}:{encoded_password}@{parsed.hostname}"
        if parsed.port:
            netloc += f":{parsed.port}"
        return urlunparse(parsed._replace(netloc=netloc))
    return url


def run_migrations(*, dry_run: bool = False, target_file: str | None = None, env_file: str | None = None) -> None:
    """Connect to the database and apply pending migrations."""
    import psycopg

    env_path = Path(env_file) if env_file else None
    if env_path and not env_path.is_file():
        print(f"ERROR: Env file not found: {env_path}", file=sys.stderr)
        sys.exit(1)
    load_dotenv(env_path)

    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        print(
            "ERROR: DATABASE_URL environment variable is not set.\n"
            "Set it in your shell or in a .env file in the project root.",
            file=sys.stderr,
        )
        sys.exit(1)

    database_url = _normalise_database_url(database_url)

    # Supabase pooler requires SSL — append sslmode if not already present
    if "sslmode=" not in database_url:
        separator = "&" if "?" in database_url else "?"
        database_url = f"{database_url}{separator}sslmode=require"

    sql_files = _discover_sql_files(target_file)
    if not sql_files:
        print("No migration files found.")
        return

    with psycopg.connect(database_url) as conn:
        conn.autocommit = False

        with conn.cursor() as cur:
            cur.execute(_CREATE_MIGRATIONS_TABLE)

            applied = _get_applied_versions(cur)
            pending = [f for f in sql_files if f.stem not in applied]

            if not pending:
                print(f"All {len(sql_files)} migration(s) already applied. Nothing to do.")
                return

            print(f"Found {len(pending)} pending migration(s) out of {len(sql_files)} total.\n")

            if dry_run:
                for f in pending:
                    print(f"  [DRY RUN] Would apply: {f.name}")
                print("\nNo changes were made.")
                return

            for f in pending:
                sql = f.read_text(encoding="utf-8")
                print(f"Applying {f.name}...", end=" ", flush=True)
                try:
                    cur.execute(sql)
                    cur.execute(
                        "INSERT INTO schema_migrations (version) VALUES (%s)",
                        (f.stem,),
                    )
                    conn.commit()
                    print("OK")
                except Exception as e:
                    conn.rollback()
                    print(f"FAILED\n\nError: {e}")
                    print(f"\nThe migration {f.name} failed. Remaining migrations were skipped.")
                    sys.exit(1)

            print(f"\nAll {len(pending)} migration(s) applied successfully.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run Supabase SQL migrations against the remote database.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show which migrations would run without executing them.",
    )
    parser.add_argument(
        "--file",
        type=str,
        default=None,
        help="Run a specific migration file by name (e.g. 20260621000008_flatmates_social.sql).",
    )
    parser.add_argument(
        "--env",
        type=str,
        default=".env.dev",
        help="Path to the .env file to load (default: .env.dev).",
    )
    args = parser.parse_args()
    run_migrations(dry_run=args.dry_run, target_file=args.file, env_file=args.env)


if __name__ == "__main__":
    main()
