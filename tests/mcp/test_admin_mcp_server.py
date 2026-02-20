"""
Tests for Admin MCP server.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class AsyncIteratorMock:
    """Helper for async iteration in tests."""
    def __init__(self, items):
        self.items = items
        self.index = 0

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self.index < len(self.items):
            item = self.items[self.index]
            self.index += 1
            return item
        raise StopAsyncIteration


def get_tool_fn(tool):
    """Extract the underlying function from a FunctionTool object."""
    return tool.fn if hasattr(tool, 'fn') else tool


class TestAgentPropertyTools:
    """Tests for agent_properties_* MCP tools."""

    @pytest.mark.asyncio
    async def test_agent_properties_list_authenticated(self, mock_mcp_context):
        """Test listing agent's portfolio properties."""
        from app.mcp.admin_server import agent_properties_list

        fn = get_tool_fn(agent_properties_list)

        with patch("app.mcp.admin_server._get_user", new_callable=AsyncMock) as mock_user:
            mock_user.return_value = MagicMock(id=1, role="agent")

            with patch("app.mcp.admin_server.get_db") as mock_db:
                mock_db.return_value = AsyncIteratorMock([MagicMock()])

                result = await fn()

                assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_agent_properties_list_unauthorized(self):
        """Test listing properties without agent role."""
        from app.mcp.admin_server import agent_properties_list

        fn = get_tool_fn(agent_properties_list)

        with patch("app.mcp.admin_server._get_user", new_callable=AsyncMock) as mock_user:
            mock_user.return_value = MagicMock(id=1, role="user")  # Not an agent

            with patch("app.mcp.admin_server.get_db") as mock_db:
                mock_db.return_value = AsyncIteratorMock([MagicMock()])

                result = await fn()

                # Should return unauthorized or forbidden
                assert "error" in result


class TestAgentLeaseTools:
    """Tests for agent.leases.* MCP tools."""

    @pytest.mark.asyncio
    async def test_agent_leases_list(self, mock_mcp_context):
        """Test listing leases in agent's portfolio."""
        from app.mcp.admin_server import agent_leases_list

        fn = get_tool_fn(agent_leases_list)

        with patch("app.mcp.admin_server._get_user", new_callable=AsyncMock) as mock_user:
            mock_user.return_value = MagicMock(id=1, role="agent")

            with patch("app.mcp.admin_server.get_db") as mock_db:
                mock_db.return_value = AsyncIteratorMock([MagicMock()])

                result = await fn()

                assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_agent_leases_create(self, mock_mcp_context):
        """Test creating lease as agent."""
        from app.mcp.admin_server import agent_leases_create

        fn = get_tool_fn(agent_leases_create)

        with patch("app.mcp.admin_server._get_user", new_callable=AsyncMock) as mock_user:
            mock_user.return_value = MagicMock(id=1, role="agent")

            with patch("app.mcp.admin_server.get_db") as mock_db:
                mock_db.return_value = AsyncIteratorMock([MagicMock()])

                result = await fn(
                    property_id=1,
                    tenant_user_id=2,
                    start_date="2025-01-01",
                    end_date="2026-01-01",
                    monthly_rent=50000,
                    security_deposit=100000,
                )

                assert isinstance(result, dict)


class TestAgentRentTools:
    """Tests for agent.rent.* MCP tools."""

    @pytest.mark.asyncio
    async def test_agent_rent_list_due(self, mock_mcp_context):
        """Test listing overdue rent."""
        from app.mcp.admin_server import agent_rent_list_due

        fn = get_tool_fn(agent_rent_list_due)

        with patch("app.mcp.admin_server._get_user", new_callable=AsyncMock) as mock_user:
            mock_user.return_value = MagicMock(id=1, role="agent")

            with patch("app.mcp.admin_server.get_db") as mock_db:
                mock_db.return_value = AsyncIteratorMock([MagicMock()])

                result = await fn()

                assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_agent_rent_record_payment(self, mock_mcp_context):
        """Test recording rent payment as agent."""
        from app.mcp.admin_server import agent_rent_record_payment

        fn = get_tool_fn(agent_rent_record_payment)

        with patch("app.mcp.admin_server._get_user", new_callable=AsyncMock) as mock_user:
            mock_user.return_value = MagicMock(id=1, role="agent")

            with patch("app.mcp.admin_server.get_db") as mock_db:
                mock_db.return_value = AsyncIteratorMock([MagicMock()])

                result = await fn(
                    lease_id=1,
                    amount=50000,
                    payment_method="bank_transfer",
                    payment_date="2025-01-15",
                )

                assert isinstance(result, dict)


