"""
Unit tests for MCP User tools (owner, booking, tenant, system).

These tests exercise the tool functions directly, mocking the
database session, user resolution, and tool_ops functions to verify
that each tool:
- Delegates to the correct tool_ops function
- Passes the correct arguments
- Returns responses in the MCPResponse shape
- Handles auth, not-found, and validation errors correctly
"""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.mcp.apps_sdk import AuthRequiredError
from app.mcp.errors import MCPErrorCode

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _async_gen(db):
    """Async generator that yields db, mimicking get_db()."""
    yield db


def _auth_error(**kwargs):
    """Raise AuthRequiredError with correct signature.

    _require_auth() is called with keyword arguments (action, message, scope),
    so the side_effect must accept those kwargs.
    """
    raise AuthRequiredError(
        message=kwargs.get("message", "Authentication required"),
        www_authenticate="Bearer error=\"insufficient_scope\"",
    )


def _make_user(
    user_id: int = 10,
    role: str = "user",
    full_name: str = "Owner User",
):
    now = datetime.now(timezone.utc)
    return SimpleNamespace(
        id=user_id,
        role=role,
        supabase_user_id=f"user-{user_id}",
        phone="+919876543210",
        full_name=full_name,
        email=f"user{user_id}@example.com",
        is_active=True,
        is_verified=True,
        agent_id=None,
        created_at=now,
        updated_at=now,
    )


# ===========================================================================
# Owner Tools
# ===========================================================================


class TestOwnerPropertiesList:
    """Tests for owner_properties_list MCP tool."""

    @pytest.mark.asyncio
    async def test_returns_properties(self):
        db = AsyncMock()
        user = _make_user()
        expected_result = {
            "items": [{"id": 1, "title": "Flat"}],
            "total": 1,
            "page": 1,
            "limit": 20,
            "stats": {"total_properties": 1, "occupied": 0, "vacant": 1},
        }

        with (
            patch("app.mcp.user.owner.get_db", return_value=_async_gen(db)),
            patch("app.mcp.user.owner._get_user", new=AsyncMock(return_value=user)),
            patch("app.mcp.user.owner.list_properties_enriched", new=AsyncMock(return_value=expected_result)),
        ):
            from app.mcp.user.owner import owner_properties_list

            result = await owner_properties_list(page=1, limit=20)

        # owner_properties_list returns the tool_ops result directly
        assert result["total"] == 1
        assert result["items"][0]["id"] == 1

    @pytest.mark.asyncio
    async def test_raises_auth_required_when_no_user(self):
        db = AsyncMock()

        with (
            patch("app.mcp.user.owner.get_db", return_value=_async_gen(db)),
            patch("app.mcp.user.owner._get_user", new=AsyncMock(return_value=None)),
            patch("app.mcp.user.owner.raise_auth_required", side_effect=_auth_error),
        ):
            from app.mcp.user.owner import owner_properties_list

            with pytest.raises(AuthRequiredError):
                await owner_properties_list()

    @pytest.mark.asyncio
    async def test_delegates_to_list_properties_enriched(self):
        db = AsyncMock()
        user = _make_user()
        mock_fn = AsyncMock(return_value={"items": [], "total": 0})

        with (
            patch("app.mcp.user.owner.get_db", return_value=_async_gen(db)),
            patch("app.mcp.user.owner._get_user", new=AsyncMock(return_value=user)),
            patch("app.mcp.user.owner.list_properties_enriched", new=mock_fn),
        ):
            from app.mcp.user.owner import owner_properties_list

            await owner_properties_list(page=2, limit=10, occupancy="vacant", q="DLF")

        mock_fn.assert_awaited_once()
        assert mock_fn.call_args.kwargs["page"] == 2
        assert mock_fn.call_args.kwargs["limit"] == 10
        assert mock_fn.call_args.kwargs["occupancy"] == "vacant"
        assert mock_fn.call_args.kwargs["q"] == "DLF"
        assert mock_fn.call_args.kwargs["owner_id"] == user.id


