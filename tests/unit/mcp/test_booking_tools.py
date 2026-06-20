"""Edge-case and tool-ops layer tests for MCP booking tools.

The happy-path and auth-required behaviour for the booking wrappers is already
covered in ``test_user_tools.py``. This file focuses on the additional edge
cases (pagination, validation passthrough, error-code mapping, response shape)
that are not exercised there.
"""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.mcp.errors import MCPErrorCode

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _async_gen(db):
    """Async generator that yields db, mimicking get_db()."""
    yield db


def _make_user(user_id: int = 10):
    now = datetime.now(timezone.utc)
    return SimpleNamespace(
        id=user_id,
        role="user",
        supabase_user_id=f"user-{user_id}",
        phone="+919876543210",
        full_name="Owner User",
        email=f"user{user_id}@example.com",
        is_active=True,
        is_verified=True,
        agent_id=None,
        created_at=now,
        updated_at=now,
    )


# ===========================================================================
# bookings_check_availability - edge cases
# ===========================================================================


class TestBookingsCheckAvailabilityEdgeCases:
    """Edge cases for the bookings_check_availability MCP tool wrapper."""

    @pytest.mark.asyncio
    async def test_check_availability_nonexistent_property(self):
        # tool_ops returns an "unavailable" payload for a missing property;
        # the wrapper forwards it inside a success envelope.
        db = AsyncMock()
        mock_fn = AsyncMock(
            return_value={
                "available": False,
                "reason": "Property not found",
                "max_occupancy": None,
            }
        )

        with (
            patch("app.mcp.user.booking.get_db", return_value=_async_gen(db)),
            patch("app.mcp.user.booking.check_availability", new=mock_fn),
        ):
            from app.mcp.user.booking import bookings_check_availability

            result = await bookings_check_availability(
                property_id=999,
                check_in_date="2026-07-01",
                check_out_date="2026-07-05",
                guests=2,
            )

        assert result["ok"] is True
        assert result["data"]["available"] is False
        assert result["data"]["reason"] == "Property not found"

    @pytest.mark.asyncio
    async def test_check_availability_guests_zero(self):
        db = AsyncMock()
        mock_fn = AsyncMock(
            return_value={
                "available": False,
                "reason": "Number of guests must be at least 1",
                "max_occupancy": 4,
            }
        )

        with (
            patch("app.mcp.user.booking.get_db", return_value=_async_gen(db)),
            patch("app.mcp.user.booking.check_availability", new=mock_fn),
        ):
            from app.mcp.user.booking import bookings_check_availability

            result = await bookings_check_availability(
                property_id=1,
                check_in_date="2026-07-01",
                check_out_date="2026-07-05",
                guests=0,
            )

        # guests is passed through verbatim to the tool_ops layer
        assert mock_fn.call_args.kwargs["guests"] == 0
        assert result["ok"] is True
        assert result["data"]["available"] is False

    @pytest.mark.asyncio
    async def test_check_availability_no_dates(self):
        # Empty date strings are forwarded to tool_ops unchanged.
        db = AsyncMock()
        mock_fn = AsyncMock(
            return_value={
                "available": False,
                "reason": "Dates must be in ISO-8601 format",
                "max_occupancy": None,
            }
        )

        with (
            patch("app.mcp.user.booking.get_db", return_value=_async_gen(db)),
            patch("app.mcp.user.booking.check_availability", new=mock_fn),
        ):
            from app.mcp.user.booking import bookings_check_availability

            result = await bookings_check_availability(
                property_id=1,
                check_in_date="",
                check_out_date="",
                guests=2,
            )

        assert mock_fn.call_args.kwargs["check_in_date"] == ""
        assert mock_fn.call_args.kwargs["check_out_date"] == ""
        assert result["ok"] is True


# ===========================================================================
# bookings_get_pricing - edge cases
# ===========================================================================


class TestBookingsGetPricingEdgeCases:
    """Edge cases for the bookings_get_pricing MCP tool wrapper."""

    @pytest.mark.asyncio
    async def test_get_pricing_invalid_date_format(self):
        db = AsyncMock()
        mock_fn = AsyncMock(
            return_value={"error": True, "message": "Dates must be in ISO-8601 format"}
        )

        with (
            patch("app.mcp.user.booking.get_db", return_value=_async_gen(db)),
            patch("app.mcp.user.booking.get_pricing", new=mock_fn),
        ):
            from app.mcp.user.booking import bookings_get_pricing

            result = await bookings_get_pricing(
                property_id=1,
                check_in_date="not-a-date",
                check_out_date="2026-07-05",
            )

        assert result["ok"] is False
        assert result["error"]["code"] == MCPErrorCode.INVALID_INPUT.value
        assert "ISO-8601" in result["error"]["message"]

    @pytest.mark.asyncio
    async def test_get_pricing_nonexistent_property(self):
        db = AsyncMock()
        mock_fn = AsyncMock(
            return_value={"error": True, "message": "Property not available for short stay"}
        )

        with (
            patch("app.mcp.user.booking.get_db", return_value=_async_gen(db)),
            patch("app.mcp.user.booking.get_pricing", new=mock_fn),
        ):
            from app.mcp.user.booking import bookings_get_pricing

            result = await bookings_get_pricing(
                property_id=999,
                check_in_date="2026-07-01",
                check_out_date="2026-07-05",
            )

        assert result["ok"] is False
        assert result["error"]["code"] == MCPErrorCode.INVALID_INPUT.value

    @pytest.mark.asyncio
    async def test_get_pricing_negative_guests(self):
        db = AsyncMock()
        mock_fn = AsyncMock(
            return_value={"error": True, "message": "Number of guests must be at least 1"}
        )

        with (
            patch("app.mcp.user.booking.get_db", return_value=_async_gen(db)),
            patch("app.mcp.user.booking.get_pricing", new=mock_fn),
        ):
            from app.mcp.user.booking import bookings_get_pricing

            result = await bookings_get_pricing(
                property_id=1,
                check_in_date="2026-07-01",
                check_out_date="2026-07-05",
                guests=-3,
            )

        # negative guest count is forwarded to tool_ops unchanged
        assert mock_fn.call_args.kwargs["guests"] == -3
        assert result["ok"] is False
        assert result["error"]["code"] == MCPErrorCode.INVALID_INPUT.value


