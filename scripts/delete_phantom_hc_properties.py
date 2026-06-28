"""Delete the 108 phantom duplicate properties whose main_image_url and
property_images.image_url point at non-existent Cloudinary assets under
``360ghar/hc_properties/<NNNNN>-slug/listing_images/<room>.webp``.

RCA (2026-06-17)
----------------
A second seed run inserted 108 duplicate properties (ids 1610-1717) whose
image URLs were never actually uploaded to Cloudinary -- every URL returns
HTTP 404.  Each of these broken properties is an exact duplicate (same
full_address + latitude + longitude + bedrooms) of an existing working
property whose images DO load via the
``/image/upload/v{VERSION}/360ghar/properties/<id>/...`` pattern.

This script:

1. Identifies the broken set via the ``hc_properties`` URL signature.
2. Maps each broken property to its working twin (earliest id wins).
3. Repoints the 22 ``user_swipes`` rows on broken props to the twin,
   dropping any that would violate ``idx_user_swipes_unique(user_id, property_id)``.
4. Deletes the broken properties; ON DELETE CASCADE removes their
   property_images (955) and property_amenities (712) automatically.

All steps run in a single transaction; any inconsistency (missing twin,
multiple twins, FK violation) aborts the run.

Usage::

    cd backend
    source .venv/bin/activate
    python scripts/delete_phantom_hc_properties.py           # dry-run (default)
    python scripts/delete_phantom_hc_properties.py --apply   # commit
"""

from __future__ import annotations

import argparse
import os
import sys
from collections import Counter

from dotenv import load_dotenv

load_dotenv(".env.dev")

BROKEN_URL_SIGNATURE = "%/image/upload/360ghar/hc_properties/%"
TWIN_JOIN = """
    COALESCE(b.full_address, '') = COALESCE(w.full_address, '')
    AND b.latitude IS NOT NULL
    AND w.latitude IS NOT NULL
    AND b.latitude = w.latitude
    AND b.longitude = w.longitude
    AND COALESCE(b.bedrooms, -1) = COALESCE(w.bedrooms, -1)
"""


def _engine():
    from sqlalchemy import create_engine

    url = os.environ["DATABASE_URL"]
    if "+psycopg" not in url:
        url = url.replace("postgresql://", "postgresql+psycopg://", 1)
    return create_engine(url)


def _broken_signature_filter(column: str) -> str:
    return f"{column} LIKE :broken_sig"


def _discover(eng) -> tuple[list[tuple[int, int, str]], list[int]]:
    """Return (broken_id, twin_id, address) triples and the raw broken id list.

    Each broken prop is mapped to its earliest-id working twin (canonical).
    Some addresses have multiple working twins; we pick the smallest id.
    Aborts only if a broken prop has ZERO working twins (no safe repoint target).
    """
    from sqlalchemy import text

    # _broken_signature_filter and TWIN_JOIN are module-level constant strings
    # (no user input) so they are safe to interpolate into the query text.
    # All dynamic values (broken_sig, bid) are bound parameters.
    with eng.connect() as c:
        broken_ids = [
            r[0]
            for r in c.execute(
                text(
                    f"SELECT id FROM properties WHERE {_broken_signature_filter('main_image_url')} ORDER BY id"
                ),
                {"broken_sig": BROKEN_URL_SIGNATURE},
            ).fetchall()
        ]

        if not broken_ids:
            return [], []

        twins: list[tuple[int, int, str]] = []
        missing: list[int] = []
        for bid in broken_ids:
            # Earliest working twin wins as the canonical repoint target.
            row = c.execute(
                text(
                    f"""
                    SELECT w.id, b.full_address, count(*) OVER () AS n_twins
                    FROM properties b
                    JOIN properties w
                      ON {TWIN_JOIN}
                    WHERE b.id = :bid
                      AND w.id <> b.id
                      AND NOT ({_broken_signature_filter('w.main_image_url')})
                    ORDER BY w.id
                    LIMIT 1
                    """
                ),
                {"bid": bid, "broken_sig": BROKEN_URL_SIGNATURE},
            ).first()
            if row is None:
                missing.append(bid)
            else:
                twins.append((bid, row[0], row[1] or ""))

        if missing:
            print("ERROR: no working twin found for some broken props; aborting.", file=sys.stderr)
            for bid in missing[:20]:
                print(f"  broken prop {bid}: 0 twins (no repoint target)", file=sys.stderr)
            sys.exit(1)

        return twins, broken_ids


def _plan_swipe_repoints(eng, twins: list[tuple[int, int, str]]) -> list[dict]:
    """For each swipe on a broken prop, decide UPDATE-to-twin or DELETE.

    DELETE is chosen when the same (user_id, twin) swipe already exists, to
    respect the unique index idx_user_swipes_unique(user_id, property_id).
    """
    from sqlalchemy import bindparam, text

    if not twins:
        return []

    broken_to_twin = {bid: wid for bid, wid, _ in twins}
    broken_ids = list(broken_to_twin.keys())

    with eng.connect() as c:
        swipes = c.execute(
            text(
                """
                SELECT us.id, us.user_id, us.property_id, us.is_liked
                FROM user_swipes us
                WHERE us.property_id IN :broken_ids
                ORDER BY us.id
                FOR UPDATE OF us
                """
            ).bindparams(bindparam("broken_ids", expanding=True)),
            {"broken_ids": broken_ids},
        ).fetchall()

        plans: list[dict] = []
        for sid, uid, pid, liked in swipes:
            twin = broken_to_twin[pid]
            exists = c.execute(
                text(
                    "SELECT 1 FROM user_swipes WHERE user_id = :u AND property_id = :p LIMIT 1"
                ),
                {"u": uid, "p": twin},
            ).first()
            if exists:
                plans.append(
                    {"action": "DELETE", "swipe_id": sid, "user_id": uid,
                     "broken_pid": pid, "twin_pid": twin, "liked": liked}
                )
            else:
                plans.append(
                    {"action": "UPDATE", "swipe_id": sid, "user_id": uid,
                     "broken_pid": pid, "twin_pid": twin, "liked": liked}
                )
        return plans


