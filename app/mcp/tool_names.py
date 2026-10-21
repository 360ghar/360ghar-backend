"""The one list of MCP tool names the server registers.

The widgets read ``chatgpt-widgets/src/generated/tool-names.json`` so their
``callTool`` names are constants that match the server. The drift test in
``tests/contract/test_tool_names.py`` fails when the file is stale. Regenerate
it with ``uv run python scripts/export_tool_names.py``.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOOL_NAMES_EXPORT = ROOT / "chatgpt-widgets" / "src" / "generated" / "tool-names.json"


async def registered_tool_names() -> list[str]:
    """Sorted names of every tool on the user and admin MCP servers."""
    from app.mcp.admin.server import admin_mcp
    from app.mcp.user.server import user_mcp

    names: set[str] = set()
    for server in (user_mcp, admin_mcp):
        names.update(tool.name for tool in await server.list_tools())
    return sorted(names)


def render_tool_names_export(names: list[str]) -> str:
    """The exact file content for a list of names."""
    return json.dumps(names, indent=2) + "\n"
