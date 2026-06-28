"""
Tests for MCP tool registration on user and admin servers.

Verifies that tools are properly registered and have correct annotations
per Apps SDK compliance.
"""

import pytest

from app.mcp.admin import admin_mcp
from app.mcp.user.server import user_mcp


class TestDiscoveryToolRegistration:
    """Tests that discovery tools are properly registered on the MCP server."""

    @pytest.mark.asyncio
    async def test_discovery_tools_exist(self):
        tools = await user_mcp.list_tools()
        names = [t.name for t in tools]
        discovery = [n for n in names if n.startswith("discovery_")]
        assert len(discovery) >= 5, f"Expected >= 5 discovery tools, got: {discovery}"

    @pytest.mark.asyncio
    async def test_discovery_search_registered(self):
        tools = await user_mcp.list_tools()
        names = [t.name for t in tools]
        assert "discovery_search" in names

    @pytest.mark.asyncio
    async def test_discovery_property_get_registered(self):
        tools = await user_mcp.list_tools()
        names = [t.name for t in tools]
        assert "discovery_property_get" in names

    @pytest.mark.asyncio
    async def test_discovery_feed_registered(self):
        tools = await user_mcp.list_tools()
        names = [t.name for t in tools]
        assert "discovery_feed" in names

    @pytest.mark.asyncio
    async def test_discovery_amenities_registered(self):
        tools = await user_mcp.list_tools()
        names = [t.name for t in tools]
        assert "discovery_amenities" in names

    @pytest.mark.asyncio
    async def test_discovery_recommendations_registered(self):
        tools = await user_mcp.list_tools()
        names = [t.name for t in tools]
        assert "discovery_recommendations" in names


class TestVisitToolRegistration:
    """Tests that visit tools are properly registered."""

    @pytest.mark.asyncio
    async def test_visits_schedule_registered(self):
        tools = await user_mcp.list_tools()
        names = [t.name for t in tools]
        assert "visits_schedule" in names

    @pytest.mark.asyncio
    async def test_visits_list_registered(self):
        tools = await user_mcp.list_tools()
        names = [t.name for t in tools]
        assert "visits_list" in names

    @pytest.mark.asyncio
    async def test_visits_get_registered(self):
        tools = await user_mcp.list_tools()
        names = [t.name for t in tools]
        assert "visits_get" in names

    @pytest.mark.asyncio
    async def test_visits_cancel_registered(self):
        tools = await user_mcp.list_tools()
        names = [t.name for t in tools]
        assert "visits_cancel" in names


class TestOwnerToolRegistration:
    """Tests that owner tools are properly registered."""

    @pytest.mark.asyncio
    async def test_owner_properties_list_registered(self):
        tools = await user_mcp.list_tools()
        names = [t.name for t in tools]
        assert "owner_properties_list" in names

    @pytest.mark.asyncio
    async def test_owner_properties_create_registered(self):
        tools = await user_mcp.list_tools()
        names = [t.name for t in tools]
        assert "owner_properties_create" in names

    @pytest.mark.asyncio
    async def test_owner_dashboard_overview_registered(self):
        tools = await user_mcp.list_tools()
        names = [t.name for t in tools]
        assert "owner_dashboard_overview" in names


class TestBookingToolRegistration:
    """Tests that booking tools are properly registered."""

    @pytest.mark.asyncio
    async def test_bookings_create_registered(self):
        tools = await user_mcp.list_tools()
        names = [t.name for t in tools]
        assert "bookings_create" in names

    @pytest.mark.asyncio
    async def test_bookings_list_registered(self):
        tools = await user_mcp.list_tools()
        names = [t.name for t in tools]
        assert "bookings_list" in names


class TestAdminToolRegistration:
    """Tests that admin MCP tools are properly registered."""

    @pytest.mark.asyncio
    async def test_agent_tools_on_admin_server(self):
        tools = await admin_mcp.list_tools()
        names = [t.name for t in tools]
        agent_tools = [n for n in names if n.startswith("agent_")]
        assert len(agent_tools) >= 5, f"Expected >= 5 agent tools, got: {agent_tools}"

    @pytest.mark.asyncio
    async def test_admin_system_status_registered(self):
        tools = await admin_mcp.list_tools()
        names = [t.name for t in tools]
        assert "admin_system_status" in names


class TestToolAnnotations:
    """Tests that MCP tools have proper annotations per Apps SDK compliance."""

    @pytest.mark.asyncio
    async def test_discovery_read_tools_have_read_only_hint(self):
        """Pure read/discovery tools should have readOnlyHint=True."""
        read_only_tools = {"discovery_search", "discovery_property_get", "discovery_feed", "discovery_amenities"}
        tools = await user_mcp.list_tools()
        for tool in tools:
            if tool.name in read_only_tools:
                ann = tool.annotations
                read_only = getattr(ann, "readOnlyHint", None)
                assert read_only is True, f"{tool.name} should be readOnly, got {read_only}"

    @pytest.mark.asyncio
    async def test_all_tools_have_security_schemes(self):
        tools = await user_mcp.list_tools()
        for tool in tools:
            ann = tool.annotations
            schemes = getattr(ann, "securitySchemes", None)
            assert schemes is not None, f"{tool.name} missing securitySchemes"

    @pytest.mark.asyncio
    async def test_total_tool_count(self):
        tools = await user_mcp.list_tools()
        assert len(tools) >= 30, f"Expected >= 30 user tools, got {len(tools)}"
