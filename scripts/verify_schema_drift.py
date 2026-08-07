#!/usr/bin/env python3
"""Verify SQLAlchemy models against a live database schema.

Compares every mapped table's columns (``app.models`` Base metadata) with
``information_schema.columns`` on the target database. A column present on
a model but missing from an existing table is a failure (exit 1) — the
drift class that took production down in Aug 2026 when model columns were
shipped without applying the matching supabase/migrations SQL. A table
missing entirely is only a warning (a few model tables are created outside
the migration tree).

Usage:
    uv run python scripts/verify_schema_drift.py
    uv run python scripts/verify_schema_drift.py --env .env.prod
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:
    from run_supabase_migrations import _normalise_database_url
except ImportError:  # run via `python -m scripts.verify_schema_drift`
    from scripts.run_supabase_migrations import _normalise_database_url


def verify_schema_drift(*, env_file: str | None = None) -> int:
    import psycopg

    env_path = Path(env_file) if env_file else None
    if env_path and not env_path.is_file():
        print(f"ERROR: Env file not found: {env_path}", file=sys.stderr)
        return 1
    load_dotenv(env_path)

    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        print(
            "ERROR: DATABASE_URL environment variable is not set.\n"
            "Set it in your shell or in a .env file in the project root.",
            file=sys.stderr,
        )
        return 1

    try:
        import app.models  # noqa: F401  (registers every mapped table on Base.metadata)
        from app.core.database import Base
    except Exception as exc:
        print(
            f"ERROR: failed to load SQLAlchemy models (missing env vars?): {exc}",
            file=sys.stderr,
        )
        return 1

    table_names = sorted(Base.metadata.tables)

    with psycopg.connect(_normalise_database_url(database_url)) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT table_name, column_name FROM information_schema.columns "
                "WHERE table_schema = 'public' AND table_name = ANY(%s)",
                (table_names,),
            )
            rows = cur.fetchall()

    db_columns: dict[str, set[str]] = {}
    for table_name, column_name in rows:
        db_columns.setdefault(table_name, set()).add(column_name)

    missing_tables: list[str] = []
    missing_columns: list[str] = []
    for table_name in table_names:
        if table_name not in db_columns:
            missing_tables.append(table_name)
            continue
        model_columns = {col.name for col in Base.metadata.tables[table_name].columns}
        table_missing = sorted(model_columns - db_columns[table_name])
        if table_missing:
            missing_columns.append(f"{table_name}: {', '.join(table_missing)}")

    if missing_tables:
        print(
            "WARNING: tables in models but missing from the database "
            "(no DDL in migrations?):"
        )
        for name in missing_tables:
            print(f"  - {name}")

    if missing_columns:
        print("ERROR: schema drift — model columns missing from the database:")
        for entry in missing_columns:
            print(f"  - {entry}")
        return 1

    print("OK: every model column exists in the database.")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Check SQLAlchemy models against the live database schema.",
    )
    parser.add_argument(
        "--env",
        default=None,
        help=".env file to load DATABASE_URL from (default: environment only)",
    )
    args = parser.parse_args()
    sys.exit(verify_schema_drift(env_file=args.env))


if __name__ == "__main__":
    main()