class TestOwnerPropertiesCreate:
    """Tests for owner_properties_create MCP tool."""

    @pytest.mark.asyncio
    async def test_raises_auth_required_when_no_user(self):
        db = AsyncMock()

        with (
            patch("app.mcp.user.owner.get_db", return_value=_async_gen(db)),
            patch("app.mcp.user.owner._get_user", new=AsyncMock(return_value=None)),
            patch("app.mcp.user.owner._require_auth", side_effect=_auth_error),
        ):
            from app.mcp.user.owner import owner_properties_create

            with pytest.raises(AuthRequiredError):
                await owner_properties_create(
                    title="Test",
                    property_type="apartment",
                    purpose="rent",
                    full_address="123 Test",
                    city="Gurugram",
                    locality="DLF",
                    latitude=28.45,
                    longitude=77.02,
                    base_price=15000,
                )

    @pytest.mark.asyncio
    async def test_delegates_to_create_property(self):
        db = AsyncMock()
        user = _make_user()
        mock_fn = AsyncMock(return_value={"id": 1, "title": "My Flat"})

        with (
            patch("app.mcp.user.owner.get_db", return_value=_async_gen(db)),
            patch("app.mcp.user.owner._get_user", new=AsyncMock(return_value=user)),
            patch("app.mcp.user.owner.create_property", new=mock_fn),
        ):
            from app.mcp.user.owner import owner_properties_create

            result = await owner_properties_create(
                title="My Flat",
                property_type="apartment",
                purpose="rent",
                full_address="123 Test Street",
                city="Gurugram",
                locality="DLF Phase 1",
                latitude=28.45,
                longitude=77.02,
                base_price=15000,
            )

        assert result["ok"] is True
        mock_fn.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_invalid_input_from_tool_ops(self):
        db = AsyncMock()
        user = _make_user()
        mock_fn = AsyncMock(return_value={"error": True, "message": "Invalid property_type"})

        with (
            patch("app.mcp.user.owner.get_db", return_value=_async_gen(db)),
            patch("app.mcp.user.owner._get_user", new=AsyncMock(return_value=user)),
            patch("app.mcp.user.owner.create_property", new=mock_fn),
        ):
            from app.mcp.user.owner import owner_properties_create

            result = await owner_properties_create(
                title="Test",
                property_type="spaceship",
                purpose="rent",
                full_address="123 Test",
                city="Gurugram",
                locality="DLF",
                latitude=28.45,
                longitude=77.02,
                base_price=15000,
            )

        assert result["ok"] is False
        assert result["error"]["code"] == MCPErrorCode.INVALID_INPUT.value


class TestOwnerPropertiesGet:
    """Tests for owner_properties_get MCP tool."""

    @pytest.mark.asyncio
    async def test_raises_auth_required_when_no_user(self):
        db = AsyncMock()

        with (
            patch("app.mcp.user.owner.get_db", return_value=_async_gen(db)),
            patch("app.mcp.user.owner._get_user", new=AsyncMock(return_value=None)),
            patch("app.mcp.user.owner._require_auth", side_effect=_auth_error),
        ):
            from app.mcp.user.owner import owner_properties_get

            with pytest.raises(AuthRequiredError):
                await owner_properties_get(property_id=1)

    @pytest.mark.asyncio
    async def test_returns_property_detail(self):
        db = AsyncMock()
        user = _make_user()
        mock_fn = AsyncMock(return_value={"property": {"id": 1, "title": "Flat"}})

        with (
            patch("app.mcp.user.owner.get_db", return_value=_async_gen(db)),
            patch("app.mcp.user.owner._get_user", new=AsyncMock(return_value=user)),
            patch("app.mcp.user.owner.get_property_detail", new=mock_fn),
        ):
            from app.mcp.user.owner import owner_properties_get

            result = await owner_properties_get(property_id=1)

        assert result["ok"] is True
        assert result["data"]["property"]["id"] == 1

    @pytest.mark.asyncio
    async def test_not_found_returns_error(self):
        db = AsyncMock()
        user = _make_user()
        mock_fn = AsyncMock(return_value={"error": True, "message": "Property not found"})

        with (
            patch("app.mcp.user.owner.get_db", return_value=_async_gen(db)),
            patch("app.mcp.user.owner._get_user", new=AsyncMock(return_value=user)),
            patch("app.mcp.user.owner.get_property_detail", new=mock_fn),
        ):
            from app.mcp.user.owner import owner_properties_get

            result = await owner_properties_get(property_id=999)

        assert result["ok"] is False
        assert result["error"]["code"] == MCPErrorCode.NOT_FOUND.value


