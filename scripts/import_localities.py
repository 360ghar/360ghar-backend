#!/usr/bin/env python3
"""Load app/services/content/data/locality_seed.json into the localities table.

One-time import (safe to repeat: it upserts by slug). The snapshot is committed in this
repo, so the website repo is never read at runtime. Refuses a non-local database unless
--allow-remote is given.

Usage:
    DATABASE_URL=postgresql+psycopg://user:pass@localhost:5432/db \
        uv run python scripts/import_localities.py
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from urllib.parse import urlparse

import sqlalchemy as sa

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.run_supabase_migrations import _normalise_database_url  # noqa: E402

SNAPSHOT = Path(__file__).resolve().parents[1] / "app/services/content/data/locality_seed.json"
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}

UPSERT = sa.text(
    """
    INSERT INTO localities (slug, name, city, place_type, parent_slug, aliases, landmarks, source)
    VALUES (:slug, :name, :city, :place_type, :parent_slug,
            CAST(:aliases AS jsonb), CAST(:landmarks AS jsonb), :source)
    ON CONFLICT (slug) DO UPDATE SET
        name = EXCLUDED.name, city = EXCLUDED.city, place_type = EXCLUDED.place_type,
        parent_slug = EXCLUDED.parent_slug, aliases = EXCLUDED.aliases,
        landmarks = EXCLUDED.landmarks, source = EXCLUDED.source, updated_at = now()
    """
)


def snapshot_rows() -> list[dict[str, object]]:
    data = json.loads(SNAPSHOT.read_text())
    landmarks = data["landmarks"]
    return [
        {
            "slug": p["slug"],
            "name": p["name"],
            "city": p["city"],
            "place_type": p["type"],
            "parent_slug": p.get("parent"),
            "aliases": json.dumps(p.get("aliases", []), ensure_ascii=False),
            "landmarks": json.dumps(landmarks.get(p["slug"], []), ensure_ascii=False),
            "source": data["source"],
        }
        for p in data["localities"]
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--allow-remote", action="store_true")
    args = parser.parse_args()
    url = os.environ.get("DATABASE_URL")
    if not url:
        sys.exit("DATABASE_URL is not set")
    url = _normalise_database_url(url)
    if urlparse(url).hostname not in LOCAL_HOSTS and not args.allow_remote:
        sys.exit("Refusing a non-local database. Pass --allow-remote to override.")
    rows = snapshot_rows()
    engine = sa.create_engine(url.replace("postgresql://", "postgresql+psycopg://", 1))
    with engine.begin() as conn:
        conn.execute(UPSERT, rows)
    print(f"imported {len(rows)} localities")


if __name__ == "__main__":
    main()