def _preview_counts(eng, broken_ids: list[int]) -> dict:
    from sqlalchemy import bindparam, text

    if not broken_ids:
        return {"properties": 0, "images": 0, "amenities": 0, "swipes": 0}
    with eng.connect() as c:
        return {
            "properties": len(broken_ids),
            "images": c.execute(
                text("SELECT count(*) FROM property_images WHERE property_id IN :ids")
                .bindparams(bindparam("ids", expanding=True)),
                {"ids": broken_ids},
            ).scalar(),
            "amenities": c.execute(
                text("SELECT count(*) FROM property_amenities WHERE property_id IN :ids")
                .bindparams(bindparam("ids", expanding=True)),
                {"ids": broken_ids},
            ).scalar(),
            "swipes": c.execute(
                text("SELECT count(*) FROM user_swipes WHERE property_id IN :ids")
                .bindparams(bindparam("ids", expanding=True)),
                {"ids": broken_ids},
            ).scalar(),
        }


def _print_plan(twins, swipe_plans, counts):
    print(f"\nBroken properties to delete: {counts['properties']}")
    print(f"  property_images that will cascade-delete: {counts['images']}")
    print(f"  property_amenities that will cascade-delete: {counts['amenities']}")
    print(f"  user_swipes currently on broken props: {counts['swipes']}")

    print("\nBroken -> working twin mapping (first 20 shown):")
    for bid, wid, addr in twins[:20]:
        print(f"  broken {bid} -> twin {wid} | {addr[:60]}")
    if len(twins) > 20:
        print(f"  ... and {len(twins) - 20} more")

    actions = Counter(p["action"] for p in swipe_plans)
    print("\nSwipe repoint plan:")
    print(f"  UPDATE to twin: {actions.get('UPDATE', 0)}")
    print(f"  DELETE (already swiped twin): {actions.get('DELETE', 0)}")
    for p in swipe_plans[:15]:
        print(
            f"    swipe {p['swipe_id']}: user {p['user_id']} "
            f"{p['broken_pid']}->{p['twin_pid'] if p['action'] == 'UPDATE' else '(drop)'} "
            f"liked={p['liked']}"
        )
    if len(swipe_plans) > 15:
        print(f"    ... and {len(swipe_plans) - 15} more")


def _apply(eng, twins, swipe_plans, broken_ids):
    from sqlalchemy import bindparam, text

    with eng.begin() as c:
        # 1. Repoint / drop swipes BEFORE delete to honor the unique index.
        updates = [p for p in swipe_plans if p["action"] == "UPDATE"]
        deletes = [p for p in swipe_plans if p["action"] == "DELETE"]

        for p in updates:
            c.execute(
                text("UPDATE user_swipes SET property_id = :twin WHERE id = :sid"),
                {"twin": p["twin_pid"], "sid": p["swipe_id"]},
            )
        if deletes:
            delete_ids = [p["swipe_id"] for p in deletes]
            c.execute(
                text("DELETE FROM user_swipes WHERE id IN :ids")
                .bindparams(bindparam("ids", expanding=True)),
                {"ids": delete_ids},
            )

        # 2. Delete broken properties. ON DELETE CASCADE removes
        #    property_images, property_amenities, and any leftover swipes.
        c.execute(
            text("DELETE FROM properties WHERE id IN :ids")
            .bindparams(bindparam("ids", expanding=True)),
            {"ids": broken_ids},
        )

        # 3. Sanity check: no orphans remain.
        orphans = c.execute(
            text(
                "SELECT count(*) FROM user_swipes s "
                "WHERE s.property_id IS NOT NULL "
                "AND s.property_id NOT IN (SELECT id FROM properties)"
            )
        ).scalar()
        if orphans:
            raise RuntimeError(f"orphaned swipes detected after delete: {orphans}")

        still_broken = c.execute(
            text(
                "SELECT count(*) FROM properties WHERE main_image_url LIKE :sig"
            ),
            {"sig": BROKEN_URL_SIGNATURE},
        ).scalar()
        if still_broken:
            raise RuntimeError(f"{still_broken} broken properties remain after delete")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Delete the 108 phantom hc_properties duplicate listings (broken Cloudinary URLs)."
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Commit the delete (default is dry-run).",
    )
    args = parser.parse_args()

    eng = _engine()

    twins, broken_ids = _discover(eng)
    if not broken_ids:
        print("No phantom hc_properties properties found. Nothing to do.")
        return

    swipe_plans = _plan_swipe_repoints(eng, twins)
    counts = _preview_counts(eng, broken_ids)
    _print_plan(twins, swipe_plans, counts)

    if not args.apply:
        print("\n*** DRY RUN -- no changes written. Re-run with --apply to commit. ***")
        return

    _apply(eng, twins, swipe_plans, broken_ids)
    print("\n*** Changes committed. ***")
    print(f"  deleted {len(broken_ids)} phantom properties (cascaded images + amenities)")
    print(
        f"  swipes: {sum(1 for p in swipe_plans if p['action'] == 'UPDATE')} repointed, "
        f"{sum(1 for p in swipe_plans if p['action'] == 'DELETE')} dropped"
    )


if __name__ == "__main__":
    main()