class TestOwnerPropertiesUpdate:
    """Tests for owner_properties_update MCP tool."""

    @pytest.mark.asyncio
    async def test_raises_auth_required_when_no_user(self):
        db = AsyncMock()

        with (
            patch("app.mcp.user.owner.get_db", return_value=_async_gen(db)),
            patch("app.mcp.user.owner._get_user", new=AsyncMock(return_value=None)),
            patch("app.mcp.user.owner._require_auth", side_effect=_auth_error),
        ):
            from app.mcp.user.owner import owner_properties_update

            with pytest.raises(AuthRequiredError):
                await owner_properties_update(property_id=1, title="New Title")

    @pytest.mark.asyncio
    async def test_not_found_returns_error(self):
        from app.core.exceptions import PropertyNotFoundException

        db = AsyncMock()
        user = _make_user()
        mock_fn = AsyncMock(side_effect=PropertyNotFoundException())

        with (
            patch("app.mcp.user.owner.get_db", return_value=_async_gen(db)),
            patch("app.mcp.user.owner._get_user", new=AsyncMock(return_value=user)),
            patch("app.mcp.user.owner.update_property_fields", new=mock_fn),
        ):
            from app.mcp.user.owner import owner_properties_update

            result = await owner_properties_update(property_id=999, title="New Title")

        assert result["ok"] is False
        assert result["error"]["code"] == MCPErrorCode.NOT_FOUND.value

    @pytest.mark.asyncio
    async def test_insufficient_permissions(self):
        from app.core.exceptions import InsufficientPermissionsError

        db = AsyncMock()
        user = _make_user()
        mock_fn = AsyncMock(side_effect=InsufficientPermissionsError())

        with (
            patch("app.mcp.user.owner.get_db", return_value=_async_gen(db)),
            patch("app.mcp.user.owner._get_user", new=AsyncMock(return_value=user)),
            patch("app.mcp.user.owner.update_property_fields", new=mock_fn),
        ):
            from app.mcp.user.owner import owner_properties_update

            result = await owner_properties_update(property_id=1, title="New Title")

        assert result["ok"] is False
        assert result["error"]["code"] == MCPErrorCode.INSUFFICIENT_PERMISSIONS.value

    @pytest.mark.asyncio
    async def test_successful_update(self):
        db = AsyncMock()
        user = _make_user()
        mock_fn = AsyncMock(return_value={"id": 1, "title": "Updated Title"})

        with (
            patch("app.mcp.user.owner.get_db", return_value=_async_gen(db)),
            patch("app.mcp.user.owner._get_user", new=AsyncMock(return_value=user)),
            patch("app.mcp.user.owner.update_property_fields", new=mock_fn),
        ):
            from app.mcp.user.owner import owner_properties_update

            result = await owner_properties_update(property_id=1, title="Updated Title")

        assert result["ok"] is True
        assert result["data"]["id"] == 1