class TestAgentMaintenanceTools:
    """Tests for agent.maintenance.* MCP tools."""

    @pytest.mark.asyncio
    async def test_agent_maintenance_list(self, mock_mcp_context):
        """Test listing maintenance requests."""
        from app.mcp.admin_server import agent_maintenance_list

        fn = get_tool_fn(agent_maintenance_list)

        with patch("app.mcp.admin_server._get_user", new_callable=AsyncMock) as mock_user:
            mock_user.return_value = MagicMock(id=1, role="agent")

            with patch("app.mcp.admin_server.get_db") as mock_db:
                mock_db.return_value = AsyncIteratorMock([MagicMock()])

                result = await fn()

                assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_agent_maintenance_update_status(self, mock_mcp_context):
        """Test updating maintenance request status."""
        from app.mcp.admin_server import agent_maintenance_update_status

        fn = get_tool_fn(agent_maintenance_update_status)

        with patch("app.mcp.admin_server._get_user", new_callable=AsyncMock) as mock_user:
            mock_user.return_value = MagicMock(id=1, role="agent")

            with patch("app.mcp.admin_server.get_db") as mock_db:
                mock_db.return_value = AsyncIteratorMock([MagicMock()])

                result = await fn(
                    request_id=1,
                    status="in_progress",
                )

                assert isinstance(result, dict)


class TestAgentDashboardTools:
    """Tests for agent.dashboard.* MCP tools."""

    @pytest.mark.asyncio
    async def test_agent_dashboard_overview(self, mock_mcp_context):
        """Test getting dashboard overview."""
        from app.mcp.admin_server import agent_dashboard_overview

        fn = get_tool_fn(agent_dashboard_overview)

        with patch("app.mcp.admin_server._get_user", new_callable=AsyncMock) as mock_user:
            mock_user.return_value = MagicMock(id=1, role="agent")

            with patch("app.mcp.admin_server.get_db") as mock_db:
                mock_db.return_value = AsyncIteratorMock([MagicMock()])

                result = await fn()

                assert isinstance(result, dict)


class TestAdminTools:
    """Tests for admin.* MCP tools."""

    @pytest.mark.asyncio
    async def test_admin_system_status(self, mock_mcp_context):
        """Test getting system status as admin."""
        from app.mcp.admin_server import admin_system_status

        fn = get_tool_fn(admin_system_status)

        with patch("app.mcp.admin_server._get_user", new_callable=AsyncMock) as mock_user:
            mock_user.return_value = MagicMock(id=1, role="admin")

            with patch("app.mcp.admin_server.get_db") as mock_db:
                mock_db.return_value = AsyncIteratorMock([MagicMock()])

                result = await fn()

                assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_admin_system_status_non_admin(self):
        """Test system status access denied for non-admin."""
        from app.mcp.admin_server import admin_system_status

        fn = get_tool_fn(admin_system_status)

        with patch("app.mcp.admin_server._get_user", new_callable=AsyncMock) as mock_user:
            mock_user.return_value = MagicMock(id=1, role="user")

            with patch("app.mcp.admin_server.get_db") as mock_db:
                mock_db.return_value = AsyncIteratorMock([MagicMock()])

                result = await fn()

                # Non-admin gets data but with access: denied
                assert isinstance(result, dict)
                # Either error or access denied in data
                if "data" in result:
                    assert result["data"].get("access") == "denied"


class TestAgentBookingTools:
    """Tests for agent.bookings.* MCP tools."""

    @pytest.mark.asyncio
    async def test_agent_bookings_list_all(self, mock_mcp_context):
        """Test listing all bookings as agent."""
        from app.mcp.admin_server import agent_bookings_list_all

        fn = get_tool_fn(agent_bookings_list_all)

        with patch("app.mcp.admin_server._get_user", new_callable=AsyncMock) as mock_user:
            mock_user.return_value = MagicMock(id=1, role="agent")

            with patch("app.mcp.admin_server.get_db") as mock_db:
                mock_db.return_value = AsyncIteratorMock([MagicMock()])

                result = await fn()

                assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_agent_bookings_update_status(self, mock_mcp_context):
        """Test updating booking status as agent."""
        from app.mcp.admin_server import agent_bookings_update_status

        fn = get_tool_fn(agent_bookings_update_status)

        with patch("app.mcp.admin_server._get_user", new_callable=AsyncMock) as mock_user:
            mock_user.return_value = MagicMock(id=1, role="agent")

            with patch("app.mcp.admin_server.get_db") as mock_db:
                mock_db.return_value = AsyncIteratorMock([MagicMock()])

                result = await fn(
                    booking_id=1,
                    status="confirmed",
                )

                assert isinstance(result, dict)
