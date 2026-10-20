"""Every WIDGETS tool is a registered tool, listed once. Owner maintenance has no tenant widget."""

from app.mcp.chatgpt import WIDGETS, get_widget_name_for_tool
from app.mcp.tool_names import registered_tool_names


async def test_every_widget_tool_is_registered_and_listed_once():
    names = set(await registered_tool_names())
    for widget, config in WIDGETS.items():
        tools = config["tools"]
        assert len(tools) == len(set(tools)), widget
        missing = [t for t in tools if t not in names]
        assert not missing, (widget, missing)


def test_owner_maintenance_tools_are_not_linked_to_the_tenant_widget():
    assert get_widget_name_for_tool("owner_maintenance_list") is None
    assert get_widget_name_for_tool("owner_maintenance_update") is None
    assert get_widget_name_for_tool("tenant_maintenance_list") == "MaintenanceWidget"