class TestOwnerPropertiesToggleAvailability:
    """Tests for owner_properties_toggle_availability MCP tool."""

    @pytest.mark.asyncio
    async def test_raises_auth_required_when_no_user(self):
        db = AsyncMock()

        with (
            patch("app.mcp.user.owner.get_db", return_value=_async_gen(db)),
            patch("app.mcp.user.owner._get_user", new=AsyncMock(return_value=None)),
            patch("app.mcp.user.owner._require_auth", side_effect=_auth_error),
        ):
            from app.mcp.user.owner import owner_properties_toggle_availability

            with pytest.raises(AuthRequiredError):
                await owner_properties_toggle_availability(property_id=1, is_available=True)

    @pytest.mark.asyncio
    async def test_not_found_returns_error(self):
        from app.core.exceptions import PropertyNotFoundException

        db = AsyncMock()
        user = _make_user()
        mock_fn = AsyncMock(side_effect=PropertyNotFoundException())

        with (
            patch("app.mcp.user.owner.get_db", return_value=_async_gen(db)),
            patch("app.mcp.user.owner._get_user", new=AsyncMock(return_value=user)),
            patch("app.mcp.user.owner.toggle_property_availability", new=mock_fn),
        ):
            from app.mcp.user.owner import owner_properties_toggle_availability

            result = await owner_properties_toggle_availability(property_id=999, is_available=True)

        assert result["ok"] is False
        assert result["error"]["code"] == MCPErrorCode.NOT_FOUND.value

    @pytest.mark.asyncio
    async def test_successful_toggle(self):
        db = AsyncMock()
        user = _make_user()
        mock_fn = AsyncMock(return_value={"property_id": 1, "is_available": True})

        with (
            patch("app.mcp.user.owner.get_db", return_value=_async_gen(db)),
            patch("app.mcp.user.owner._get_user", new=AsyncMock(return_value=user)),
            patch("app.mcp.user.owner.toggle_property_availability", new=mock_fn),
        ):
            from app.mcp.user.owner import owner_properties_toggle_availability

            result = await owner_properties_toggle_availability(property_id=1, is_available=True)

        assert result["ok"] is True
        assert result["data"]["is_available"] is True


# ===========================================================================
# Booking Tools
# ===========================================================================


class TestBookingsCreate:
    """Tests for bookings_create MCP tool."""

    @pytest.mark.asyncio
    async def test_raises_auth_required_when_no_user(self):
        db = AsyncMock()

        with (
            patch("app.mcp.user.booking.get_db", return_value=_async_gen(db)),
            patch("app.mcp.user.booking._get_user", new=AsyncMock(return_value=None)),
            patch("app.mcp.user.booking._require_auth", side_effect=_auth_error),
        ):
            from app.mcp.user.booking import bookings_create

            with pytest.raises(AuthRequiredError):
                await bookings_create(
                    property_id=1,
                    check_in_date="2026-06-01",
                    check_out_date="2026-06-05",
                )

    @pytest.mark.asyncio
    async def test_unavailable_property_returns_conflict(self):
        db = AsyncMock()
        user = _make_user()
        mock_fn = AsyncMock(return_value={"error": True, "message": "Already booked"})

        with (
            patch("app.mcp.user.booking.get_db", return_value=_async_gen(db)),
            patch("app.mcp.user.booking._get_user", new=AsyncMock(return_value=user)),
            patch("app.mcp.user.booking.create_booking", new=mock_fn),
        ):
            from app.mcp.user.booking import bookings_create

            result = await bookings_create(
                property_id=1,
                check_in_date="2026-06-01",
                check_out_date="2026-06-05",
            )

        assert result["ok"] is False
        assert result["error"]["code"] == MCPErrorCode.BOOKING_CONFLICT.value

    @pytest.mark.asyncio
    async def test_successful_booking_creation(self):
        db = AsyncMock()
        user = _make_user()
        mock_fn = AsyncMock(return_value={"id": 1, "message": "Booking created successfully"})

        with (
            patch("app.mcp.user.booking.get_db", return_value=_async_gen(db)),
            patch("app.mcp.user.booking._get_user", new=AsyncMock(return_value=user)),
            patch("app.mcp.user.booking.create_booking", new=mock_fn),
        ):
            from app.mcp.user.booking import bookings_create

            result = await bookings_create(
                property_id=1,
                check_in_date="2026-06-01",
                check_out_date="2026-06-05",
                guests=2,
            )

        assert result["ok"] is True
        assert result["data"]["id"] == 1


