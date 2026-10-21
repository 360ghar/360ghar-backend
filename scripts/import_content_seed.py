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
from datetime import date
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "app/services/content/data/locality_seed.json"
# 'project' rows are builder projects, not places. They are not locality pages.
PLACE_TYPES = {"locality", "sector", "society", "village", "road", "township", "phase"}
CITY_NAMES = {"gurgaon": "Gurugram"}


def main(web_repo: Path) -> None:
    data = web_repo / "src/data"
    localities = json.loads((data / "localities.json").read_text())
    landmarks = json.loads((data / "locality-landmarks.json").read_text())
    price_context = json.loads((data / "priceContext.json").read_text())
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
    snapshot = {
        "source": f"360ghar-web-ui@{sha}" if sha else "360ghar-web-ui",
        "generated_on": date.today().isoformat(),
        "localities": places,
        "landmarks": {item["slug"]: item["landmarks"] for item in landmarks},
        "price_context": price_context,
    }
    OUT.write_text(json.dumps(snapshot, ensure_ascii=False, separators=(",", ":")) + "\n")
    print(f"wrote {OUT} ({len(places)} places, {len(snapshot['landmarks'])} with landmarks)")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(Path(sys.argv[1]))
