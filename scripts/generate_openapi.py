#!/usr/bin/env python3
"""Generate the full OpenAPI spec for the 360Ghar backend.

Builds the FastAPI app in testing mode (no external services required), calls
``app.openapi()``, and writes the result to ``docs/openapi.json``. The output
is the authoritative OpenAPI 3.1 document covering every mounted route
(``/api/v1/*``, root-level OAuth well-known, share, websocket, deeplink
well-known/redirect, and MCP discovery endpoints).

Usage:
    uv run python scripts/generate_openapi.py                # write docs/openapi.json
    uv run python scripts/generate_openapi.py --check        # exit 1 if spec would change (CI guard)
    uv run python scripts/generate_openapi.py -o path.json   # custom output path

The script is idempotent: running it repeatedly produces an identical file as
long as the codebase has not changed. Commit the regenerated file whenever
endpoints, schemas, or tags change.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# Stub env so create_app(testing=True) can build without real infra.
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://test_user:test_password@localhost:5432/test_db")
os.environ.setdefault("ASYNC_DATABASE_URL", "postgresql+psycopg://test_user:test_password@localhost:5432/test_db")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("SUPABASE_URL", "https://mock.supabase.co")
os.environ.setdefault("SUPABASE_PUBLISHABLE_KEY", "mock")
os.environ.setdefault("SUPABASE_SECRET_KEY", "mock")
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("CI", "true")
# The server entry follows PUBLIC_BASE_URL. Clear it so the file does not depend on a dev .env.
os.environ["PUBLIC_BASE_URL"] = ""

from app.factory import create_app  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT / "docs" / "openapi.json"


def build_spec() -> dict:
    """Build the app and return its OpenAPI schema dict."""
    app = create_app(testing=True)
    return app.openapi()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("-o", "--output", type=Path, default=DEFAULT_OUT, help="Output file path.")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Do not write; exit 1 if the generated spec differs from the existing file.",
    )
    args = parser.parse_args()

    spec = build_spec()
    payload = json.dumps(spec, indent=2, sort_keys=False, ensure_ascii=False) + "\n"

    if args.check:
        if not args.output.exists():
            print(f"openapi spec missing: {args.output}", file=sys.stderr)
            return 1
        existing = args.output.read_text()
        if existing == payload:
            print(f"openapi spec up to date: {args.output}")
            return 0
        print(f"openapi spec out of date: {args.output}", file=sys.stderr)
        return 1

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(payload)
    path_count = len(spec.get("paths", {}))
    print(f"wrote {args.output} ({path_count} paths)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