class TestBookingsList:
    """Tests for bookings_list MCP tool."""

    @pytest.mark.asyncio
    async def test_raises_auth_required_when_no_user(self):
        db = AsyncMock()

        with (
            patch("app.mcp.user.booking.get_db", return_value=_async_gen(db)),
            patch("app.mcp.user.booking._get_user", new=AsyncMock(return_value=None)),
            patch("app.mcp.user.booking._require_auth", side_effect=_auth_error),
        ):
            from app.mcp.user.booking import bookings_list

            with pytest.raises(AuthRequiredError):
                await bookings_list()

    @pytest.mark.asyncio
    async def test_returns_paginated_bookings(self):
        db = AsyncMock()
        user = _make_user()
        mock_fn = AsyncMock(return_value={
            "bookings": [{"id": 1}],
            "total": 1,
            "page": 1,
            "limit": 20,
        })

        with (
            patch("app.mcp.user.booking.get_db", return_value=_async_gen(db)),
            patch("app.mcp.user.booking._get_user", new=AsyncMock(return_value=user)),
            patch("app.mcp.user.booking.list_user_bookings", new=mock_fn),
        ):
            from app.mcp.user.booking import bookings_list

            result = await bookings_list(page=1, limit=20)

        assert result["ok"] is True
        assert result["data"]["total"] == 1


class TestBookingsGet:
    """Tests for bookings_get MCP tool."""

    @pytest.mark.asyncio
    async def test_raises_auth_required_when_no_user(self):
        db = AsyncMock()

        with (
            patch("app.mcp.user.booking.get_db", return_value=_async_gen(db)),
            patch("app.mcp.user.booking._get_user", new=AsyncMock(return_value=None)),
            patch("app.mcp.user.booking._require_auth", side_effect=_auth_error),
        ):
            from app.mcp.user.booking import bookings_get

            with pytest.raises(AuthRequiredError):
                await bookings_get(booking_id=1)

    @pytest.mark.asyncio
    async def test_booking_not_found(self):
        db = AsyncMock()
        user = _make_user()
        mock_fn = AsyncMock(return_value={"error": True, "message": "Booking not found"})

        with (
            patch("app.mcp.user.booking.get_db", return_value=_async_gen(db)),
            patch("app.mcp.user.booking._get_user", new=AsyncMock(return_value=user)),
            patch("app.mcp.user.booking.get_booking_detail", new=mock_fn),
        ):
            from app.mcp.user.booking import bookings_get

            result = await bookings_get(booking_id=999)

        assert result["ok"] is False
        assert result["error"]["code"] == MCPErrorCode.NOT_FOUND.value

    @pytest.mark.asyncio
    async def test_insufficient_permissions(self):
        db = AsyncMock()
        user = _make_user()
        mock_fn = AsyncMock(return_value={"error": True, "message": "You can only view your own bookings"})

        with (
            patch("app.mcp.user.booking.get_db", return_value=_async_gen(db)),
            patch("app.mcp.user.booking._get_user", new=AsyncMock(return_value=user)),
            patch("app.mcp.user.booking.get_booking_detail", new=mock_fn),
        ):
            from app.mcp.user.booking import bookings_get

            result = await bookings_get(booking_id=1)

        assert result["ok"] is False
        assert result["error"]["code"] == MCPErrorCode.INSUFFICIENT_PERMISSIONS.value