# ===========================================================================
# bookings_list - pagination / filtering
# ===========================================================================


class TestBookingsListPagination:
    """Pagination and filtering behaviour for bookings_list."""

    @pytest.mark.asyncio
    async def test_list_with_cursor(self):
        db = AsyncMock()
        user = _make_user()
        cursor_payload = {"id": 42}
        mock_fn = AsyncMock(
            return_value={
                "total": 1,
                "upcoming": 1,
                "completed": 0,
                "cancelled": 0,
                "next_cursor": None,
                "has_more": False,
                "bookings": [{"id": 42, "booking_status": "confirmed"}],
            }
        )

        with (
            patch("app.mcp.user.booking.get_db", return_value=_async_gen(db)),
            patch("app.mcp.user.booking._get_user", new=AsyncMock(return_value=user)),
            patch("app.mcp.user.booking.decode_cursor", return_value=cursor_payload),
            patch("app.mcp.user.booking.list_user_bookings", new=mock_fn),
        ):
            from app.mcp.user.booking import bookings_list

            result = await bookings_list(cursor="opaque-cursor", limit=20)

        assert mock_fn.call_args.kwargs["cursor_payload"] == cursor_payload
        assert result["ok"] is True
        assert result["data"]["total"] == 1
        assert result["data"]["bookings"][0]["id"] == 42

    @pytest.mark.asyncio
    async def test_list_with_status_filter(self):
        db = AsyncMock()
        user = _make_user()
        mock_fn = AsyncMock(
            return_value={
                "total": 0,
                "upcoming": 0,
                "completed": 0,
                "cancelled": 0,
                "next_cursor": None,
                "has_more": False,
                "bookings": [],
            }
        )

        with (
            patch("app.mcp.user.booking.get_db", return_value=_async_gen(db)),
            patch("app.mcp.user.booking._get_user", new=AsyncMock(return_value=user)),
            patch("app.mcp.user.booking.list_user_bookings", new=mock_fn),
        ):
            from app.mcp.user.booking import bookings_list

            await bookings_list(status="confirmed", limit=10)

        assert mock_fn.call_args.kwargs["status"] == "confirmed"

    @pytest.mark.asyncio
    async def test_list_empty_result(self):
        db = AsyncMock()
        user = _make_user()
        mock_fn = AsyncMock(
            return_value={
                "total": 0,
                "upcoming": 0,
                "completed": 0,
                "cancelled": 0,
                "next_cursor": None,
                "has_more": False,
                "bookings": [],
            }
        )

        with (
            patch("app.mcp.user.booking.get_db", return_value=_async_gen(db)),
            patch("app.mcp.user.booking._get_user", new=AsyncMock(return_value=user)),
            patch("app.mcp.user.booking.list_user_bookings", new=mock_fn),
        ):
            from app.mcp.user.booking import bookings_list

            result = await bookings_list()

        assert result["ok"] is True
        assert result["data"]["total"] == 0
        assert result["data"]["bookings"] == []
        assert result["data"]["has_more"] is False


# ===========================================================================
# bookings_create - edge cases
# ===========================================================================


