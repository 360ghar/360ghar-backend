"""Enum-like MCP tool arguments advertise their allowed values (be-ai-15).

A plain ``str`` argument hides the allowed values from MCP hosts, and the tool then
answers a bad value with an error only after the call. Every enum-like argument must
be an Enum or a Literal, so the JSON schema lists the values.
"""

from __future__ import annotations

import pytest

from app.mcp.admin.server import admin_mcp
from app.mcp.user.server import user_mcp

ENUM_LIKE = {
    "status",
    "priority",
    "urgency",
    "category",
    "payment_method",
    "property_type",
    "purpose",
    "occupancy",
    "booking_status",
    "payment_status",
}


async def _schemas(server):
    tools = await server.list_tools()
    for tool in tools:
        yield tool.name, tool.parameters or {}


def _plain_string_props(schema: dict) -> list[str]:
    props = schema.get("properties", {}) or {}
    found: list[str] = []
    for name, spec in props.items():
        if name not in ENUM_LIKE:
            continue
        options = spec.get("anyOf", [spec])
        types = [option.get("type") for option in options]
        has_values = "enum" in spec or any("enum" in option for option in options)
        if "string" in types and not has_values:
            found.append(name)
    return found


@pytest.mark.asyncio
@pytest.mark.parametrize("server", [user_mcp, admin_mcp], ids=["user", "admin"])
async def test_enum_like_arguments_list_their_values(server):
    offenders: dict[str, list[str]] = {}
    checked = 0
    async for tool_name, schema in _schemas(server):
        checked += 1
        bad = _plain_string_props(schema)
        if bad:
            offenders[tool_name] = bad
    assert checked > 0
    assert not offenders, f"plain string arguments that should be enums: {offenders}"