class TestBookingsCancel:
    """Tests for bookings_cancel MCP tool."""

    @pytest.mark.asyncio
    async def test_raises_auth_required_when_no_user(self):
        db = AsyncMock()

        with (
            patch("app.mcp.user.booking.get_db", return_value=_async_gen(db)),
            patch("app.mcp.user.booking._get_user", new=AsyncMock(return_value=None)),
            patch("app.mcp.user.booking._require_auth", side_effect=_auth_error),
        ):
            from app.mcp.user.booking import bookings_cancel

            with pytest.raises(AuthRequiredError):
                await bookings_cancel(booking_id=1, reason="Change of plans")

    @pytest.mark.asyncio
    async def test_booking_not_found(self):
        db = AsyncMock()
        user = _make_user()
        mock_fn = AsyncMock(return_value={"error": True, "message": "Booking not found"})

        with (
            patch("app.mcp.user.booking.get_db", return_value=_async_gen(db)),
            patch("app.mcp.user.booking._get_user", new=AsyncMock(return_value=user)),
            patch("app.mcp.user.booking.cancel_booking", new=mock_fn),
        ):
            from app.mcp.user.booking import bookings_cancel

            result = await bookings_cancel(booking_id=999, reason="N/A")

        assert result["ok"] is False
        assert result["error"]["code"] == MCPErrorCode.NOT_FOUND.value

    @pytest.mark.asyncio
    async def test_cannot_cancel_already_cancelled_booking(self):
        db = AsyncMock()
        user = _make_user()
        # The tool checks for "cannot cancel" in lowercase message
        mock_fn = AsyncMock(return_value={"error": True, "message": "Cannot cancel booking in current status"})

        with (
            patch("app.mcp.user.booking.get_db", return_value=_async_gen(db)),
            patch("app.mcp.user.booking._get_user", new=AsyncMock(return_value=user)),
            patch("app.mcp.user.booking.cancel_booking", new=mock_fn),
        ):
            from app.mcp.user.booking import bookings_cancel

            result = await bookings_cancel(booking_id=1, reason="N/A")

        assert result["ok"] is False
        assert result["error"]["code"] == MCPErrorCode.OPERATION_FAILED.value

    @pytest.mark.asyncio
    async def test_successful_cancellation(self):
        db = AsyncMock()
        user = _make_user()
        mock_fn = AsyncMock(return_value={"booking_id": 1, "message": "Booking cancelled successfully"})

        with (
            patch("app.mcp.user.booking.get_db", return_value=_async_gen(db)),
            patch("app.mcp.user.booking._get_user", new=AsyncMock(return_value=user)),
            patch("app.mcp.user.booking.cancel_booking", new=mock_fn),
        ):
            from app.mcp.user.booking import bookings_cancel

            result = await bookings_cancel(booking_id=1, reason="Change of plans")

        assert result["ok"] is True
        assert result["data"]["booking_id"] == 1


class TestBookingsCheckAvailability:
    """Tests for bookings_check_availability MCP tool."""

    @pytest.mark.asyncio
    async def test_returns_availability_result(self):
        db = AsyncMock()
        mock_fn = AsyncMock(return_value={"available": True, "max_occupancy": 4})

        with (
            patch("app.mcp.user.booking.get_db", return_value=_async_gen(db)),
            patch("app.mcp.user.booking.check_availability", new=mock_fn),
        ):
            from app.mcp.user.booking import bookings_check_availability

            result = await bookings_check_availability(
                property_id=1,
                check_in_date="2026-06-01",
                check_out_date="2026-06-05",
                guests=2,
            )

        assert result["ok"] is True
        assert result["data"]["available"] is True


class TestBookingsGetPricing:
    """Tests for bookings_get_pricing MCP tool."""

    @pytest.mark.asyncio
    async def test_returns_pricing(self):
        db = AsyncMock()
        mock_fn = AsyncMock(return_value={"base": 8000, "taxes": 800, "total": 9000})

        with (
            patch("app.mcp.user.booking.get_db", return_value=_async_gen(db)),
            patch("app.mcp.user.booking.get_pricing", new=mock_fn),
        ):
            from app.mcp.user.booking import bookings_get_pricing

            result = await bookings_get_pricing(
                property_id=1,
                check_in_date="2026-06-01",
                check_out_date="2026-06-05",
            )

        assert result["ok"] is True
        assert "base" in result["data"]

    @pytest.mark.asyncio
    async def test_pricing_error_response(self):
        db = AsyncMock()
        mock_fn = AsyncMock(return_value={"error": True, "message": "Property not available for short stay"})

        with (
            patch("app.mcp.user.booking.get_db", return_value=_async_gen(db)),
            patch("app.mcp.user.booking.get_pricing", new=mock_fn),
        ):
            from app.mcp.user.booking import bookings_get_pricing

            result = await bookings_get_pricing(
                property_id=1,
                check_in_date="2026-06-01",
                check_out_date="2026-06-05",
            )

        assert result["ok"] is False
        assert result["error"]["code"] == MCPErrorCode.INVALID_INPUT.value


# ===========================================================================
# Tenant Tools
# ===========================================================================


