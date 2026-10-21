#!/usr/bin/env python3
"""Rebuild app/services/content/data/locality_seed.json from the website data files.

The locality master list lives in the website repo (360ghar-web-ui/src/data). The
backend never reads that repo at runtime: this script copies the fields the content
engine needs into a JSON snapshot that is committed here. Run it again when the
website list changes, then commit the new snapshot.

Usage:
    uv run python scripts/import_content_seed.py ../360ghar-web-ui
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "app/services/content/data/locality_seed.json"
# 'project' rows are builder projects, not places. They are not locality pages.
PLACE_TYPES = {"locality", "sector", "society", "village", "road", "township", "phase"}
CITY_NAMES = {"gurgaon": "Gurugram"}


def main(web_repo: Path) -> None:
    data = web_repo / "src/data"
    localities = json.loads((data / "localities.json").read_text(encoding="utf-8"))
    landmarks = json.loads((data / "locality-landmarks.json").read_text(encoding="utf-8"))
    price_context = json.loads((data / "priceContext.json").read_text(encoding="utf-8"))
    sha = subprocess.run(
        ["git", "-C", str(web_repo), "rev-parse", "--short", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    ).stdout.strip()

    places = []
    for row in localities:
        if row["entityType"] not in PLACE_TYPES:
            continue
        city = row["city"]
        places.append(
            {
                "slug": row["slug"],
                "name": row["name"],
                "city": CITY_NAMES.get(city.lower(), city.title()),
                "type": row["entityType"],
                "parent": row.get("parentLocality") or None,
                "aliases": [a for a in row.get("aliases", []) if a != row["name"]],
            }
        )
    places_by_slug = {p["slug"] for p in places}
    # The landmark file also covers other cities that are not in the locality list, and one
    # Gurugram road under a "-gurgaon" slug. Report what is left out.
    landmark_map: dict[str, list[dict[str, str]]] = {}
    for item in landmarks:
        slug = item["slug"] if item["slug"] in places_by_slug else item["slug"].removesuffix("-gurgaon")
        if slug in places_by_slug:
            landmark_map[slug] = item["landmarks"]
        else:
            print(f"skipped landmarks for {item['slug']}: not in the locality list")
    snapshot = {
        "source": f"360ghar-web-ui@{sha}" if sha else "360ghar-web-ui",
        "generated_on": datetime.now(UTC).date().isoformat(),
        "localities": places,
        "landmarks": landmark_map,
        "price_context": price_context,
    }
    # One locality per line keeps a regenerated snapshot reviewable in a diff.
    head = {k: v for k, v in snapshot.items() if k != "localities"}
    lines = ",\n".join("    " + json.dumps(p, ensure_ascii=False) for p in places)
    body = json.dumps(head, ensure_ascii=False, indent=2)[:-2]  # drop the closing brace
    OUT.write_text(f'{body},\n  "localities": [\n{lines}\n  ]\n}}\n', encoding="utf-8")
    print(f"wrote {OUT} ({len(places)} places, {len(snapshot['landmarks'])} with landmarks)")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(Path(sys.argv[1]))
