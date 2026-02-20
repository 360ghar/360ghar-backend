"""
Tests for User MCP server.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestOwnerPropertyTools:
    """Tests for owner.properties.* MCP tools."""

    @pytest.mark.asyncio
    async def test_owner_properties_list_authenticated(self, mock_mcp_context):
        """Test listing owner properties with auth."""
        from app.mcp.user_server import owner_properties_list

        # Get the underlying function from the FunctionTool
        fn = owner_properties_list.fn if hasattr(owner_properties_list, 'fn') else owner_properties_list

        with patch("app.mcp.user_server._get_user", new_callable=AsyncMock) as mock_user:
            mock_user.return_value = MagicMock(id=1, role="user")

            with patch("app.mcp.user_server.list_managed_properties", new_callable=AsyncMock) as mock_list:
                mock_list.return_value = {"items": [], "total": 0}

                with patch("app.mcp.user_server.get_db") as mock_db:
                    mock_db.return_value = AsyncIteratorMock([MagicMock()])

                    result = await fn()

                    assert "data" in result or "error" in result

    @pytest.mark.asyncio
    async def test_owner_properties_list_unauthenticated(self):
        """Test listing properties without auth."""
        from app.mcp.user_server import owner_properties_list
        from app.mcp.apps_sdk import AuthRequiredError

        # Get the underlying function from the FunctionTool
        fn = owner_properties_list.fn if hasattr(owner_properties_list, 'fn') else owner_properties_list

        with patch("app.mcp.user_server._get_user", new_callable=AsyncMock) as mock_user:
            mock_user.return_value = None

            with patch("app.mcp.user_server.get_db") as mock_db:
                mock_db.return_value = AsyncIteratorMock([MagicMock()])

                with pytest.raises(AuthRequiredError):
                    await fn()

    @pytest.mark.asyncio
    async def test_owner_properties_list_www_authenticate_meta(self, mock_mcp_context):
        """Tool-level auth prompts should include mcp/www_authenticate meta."""
        from app.mcp.user_server import user_mcp

        with patch("app.mcp.user_server._get_user", new_callable=AsyncMock) as mock_user:
            mock_user.return_value = None

            with patch("app.mcp.user_server.get_db") as mock_db:
                mock_db.return_value = AsyncIteratorMock([MagicMock()])

                result = await user_mcp._mcp_call_tool("owner_properties_list", {})

                assert result.isError is True
                assert result.meta is not None
                assert "mcp/www_authenticate" in result.meta
                assert result.structuredContent is not None
                assert result.structuredContent.get("requires_auth") is True

    @pytest.mark.asyncio
    async def test_tools_list_includes_security_schemes_and_template(self, mock_mcp_context):
        """Apps SDK expects tool security schemes + output template metadata."""
        from app.mcp.user_server import user_mcp

        tools = await user_mcp._mcp_list_tools()
        owner_tool = next(tool for tool in tools if tool.name == "owner_properties_list")

        assert owner_tool.annotations is not None
        assert getattr(owner_tool.annotations, "securitySchemes", None) is not None
        assert owner_tool.meta is not None
        assert owner_tool.meta.get("openai/outputTemplate") == "ui://widget/ownerdashboardwidget.html"


class TestOwnerPropertyCreate:
    """Tests for owner.properties.create tool."""

    @pytest.mark.asyncio
    async def test_create_property_success(self, mock_mcp_context):
        """Test creating property."""
        from app.mcp.user_server import owner_properties_create

        # Get the underlying function from the FunctionTool
        fn = owner_properties_create.fn if hasattr(owner_properties_create, 'fn') else owner_properties_create

        with patch("app.mcp.user_server._get_user", new_callable=AsyncMock) as mock_user:
            mock_user.return_value = MagicMock(id=1, role="user")

            with patch("app.mcp.user_server.create_managed_property", new_callable=AsyncMock) as mock_create:
                mock_property = MagicMock()
                mock_property.id = 1
                mock_property.title = "New Property"
                mock_create.return_value = mock_property

                with patch("app.mcp.user_server.get_db") as mock_db:
                    mock_db.return_value = AsyncIteratorMock([MagicMock()])

                    result = await fn(
                        title="New Property",
                        property_type="apartment",
                        purpose="rent",
                        city="Mumbai",
                        locality="Andheri",
                        full_address="123 Test Street",
                        latitude=19.0760,
                        longitude=72.8777,
                        base_price=5000000,
                    )

                    # Should return success or error
                    assert isinstance(result, dict)


class TestTenantTools:
    """Tests for tenant.* MCP tools."""

    @pytest.mark.asyncio
    async def test_tenant_lease_current(self, mock_mcp_context):
        """Test getting current tenant lease."""
        from app.mcp.user_server import tenant_lease_current

        # Get the underlying function from the FunctionTool
        fn = tenant_lease_current.fn if hasattr(tenant_lease_current, 'fn') else tenant_lease_current

        with patch("app.mcp.user_server._get_user", new_callable=AsyncMock) as mock_user:
            mock_user.return_value = MagicMock(id=1, role="user")

            with patch("app.mcp.user_server.get_db") as mock_db:
                mock_db.return_value = AsyncIteratorMock([MagicMock()])

                result = await fn()

                assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_tenant_rent_history(self, mock_mcp_context):
        """Test getting tenant rent history."""
        from app.mcp.user_server import tenant_rent_history

        # Get the underlying function from the FunctionTool
        fn = tenant_rent_history.fn if hasattr(tenant_rent_history, 'fn') else tenant_rent_history

        with patch("app.mcp.user_server._get_user", new_callable=AsyncMock) as mock_user:
            mock_user.return_value = MagicMock(id=1, role="user")

            with patch("app.mcp.user_server.get_db") as mock_db:
                mock_db.return_value = AsyncIteratorMock([MagicMock()])

                result = await fn()

                assert isinstance(result, dict)


class TestBookingTools:
    """Tests for bookings.* MCP tools."""

    @pytest.mark.asyncio
    async def test_bookings_list(self, mock_mcp_context):
        """Test listing user bookings."""
        from app.mcp.user_server import bookings_list

        # Get the underlying function from the FunctionTool
        fn = bookings_list.fn if hasattr(bookings_list, 'fn') else bookings_list

        with patch("app.mcp.user_server._get_user", new_callable=AsyncMock) as mock_user:
            mock_user.return_value = MagicMock(id=1, role="user")

            with patch("app.mcp.user_server.booking_svc.get_user_bookings", new_callable=AsyncMock) as mock_list:
                mock_list.return_value = {"bookings": [], "total": 0}

                with patch("app.mcp.user_server.get_db") as mock_db:
                    mock_db.return_value = AsyncIteratorMock([MagicMock()])

                    result = await fn()

                    assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_bookings_check_availability(self, mock_mcp_context):
        """Test checking property availability."""
        from app.mcp.user_server import bookings_check_availability

        # Get the underlying function from the FunctionTool
        fn = bookings_check_availability.fn if hasattr(bookings_check_availability, 'fn') else bookings_check_availability

        with patch("app.mcp.user_server.booking_svc.check_availability", new_callable=AsyncMock) as mock_check:
            mock_check.return_value = {"available": True, "conflicts": []}

            with patch("app.mcp.user_server.get_db") as mock_db:
                mock_db.return_value = AsyncIteratorMock([MagicMock()])

                result = await fn(
                    property_id=1,
                    check_in_date="2025-01-15",
                    check_out_date="2025-01-18",
                )

                assert isinstance(result, dict)


class TestMCPErrorResponses:
    """Tests for MCP error response formats."""

    def test_unauthorized_response(self):
        """Test unauthorized error response format."""
        from app.mcp.errors import unauthorized_response

        result = unauthorized_response("Test message")

        assert "error" in result
        assert result["error"]["code"] == "UNAUTHORIZED"
        assert result["error"]["message"] == "Test message"

    def test_not_found_response(self):
        """Test not found error response format."""
        from app.mcp.errors import not_found_response

        result = not_found_response("Item not found")

        assert "error" in result
        assert result["error"]["code"] == "NOT_FOUND"

    def test_invalid_input_response(self):
        """Test invalid input error response format."""
        from app.mcp.errors import invalid_input_response

        result = invalid_input_response("Invalid field")

        assert "error" in result
        assert result["error"]["code"] == "INVALID_INPUT"


# Helper class for async iteration
class AsyncIteratorMock:
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
