"""MCP tool names: the widget export matches the server, and every widget tool is registered."""

import json
import re
from pathlib import Path

import pytest

from app.mcp.chatgpt import WIDGETS
from app.mcp.tool_names import TOOL_NAMES_EXPORT, registered_tool_names, render_tool_names_export


@pytest.mark.asyncio
async def test_widget_export_matches_registered_tools():
    names = await registered_tool_names()

    assert TOOL_NAMES_EXPORT.read_text() == render_tool_names_export(names), (
        "tool-names.json is stale. Run: uv run python scripts/export_tool_names.py"
    )


@pytest.mark.asyncio
async def test_every_widget_tool_is_registered_on_the_server():
    registered = set(await registered_tool_names())

    for widget, config in WIDGETS.items():
        missing = [tool for tool in config["tools"] if tool not in registered]
        assert not missing, f"{widget} links tools the server does not register: {missing}"


def test_tool_names_use_underscores():
    # Dotted names (discovery.search) never reached the server. Keep every name underscored.
    import json

    names = json.loads(TOOL_NAMES_EXPORT.read_text())
    assert names and all("." not in name for name in names)


# ---------------------------------------------------------------- widget callTool drift (widgets-mcp-0)

WIDGET_SOURCES = Path(__file__).resolve().parents[2] / "chatgpt-widgets" / "src"
CALL_TOOL_LITERAL = re.compile(r"""callTool(?:<[^>\n]*>)?\(\s*['"]([^'"]+)['"]""")


def _widget_call_literals() -> set[str]:
    literals: set[str] = set()
    for path in WIDGET_SOURCES.rglob("*.ts*"):
        if "generated" in path.parts:
            continue
        literals.update(CALL_TOOL_LITERAL.findall(path.read_text(encoding="utf-8")))
    return literals


def test_every_widget_call_tool_literal_is_a_registered_tool_name():
    """A new callTool literal that the server does not register fails here.

    No exceptions: every literal must be registered.
    """
    registered = set(json.loads(TOOL_NAMES_EXPORT.read_text()))
    literals = _widget_call_literals()
    assert literals, "no callTool literals found; check WIDGET_SOURCES"

    unknown = literals - registered
    assert not unknown, f"callTool names the server does not register: {sorted(unknown)}"

