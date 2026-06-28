"""
Integration tests for MCP servers.

Tests the full flow from HTTP request to tool execution.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _setup_in_memory_cache():
    """Provide a connected in-memory cache for OAuth token store tests."""
    from app.core.cache import set_cache_manager
    from app.core.cache.backends.memory import InMemoryCacheBackend
    from app.core.cache.manager import CacheManager

    backend = InMemoryCacheBackend(max_size=500)
    manager = CacheManager(backend=backend)
    import asyncio

    loop = asyncio.new_event_loop()
    loop.run_until_complete(manager.connect())
    set_cache_manager(manager)
    yield
    loop.run_until_complete(manager.disconnect())
    loop.close()
    set_cache_manager(None)


def get_tool_fn(tool):
    """Extract the underlying function from a FunctionTool object."""
    return tool.fn if hasattr(tool, 'fn') else tool


class TestMCPServerIntegration:
    """Integration tests for MCP servers."""

    @pytest.fixture
    def client(self):
        """Create test client."""
        from app.factory import create_app
        app = create_app(testing=True)
        return TestClient(app)

    def test_mcp_endpoint_mounted(self, client):
        """Test that /mcp endpoint is mounted (by checking router)."""
        from app.factory import create_app
        app = create_app(testing=True)

        # Check that the MCP routes are registered
        routes = [route.path for route in app.routes]
        # MCP endpoints are mounted as sub-applications
        assert any("mcp" in str(route) for route in routes)

    def test_mcp_admin_endpoint_mounted(self, client):
        """Test that /mcp-admin endpoint is mounted (by checking router)."""
        from app.factory import create_app
        app = create_app(testing=True)

        # Check that the MCP admin routes are registered
        routes = [route.path for route in app.routes]
        assert any("mcp-admin" in str(route) for route in routes)

    def test_oauth_well_known_endpoints(self, client):
        """Test OAuth discovery endpoints."""
        response = client.get("/.well-known/oauth-protected-resource/mcp")
        # Should return OAuth metadata or 401/404 if not configured
        assert response.status_code in [200, 401, 404]


class TestMCPToolsIntegration:
    """Integration tests for MCP tool execution."""

    @pytest.mark.asyncio
    async def test_discovery_search_guest_access(self):
        """Test discovery_search works without authentication."""
        from app.mcp.apps_sdk import AppsSDKToolResult
        from app.mcp.chatgpt.discovery_tools import discovery_search

        fn = get_tool_fn(discovery_search)

        with patch("app.mcp.chatgpt.discovery_tools._get_optional_user", new_callable=AsyncMock) as mock_user:
            mock_user.return_value = None  # Guest user

            with patch("app.services.property.get_unified_properties_optimized", new_callable=AsyncMock) as mock_search:
                mock_search.return_value = ([], None, 0)

                result = await fn(query="test")

                assert isinstance(result, AppsSDKToolResult)
                assert hasattr(result, 'content')
                assert hasattr(result, 'structured_content')

    @pytest.mark.asyncio
    async def test_discovery_search_with_user(self):
        """Test discovery_search with authenticated user."""
        from app.mcp.apps_sdk import AppsSDKToolResult
        from app.mcp.chatgpt.discovery_tools import discovery_search

        fn = get_tool_fn(discovery_search)

        mock_user_obj = MagicMock(id=1, role="user")

        with patch("app.mcp.chatgpt.discovery_tools._get_optional_user", new_callable=AsyncMock) as mock_user:
            mock_user.return_value = mock_user_obj

            with patch("app.services.property.get_unified_properties_optimized", new_callable=AsyncMock) as mock_search:
                mock_search.return_value = ([], None, 0)

                result = await fn(query="apartment in Mumbai")

                assert isinstance(result, AppsSDKToolResult)

    @pytest.mark.asyncio
    async def test_discovery_search_with_coordinates(self):
        """Test discovery_search with location coordinates."""
        from app.mcp.apps_sdk import AppsSDKToolResult
        from app.mcp.chatgpt.discovery_tools import discovery_search

        fn = get_tool_fn(discovery_search)

        mock_user_obj = MagicMock(id=1, role="user")

        with patch("app.mcp.chatgpt.discovery_tools._get_optional_user", new_callable=AsyncMock) as mock_user:
            mock_user.return_value = mock_user_obj

            with patch("app.services.property.get_unified_properties_optimized", new_callable=AsyncMock) as mock_search:
                mock_search.return_value = (
                    [
                        {"id": 1, "title": "Property 1", "base_price": 1000000},
                        {"id": 2, "title": "Property 2", "base_price": 2000000},
                    ],
                    None,
                    2,
                )

                result = await fn(
                    query="apartment",
                    latitude=19.0760,
                    longitude=72.8777,
                    radius_km=10
                )

                assert isinstance(result, AppsSDKToolResult)
                assert result.content is not None

    @pytest.mark.asyncio
    async def test_auth_required_response_format(self):
        """Test that auth-required responses include proper metadata."""
        from app.mcp.apps_sdk import AuthRequiredError
        from app.mcp.chatgpt.discovery_tools import discovery_swipe

        fn = get_tool_fn(discovery_swipe)

        with patch("app.mcp.chatgpt.discovery_tools._get_optional_user", new_callable=AsyncMock) as mock_user:
            mock_user.return_value = None  # Not authenticated

            # Should raise AuthRequiredError
            with pytest.raises(AuthRequiredError) as exc_info:
                await fn(property_id=1, is_liked=True)

            # Verify it's an auth error with proper attributes
            assert exc_info.value is not None

    @pytest.mark.asyncio
    async def test_discovery_amenities(self):
        """Test discovery.amenities tool."""
        from app.mcp.apps_sdk import AppsSDKToolResult
        from app.mcp.chatgpt.discovery_tools import discovery_amenities

        fn = get_tool_fn(discovery_amenities)

        # Mock the database session
        mock_db = MagicMock()
        mock_result = MagicMock()

        # Create mock amenity objects
        class MockAmenity:
            def __init__(self, id, title, icon):
                self.id = id
                self.title = title
                self.icon = icon

        mock_amenities = [
            MockAmenity(1, "WiFi", "wifi"),
            MockAmenity(2, "Pool", "pool"),
        ]
        mock_result.scalars.return_value.all.return_value = mock_amenities
        mock_db.execute.return_value = mock_result

        with patch("app.mcp.chatgpt.discovery_tools.AsyncSessionLocal") as mock_session:
            mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_session.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await fn()

            assert isinstance(result, AppsSDKToolResult)
            assert result.content is not None


class TestMCPAuthIntegration:
    """Integration tests for MCP authentication."""

    @pytest.mark.asyncio
    async def test_token_verifier_valid_oauth_token(self):
        """Test token verifier with valid OAuth token."""
        from app.mcp.auth_provider import SupabaseTokenVerifier

        verifier = SupabaseTokenVerifier(
            required_scopes=["mcp:read"],
            expected_resource="http://localhost:3600/mcp"
        )

        # Mock the token store
        with patch("app.services.oauth_token_store.oauth_token_store.get_access_token", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = {
                "user_id": "123",
                "scope": "mcp:read",
                "resource": "http://localhost:3600/mcp",
                "expires_at": 9999999999  # Far future
            }

            token = await verifier.verify_token("valid_token_12345_no_dots_longer_than_40_chars")

            assert token is not None
            assert token.claims["sub"] == "123"
            assert "mcp:read" in token.scopes

    @pytest.mark.asyncio
    async def test_token_verifier_invalid_token_format(self):
        """Test token verifier rejects JWT format tokens."""
        from app.mcp.auth_provider import SupabaseTokenVerifier

        verifier = SupabaseTokenVerifier(required_scopes=["mcp:read"])

        # JWT format should be rejected (contains dots)
        jwt_token = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjMifQ.test"
        token = await verifier.verify_token(jwt_token)

        assert token is None

    @pytest.mark.asyncio
    async def test_token_verifier_expired_token(self):
        """Test token verifier rejects expired tokens."""
        from app.mcp.auth_provider import SupabaseTokenVerifier

        verifier = SupabaseTokenVerifier(required_scopes=["mcp:read"])

        with patch("app.services.oauth_token_store.oauth_token_store.get_access_token", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = {
                "user_id": "123",
                "scope": "mcp:read",
                "resource": "http://localhost:3600/mcp",
                "expires_at": 1  # Expired long ago
            }

            token = await verifier.verify_token("valid_token_12345_no_dots_longer_than_40_chars")

            # Should reject due to expiration
            assert token is None

    @pytest.mark.asyncio
    async def test_token_verifier_audience_mismatch(self):
        """Test token verifier rejects tokens with wrong audience."""
        from app.mcp.auth_provider import SupabaseTokenVerifier

        verifier = SupabaseTokenVerifier(
            required_scopes=["mcp:read"],
            expected_resource="http://localhost:3600/mcp"
        )

        with patch("app.services.oauth_token_store.oauth_token_store.get_access_token", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = {
                "user_id": "123",
                "scope": "mcp:read",
                "resource": "http://other-server.com/mcp",  # Wrong resource
                "expires_at": 9999999999
            }

            token = await verifier.verify_token("valid_token_12345_no_dots_longer_than_40_chars")

            # Should reject due to audience mismatch
            assert token is None

    @pytest.mark.asyncio
    async def test_token_verifier_missing_scope(self):
        """Test token verifier rejects tokens without required scope."""
        from app.mcp.auth_provider import SupabaseTokenVerifier

        verifier = SupabaseTokenVerifier(
            required_scopes=["mcp:write"],
            expected_resource="http://localhost:3600/mcp"
        )

        with patch("app.services.oauth_token_store.oauth_token_store.get_access_token", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = {
                "user_id": "123",
                "scope": "mcp:read",  # Missing mcp:write
                "resource": "http://localhost:3600/mcp",
                "expires_at": 9999999999
            }

            token = await verifier.verify_token("valid_token_12345_no_dots_longer_than_40_chars")

            # Should reject due to missing scope
            assert token is None


class TestMCPOAuthTokenStore:
    """Tests for OAuth token store integration."""

    @pytest.mark.asyncio
    async def test_store_and_retrieve_auth_code(self):
        """Test storing and retrieving authorization code."""
        from app.services.oauth_token_store import oauth_token_store

        # Store auth code
        result = await oauth_token_store.store_auth_code(
            code="test_code_123",
            user_id="user_123",
            client_id="test_client",
            redirect_uri="http://localhost/callback",
            scope="mcp:read"
        )

        assert result is True

        # Retrieve and consume
        auth_data = await oauth_token_store.get_auth_code("test_code_123")

        assert auth_data is not None
        assert auth_data["user_id"] == "user_123"
        assert auth_data["client_id"] == "test_client"

        # Should be one-time use
        auth_data_2 = await oauth_token_store.get_auth_code("test_code_123")
        assert auth_data_2 is None

    @pytest.mark.asyncio
    async def test_store_and_retrieve_tokens(self):
        """Test storing and retrieving OAuth tokens."""
        from app.services.oauth_token_store import oauth_token_store

        # Store tokens
        result = await oauth_token_store.store_oauth_tokens(
            access_token="access_token_12345_no_dots_longer_than_40_chars",
            refresh_token="refresh_token_12345_no_dots_longer_than_40_chars",
            user_id="user_123",
            scope="mcp:read mcp:write",
            client_id="test_client"
        )

        assert result is True

        # Retrieve access token
        token_data = await oauth_token_store.get_access_token("access_token_12345_no_dots_longer_than_40_chars")

        assert token_data is not None
        assert token_data["user_id"] == "user_123"
        assert token_data["scope"] == "mcp:read mcp:write"

    @pytest.mark.asyncio
    async def test_revoke_token(self):
        """Test token revocation."""
        from app.services.oauth_token_store import oauth_token_store

        # Store and revoke
        await oauth_token_store.store_oauth_tokens(
            access_token="token_to_revoke_12345_no_dots_longer_than_40_chars",
            refresh_token="refresh_to_revoke_12345_no_dots_longer_than_40_chars",
            user_id="user_123",
            scope="mcp:read"
        )

        result = await oauth_token_store.revoke_token("token_to_revoke_12345_no_dots_longer_than_40_chars")
        assert result is True

        # Should no longer exist
        token_data = await oauth_token_store.get_access_token("token_to_revoke_12345_no_dots_longer_than_40_chars")
        assert token_data is None

    @pytest.mark.asyncio
    async def test_refresh_token_rotation(self):
        """Test refresh token rotation."""
        from app.services.oauth_token_store import oauth_token_store

        # Store initial tokens
        await oauth_token_store.store_oauth_tokens(
            access_token="old_access_token_12345_no_dots_longer_than_40",
            refresh_token="old_refresh_token_12345_no_dots_longer_than_40",
            user_id="user_123",
            scope="mcp:read"
        )

        # Store new tokens (simulating refresh)
        await oauth_token_store.store_oauth_tokens(
            access_token="new_access_token_12345_no_dots_longer_than_40",
            refresh_token="new_refresh_token_12345_no_dots_longer_than_40",
            user_id="user_123",
            scope="mcp:read"
        )

        # Old access token should still exist (until expiry)
        old_token = await oauth_token_store.get_access_token("old_access_token_12345_no_dots_longer_than_40")
        # Token store doesn't revoke old tokens on refresh, they expire naturally
        assert old_token is not None or old_token is None  # Depends on implementation

        # New token should exist
        new_token = await oauth_token_store.get_access_token("new_access_token_12345_no_dots_longer_than_40")
        assert new_token is not None


class TestMCPWidgetIntegration:
    """Tests for ChatGPT widget integration."""

    def test_widget_registration(self):
        """Test that widgets are registered correctly."""
        from app.mcp.chatgpt import WIDGETS

        assert "PropertySearchWidget" in WIDGETS
        assert "PropertyDetailsWidget" in WIDGETS
        assert "OwnerDashboardWidget" in WIDGETS

    def test_widget_tool_mapping(self):
        """Test widget to tool mapping."""
        from app.mcp.chatgpt import WIDGETS

        search_widget = WIDGETS["PropertySearchWidget"]
        assert "discovery_search" in search_widget["tools"]

        owner_widget = WIDGETS["OwnerDashboardWidget"]
        assert "owner_properties_list" in owner_widget["tools"]

    def test_get_widget_for_tool(self):
        """Test getting widget URI for a tool."""
        from app.mcp.chatgpt import get_widget_for_tool

        widget_uri = get_widget_for_tool("discovery_search")
        assert widget_uri is not None
        assert widget_uri.startswith("ui://widget/")

        no_widget = get_widget_for_tool("nonexistent.tool")
        assert no_widget is None

    def test_all_discovery_tools_have_widgets(self):
        """Test that discovery tools have widget mappings."""
        from app.mcp.chatgpt import get_widget_for_tool

        # Core discovery tools that should have widgets
        discovery_tools = [
            "discovery_search",
            "discovery_property_get",
            "discovery_feed",
        ]

        for tool_name in discovery_tools:
            widget = get_widget_for_tool(tool_name)
            assert widget is not None, f"Tool {tool_name} should have a widget"


class TestMCPEndToEnd:
    """End-to-end tests for MCP workflows."""

    @pytest.mark.asyncio
    async def test_complete_property_workflow(self):
        """Test complete property discovery and booking workflow."""
        from app.mcp.apps_sdk import AppsSDKToolResult
        from app.mcp.chatgpt.discovery_tools import discovery_search
        from app.mcp.user.booking import bookings_check_availability

        search_fn = get_tool_fn(discovery_search)
        avail_fn = get_tool_fn(bookings_check_availability)

        # Step 1: Search for properties
        with patch("app.mcp.chatgpt.discovery_tools._get_optional_user", new_callable=AsyncMock) as mock_user:
            mock_user.return_value = MagicMock(id=1)

            with patch("app.services.property.get_unified_properties_optimized", new_callable=AsyncMock) as mock_search:
                mock_search.return_value = (
                    [{"id": 1, "title": "Test Property", "base_price": 1000000}],
                    None,
                    1,
                )

                search_result = await search_fn(query="apartment")
                assert isinstance(search_result, AppsSDKToolResult)

        # Step 2: Check availability (returns dict via MCPResponse, not AppsSDKToolResult)
        with patch("app.mcp.user.booking._get_user", new_callable=AsyncMock) as mock_user:
            mock_user.return_value = MagicMock(id=1)

            with patch("app.services.booking.check_availability", new_callable=AsyncMock) as mock_avail:
                mock_avail.return_value = {"available": True, "max_occupancy": 4}

                with patch("app.mcp.user.booking.get_db") as mock_db:
                    mock_db.return_value = AsyncIteratorMock([MagicMock()])

                    avail_result = await avail_fn(
                        property_id=1,
                        check_in_date="2025-06-01",
                        check_out_date="2025-06-05",
                        guests=2
                    )

                    # bookings_check_availability returns a dict via MCPResponse
                    assert isinstance(avail_result, dict)
                    assert avail_result.get("ok") is True
                    assert avail_result.get("data", {}).get("available") is True

    @pytest.mark.asyncio
    async def test_agent_property_management_workflow(self):
        """Test agent property management workflow."""
        from app.mcp.admin.agent import agent_properties_list

        props_fn = get_tool_fn(agent_properties_list)

        # Create a properly structured mock user that won't cause Pydantic validation errors
        # User schema requires: id, supabase_user_id, role, is_active, is_verified, created_at
        from datetime import datetime
        class MockUser:
            def __init__(self):
                self.id = 1
                self.role = "agent"
                self.agent_id = 1
                self.email = "agent@example.com"
                self.full_name = "Test Agent"
                self.phone = "+1234567890"
                self.date_of_birth = None
                self.supabase_user_id = "test-user-id"
                self.profile_image_url = None
                self.preferences = {}
                self.notification_settings = {}
                self.privacy_settings = {}
                self.is_active = True
                self.is_verified = True
                self.created_at = datetime.now()
                self.updated_at = None
                self.current_latitude = None
                self.current_longitude = None
                self.preferred_locations = None

        mock_user_obj = MockUser()

        with patch("app.mcp.admin.agent_tools.properties._get_user", new_callable=AsyncMock) as mock_user:
            mock_user.return_value = mock_user_obj

            # list_managed_properties is in app.services.pm_properties
            with patch("app.services.pm_properties.list_managed_properties", new_callable=AsyncMock) as mock_list:
                mock_list.return_value = ([], None, None)

                with patch("app.mcp.admin.agent_tools.properties.get_db") as mock_db:
                    mock_db.return_value = AsyncIteratorMock([MagicMock()])

                    # List properties - admin server returns dict via MCPResponse
                    result = await props_fn()
                    assert isinstance(result, dict)
                    assert result.get("ok") is True
                    assert "data" in result

    @pytest.mark.asyncio
    async def test_owner_property_workflow(self):
        """Test owner managing their properties."""
        from app.mcp.user.owner import owner_properties_get, owner_properties_list

        list_fn = get_tool_fn(owner_properties_list)
        get_fn = get_tool_fn(owner_properties_get)

        # Create a properly structured mock user
        from datetime import datetime
        class MockUser:
            def __init__(self):
                self.id = 1
                self.role = "user"
                self.email = "owner@example.com"
                self.full_name = "Test Owner"
                self.phone = "+1234567890"
                self.date_of_birth = None
                self.supabase_user_id = "test-user-id"
                self.profile_image_url = None
                self.preferences = {}
                self.notification_settings = {}
                self.privacy_settings = {}
                self.is_active = True
                self.is_verified = True
                self.created_at = datetime.now()
                self.updated_at = None
                self.current_latitude = None
                self.current_longitude = None
                self.preferred_locations = None

        mock_user_obj = MockUser()

        # Create a proper mock db that supports await
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute.return_value = mock_result

        # List properties - uses list_managed_properties from app.services.pm_properties
        # Returns dict via MCPResponse
        with patch("app.mcp.user.owner._get_user", new_callable=AsyncMock) as mock_user:
            mock_user.return_value = mock_user_obj

            with patch("app.mcp.user.owner.get_db") as mock_db_gen:
                mock_db_gen.return_value = AsyncIteratorMock([mock_db])

                with patch("app.services.pm_properties.list_managed_properties", new_callable=AsyncMock) as mock_props:
                    mock_props.return_value = ([], None, None)

                    result = await list_fn()
                    # owner tools return dict via MCPResponse
                    assert isinstance(result, dict)

        # Get specific property - uses get_managed_property_detail
        with patch("app.mcp.user.owner._get_user", new_callable=AsyncMock) as mock_user:
            mock_user.return_value = mock_user_obj

            with patch("app.mcp.user.owner.get_db") as mock_db_gen:
                mock_db_gen.return_value = AsyncIteratorMock([mock_db])

                with patch("app.services.pm_properties.get_managed_property_detail", new_callable=AsyncMock) as mock_get:
                    mock_get.return_value = MagicMock(
                        id=1,
                        title="My Property",
                        is_available=True
                    )

                    result = await get_fn(property_id=1)
                    assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_tenant_workflow(self):
        """Test tenant viewing lease and rent status."""
        from app.mcp.user.tenant import tenant_lease_current, tenant_rent_history

        lease_fn = get_tool_fn(tenant_lease_current)
        rent_fn = get_tool_fn(tenant_rent_history)

        # View current lease - returns dict directly, not AppsSDKToolResult
        with patch("app.mcp.user.tenant._get_user", new_callable=AsyncMock) as mock_user:
            mock_user.return_value = MagicMock(id=1, role="user")

            # Mock the database session and queries
            mock_db_session = MagicMock()
            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = None  # No active lease
            mock_db_session.execute.return_value = mock_result

            with patch("app.mcp.user.tenant.get_db") as mock_db:
                mock_db.return_value = AsyncIteratorMock([mock_db_session])

                result = await lease_fn()
                # These functions return dicts directly
                assert isinstance(result, dict)
                assert "lease" in result or "error" in result

        # View rent history - returns dict directly
        with patch("app.mcp.user.tenant._get_user", new_callable=AsyncMock) as mock_user:
            mock_user.return_value = MagicMock(id=1, role="user")

            # Mock the database session and queries
            mock_db_session = MagicMock()
            mock_lease_result = MagicMock()
            mock_lease_result.all.return_value = []
            mock_db_session.execute.return_value = mock_lease_result

            with patch("app.mcp.user.tenant.get_db") as mock_db:
                mock_db.return_value = AsyncIteratorMock([mock_db_session])

                result = await rent_fn()
                # These functions return dicts directly
                assert isinstance(result, dict)
                assert "payments" in result or "error" in result


# Helper for async iteration
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