class TestTenantLeaseCurrent:
    """Tests for tenant_lease_current MCP tool."""

    @pytest.mark.asyncio
    async def test_raises_auth_required_when_no_user(self):
        db = AsyncMock()

        with (
            patch("app.mcp.user.tenant.get_db", return_value=_async_gen(db)),
            patch("app.mcp.user.tenant._get_user", new=AsyncMock(return_value=None)),
            patch("app.mcp.user.tenant._require_auth", side_effect=_auth_error),
        ):
            from app.mcp.user.tenant import tenant_lease_current

            with pytest.raises(AuthRequiredError):
                await tenant_lease_current()

    @pytest.mark.asyncio
    async def test_no_active_lease(self):
        db = AsyncMock()
        user = _make_user()
        mock_fn = AsyncMock(return_value={"lease": None, "message": "No active lease found."})

        with (
            patch("app.mcp.user.tenant.get_db", return_value=_async_gen(db)),
            patch("app.mcp.user.tenant._get_user", new=AsyncMock(return_value=user)),
            patch("app.mcp.user.tenant.get_tenant_current_lease", new=mock_fn),
        ):
            from app.mcp.user.tenant import tenant_lease_current

            result = await tenant_lease_current()

        assert result["ok"] is True
        assert result["data"]["lease"] is None


class TestTenantRentHistory:
    """Tests for tenant_rent_history MCP tool."""

    @pytest.mark.asyncio
    async def test_raises_auth_required_when_no_user(self):
        db = AsyncMock()

        with (
            patch("app.mcp.user.tenant.get_db", return_value=_async_gen(db)),
            patch("app.mcp.user.tenant._get_user", new=AsyncMock(return_value=None)),
            patch("app.mcp.user.tenant._require_auth", side_effect=_auth_error),
        ):
            from app.mcp.user.tenant import tenant_rent_history

            with pytest.raises(AuthRequiredError):
                await tenant_rent_history()

    @pytest.mark.asyncio
    async def test_no_leases_returns_empty(self):
        db = AsyncMock()
        user = _make_user()
        mock_fn = AsyncMock(return_value={"payments": [], "total": 0})

        with (
            patch("app.mcp.user.tenant.get_db", return_value=_async_gen(db)),
            patch("app.mcp.user.tenant._get_user", new=AsyncMock(return_value=user)),
            patch("app.mcp.user.tenant.get_rent_history", new=mock_fn),
        ):
            from app.mcp.user.tenant import tenant_rent_history

            result = await tenant_rent_history()

        assert result["ok"] is True
        assert result["data"]["payments"] == []
        assert result["data"]["total"] == 0


class TestTenantMaintenanceCreate:
    """Tests for tenant_maintenance_create MCP tool."""

    @pytest.mark.asyncio
    async def test_raises_auth_required_when_no_user(self):
        db = AsyncMock()

        with (
            patch("app.mcp.user.tenant.get_db", return_value=_async_gen(db)),
            patch("app.mcp.user.tenant._get_user", new=AsyncMock(return_value=None)),
            patch("app.mcp.user.tenant._require_auth", side_effect=_auth_error),
        ):
            from app.mcp.user.tenant import tenant_maintenance_create

            with pytest.raises(AuthRequiredError):
                await tenant_maintenance_create(
                    property_id=1,
                    title="Broken pipe",
                    description="Pipe is leaking",
                    category="plumbing",
                )

    @pytest.mark.asyncio
    async def test_no_active_lease_returns_permissions_error(self):
        db = AsyncMock()
        user = _make_user()
        mock_fn = AsyncMock(return_value={"error": True, "message": "No active lease found for this property"})

        with (
            patch("app.mcp.user.tenant.get_db", return_value=_async_gen(db)),
            patch("app.mcp.user.tenant._get_user", new=AsyncMock(return_value=user)),
            patch("app.mcp.user.tenant.create_maintenance_request", new=mock_fn),
        ):
            from app.mcp.user.tenant import tenant_maintenance_create

            result = await tenant_maintenance_create(
                property_id=1,
                title="Broken pipe",
                description="Pipe is leaking",
                category="plumbing",
            )

        assert result["ok"] is False
        assert result["error"]["code"] == MCPErrorCode.INSUFFICIENT_PERMISSIONS.value

    @pytest.mark.asyncio
    async def test_invalid_category_returns_error(self):
        db = AsyncMock()
        user = _make_user()
        mock_fn = AsyncMock(return_value={"error": True, "message": "Invalid category: rocket_science"})

        with (
            patch("app.mcp.user.tenant.get_db", return_value=_async_gen(db)),
            patch("app.mcp.user.tenant._get_user", new=AsyncMock(return_value=user)),
            patch("app.mcp.user.tenant.create_maintenance_request", new=mock_fn),
        ):
            from app.mcp.user.tenant import tenant_maintenance_create

            result = await tenant_maintenance_create(
                property_id=1,
                title="Broken pipe",
                description="Pipe is leaking",
                category="rocket_science",
            )

        assert result["ok"] is False
        assert result["error"]["code"] == MCPErrorCode.INVALID_INPUT.value

    @pytest.mark.asyncio
    async def test_invalid_priority_returns_error(self):
        db = AsyncMock()
        user = _make_user()
        mock_fn = AsyncMock(return_value={"error": True, "message": "Invalid priority: critical"})

        with (
            patch("app.mcp.user.tenant.get_db", return_value=_async_gen(db)),
            patch("app.mcp.user.tenant._get_user", new=AsyncMock(return_value=user)),
            patch("app.mcp.user.tenant.create_maintenance_request", new=mock_fn),
        ):
            from app.mcp.user.tenant import tenant_maintenance_create

            result = await tenant_maintenance_create(
                property_id=1,
                title="Broken pipe",
                description="Pipe is leaking",
                category="plumbing",
                priority="critical",
            )

        assert result["ok"] is False
        assert result["error"]["code"] == MCPErrorCode.INVALID_INPUT.value


