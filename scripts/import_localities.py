#!/usr/bin/env python3
"""Load app/services/content/data/locality_seed.json into the localities table.

One-time import. Safe to repeat: it upserts by slug, and --prune also deletes slugs that left
the snapshot. The snapshot is committed in this repo, so the website repo is never read at
runtime. Refuses a non-local database unless --allow-remote is given.

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

import sqlalchemy as sa
from sqlalchemy.engine import make_url

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
    data = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
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
    parser.add_argument("--prune", action="store_true", help="delete rows whose slug is not in the snapshot")
    args = parser.parse_args()
    raw = os.environ.get("DATABASE_URL")
    if not raw:
        sys.exit("DATABASE_URL is not set")
    url = make_url(raw)  # handles percent-encoded passwords and bracketed IPv6 hosts
    local = url.host in LOCAL_HOSTS
    if not local and not args.allow_remote:
        sys.exit("Refusing a non-local database. Pass --allow-remote to override.")
    url = url.set(drivername="postgresql+psycopg")
    if not local:
        url = url.update_query_dict({"sslmode": "require"})
    rows = snapshot_rows()
    engine = sa.create_engine(url)
    with engine.begin() as conn:
        conn.execute(UPSERT, rows)
        pruned = 0
        if args.prune:
            pruned = conn.execute(
                sa.text("DELETE FROM localities WHERE slug <> ALL(:slugs)"), {"slugs": [r["slug"] for r in rows]}
            ).rowcount
    print(f"imported {len(rows)} localities, pruned {pruned}")


if __name__ == "__main__":
    main()
