#!/usr/bin/env python3
"""Write the MCP tool-name list the widgets import (chatgpt-widgets/src/generated/tool-names.json)."""

from __future__ import annotations

import asyncio
import os
import sys

os.environ.setdefault(
    "DATABASE_URL", "postgresql+psycopg://test_user:test_password@localhost:5432/test_db"
)
os.environ.setdefault(
    "ASYNC_DATABASE_URL", "postgresql+psycopg://test_user:test_password@localhost:5432/test_db"
)
os.environ.setdefault("SUPABASE_URL", "https://mock.supabase.co")
os.environ.setdefault("SUPABASE_PUBLISHABLE_KEY", "mock")
os.environ.setdefault("SUPABASE_SECRET_KEY", "mock")
os.environ.setdefault("ENVIRONMENT", "test")

from app.mcp.tool_names import (  # noqa: E402
    TOOL_NAMES_EXPORT,
    registered_tool_names,
    render_tool_names_export,
)


def main() -> int:
    names = asyncio.run(registered_tool_names())
    TOOL_NAMES_EXPORT.parent.mkdir(parents=True, exist_ok=True)
    TOOL_NAMES_EXPORT.write_text(render_tool_names_export(names))
    print(f"wrote {TOOL_NAMES_EXPORT} ({len(names)} tools)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