class TestBookingsCreateEdgeCases:
    """Edge cases for the bookings_create MCP tool wrapper."""

    @pytest.mark.asyncio
    async def test_create_negative_guests(self):
        # tool_ops rejects non-positive guest counts; the wrapper maps every
        # create_booking error to BOOKING_CONFLICT.
        db = AsyncMock()
        user = _make_user()
        mock_fn = AsyncMock(
            return_value={"error": True, "message": "Number of guests must be at least 1"}
        )

        with (
            patch("app.mcp.user.booking.get_db", return_value=_async_gen(db)),
            patch("app.mcp.user.booking._get_user", new=AsyncMock(return_value=user)),
            patch("app.mcp.user.booking.create_booking", new=mock_fn),
        ):
            from app.mcp.user.booking import bookings_create

            result = await bookings_create(
                property_id=1,
                check_in_date="2026-07-01",
                check_out_date="2026-07-05",
                guests=0,
            )

        assert mock_fn.call_args.kwargs["guests"] == 0
        assert result["ok"] is False
        assert result["error"]["code"] == MCPErrorCode.BOOKING_CONFLICT.value

    @pytest.mark.asyncio
    async def test_create_missing_dates(self):
        db = AsyncMock()
        user = _make_user()
        mock_fn = AsyncMock(
            return_value={"error": True, "message": "Dates must be in ISO-8601 format"}
        )

        with (
            patch("app.mcp.user.booking.get_db", return_value=_async_gen(db)),
            patch("app.mcp.user.booking._get_user", new=AsyncMock(return_value=user)),
            patch("app.mcp.user.booking.create_booking", new=mock_fn),
        ):
            from app.mcp.user.booking import bookings_create

            result = await bookings_create(
                property_id=1,
                check_in_date="",
                check_out_date="",
            )

        assert result["ok"] is False
        assert result["error"]["code"] == MCPErrorCode.BOOKING_CONFLICT.value

    @pytest.mark.asyncio
    async def test_create_special_requests(self):
        db = AsyncMock()
        user = _make_user()
        mock_fn = AsyncMock(
            return_value={
                "message": "Booking created successfully",
                "booking": {"id": 7},
            }
        )

        with (
            patch("app.mcp.user.booking.get_db", return_value=_async_gen(db)),
            patch("app.mcp.user.booking._get_user", new=AsyncMock(return_value=user)),
            patch("app.mcp.user.booking.create_booking", new=mock_fn),
        ):
            from app.mcp.user.booking import bookings_create

            result = await bookings_create(
                property_id=1,
                check_in_date="2026-07-01",
                check_out_date="2026-07-05",
                guests=2,
                special_requests="Early check-in please",
            )

        assert mock_fn.call_args.kwargs["special_requests"] == "Early check-in please"
        assert result["ok"] is True
        assert result["data"]["booking"]["id"] == 7


# ===========================================================================
# bookings_cancel - edge cases
# ===========================================================================


class TestBookingsCancelEdgeCases:
    """Edge cases for the bookings_cancel MCP tool wrapper."""

    @pytest.mark.asyncio
    async def test_cancel_missing_reason(self):
        # `reason` is a required positional parameter with no default.
        from app.mcp.user.booking import bookings_cancel

        with pytest.raises(TypeError):
            await bookings_cancel(booking_id=1)

    @pytest.mark.asyncio
    async def test_cancel_other_users_booking(self):
        db = AsyncMock()
        user = _make_user()
        mock_fn = AsyncMock(
            return_value={
                "error": True,
                "code": "FORBIDDEN",
                "message": "You can only cancel your own bookings.",
            }
        )

        with (
            patch("app.mcp.user.booking.get_db", return_value=_async_gen(db)),
            patch("app.mcp.user.booking._get_user", new=AsyncMock(return_value=user)),
            patch("app.mcp.user.booking.cancel_booking", new=mock_fn),
        ):
            from app.mcp.user.booking import bookings_cancel

            result = await bookings_cancel(booking_id=1, reason="N/A")

        assert result["ok"] is False
        assert result["error"]["code"] == MCPErrorCode.INSUFFICIENT_PERMISSIONS.value


# ===========================================================================
# Response envelope shape
# ===========================================================================


class TestBookingsResponseFormat:
    """Verify the MCPResponse envelope shape produced by the wrappers."""

    @pytest.mark.asyncio
    async def test_success_response_has_ok_true(self):
        db = AsyncMock()
        user = _make_user()
        mock_fn = AsyncMock(
            return_value={
                "total": 1,
                "upcoming": 1,
                "completed": 0,
                "cancelled": 0,
                "next_cursor": None,
                "has_more": False,
                "bookings": [{"id": 1}],
            }
        )

        with (
            patch("app.mcp.user.booking.get_db", return_value=_async_gen(db)),
            patch("app.mcp.user.booking._get_user", new=AsyncMock(return_value=user)),
            patch("app.mcp.user.booking.list_user_bookings", new=mock_fn),
        ):
            from app.mcp.user.booking import bookings_list

            result = await bookings_list()

        assert result["ok"] is True
        assert "data" in result
        assert result.get("error") is None

    @pytest.mark.asyncio
    async def test_error_response_has_ok_false(self):
        db = AsyncMock()
        user = _make_user()
        mock_fn = AsyncMock(
            return_value={
                "error": True,
                "code": "NOT_FOUND",
                "message": "Booking not found",
            }
        )

        with (
            patch("app.mcp.user.booking.get_db", return_value=_async_gen(db)),
            patch("app.mcp.user.booking._get_user", new=AsyncMock(return_value=user)),
            patch("app.mcp.user.booking.get_booking_detail", new=mock_fn),
        ):
            from app.mcp.user.booking import bookings_get

            result = await bookings_get(booking_id=999)

        assert result["ok"] is False
        assert "error" in result
        assert result["error"]["code"] == MCPErrorCode.NOT_FOUND.value
        assert result.get("data") is None