class TestTenantMaintenanceList:
    """Tests for tenant_maintenance_list MCP tool."""

    @pytest.mark.asyncio
    async def test_raises_auth_required_when_no_user(self):
        db = AsyncMock()

        with (
            patch("app.mcp.user.tenant.get_db", return_value=_async_gen(db)),
            patch("app.mcp.user.tenant._get_user", new=AsyncMock(return_value=None)),
            patch("app.mcp.user.tenant._require_auth", side_effect=_auth_error),
        ):
            from app.mcp.user.tenant import tenant_maintenance_list

            with pytest.raises(AuthRequiredError):
                await tenant_maintenance_list()

    @pytest.mark.asyncio
    async def test_invalid_status_returns_error(self):
        db = AsyncMock()
        user = _make_user()
        mock_fn = AsyncMock(return_value={"error": True, "message": "Invalid status filter: nonexistent"})

        with (
            patch("app.mcp.user.tenant.get_db", return_value=_async_gen(db)),
            patch("app.mcp.user.tenant._get_user", new=AsyncMock(return_value=user)),
            patch("app.mcp.user.tenant.list_maintenance_requests", new=mock_fn),
        ):
            from app.mcp.user.tenant import tenant_maintenance_list

            result = await tenant_maintenance_list(status="nonexistent")

        assert result["ok"] is False
        assert result["error"]["code"] == MCPErrorCode.INVALID_INPUT.value


# ===========================================================================
# System Tools
# ===========================================================================


class TestUserSystemStatus:
    """Tests for user_system_status MCP tool."""

    @pytest.mark.asyncio
    async def test_returns_operational_status_unauthenticated(self):
        db = AsyncMock()

        with (
            patch("app.mcp.user.system.get_db", return_value=_async_gen(db)),
            patch("app.mcp.user.system._get_user", new=AsyncMock(return_value=None)),
        ):
            from app.mcp.user.system import user_system_status

            result = await user_system_status()

        assert result["ok"] is True
        assert result["data"]["status"] == "operational"
        assert result["data"]["auth"]["status"] == "unauthenticated"

    @pytest.mark.asyncio
    async def test_returns_authenticated_with_user(self):
        db = AsyncMock()
        user = _make_user()

        with (
            patch("app.mcp.user.system.get_db", return_value=_async_gen(db)),
            patch("app.mcp.user.system._get_user", new=AsyncMock(return_value=user)),
        ):
            from app.mcp.user.system import user_system_status

            result = await user_system_status()

        assert result["ok"] is True
        assert result["data"]["auth"]["status"] == "authenticated"
        assert result["data"]["auth"]["user"]["id"] == 10
