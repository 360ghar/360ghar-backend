"""Unit tests for MCP booking tool_ops layer.

These tests exercise the shared booking tool_ops functions in
``app/mcp/tool_ops/bookings.py`` directly, mocking the service layer
(``app.services.booking``) and the DB session to verify that each function:
- Translates service results into the tool_ops dict contract
- Performs ownership / status validation
- Returns the expected error codes (NOT_FOUND, FORBIDDEN, OPERATION_FAILED)
- Respects the "overlapping bookings allowed" business rule
"""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.mcp.tool_ops import bookings as bookings_tool_ops
from app.models.enums import BookingStatus

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _EnumLike:
    """Lightweight stand-in for SQLAlchemy enum column values."""

    def __init__(self, value: str) -> None:
        self.value = value

    def __eq__(self, other: object) -> bool:
        if isinstance(other, str):
            return self.value == other
        if isinstance(other, _EnumLike):
            return self.value == other.value
        return NotImplemented

    def __hash__(self) -> int:
        return hash(self.value)


def _make_booking(
    booking_id: int = 1,
    property_id: int = 1,
    user_id: int = 10,
    status: BookingStatus = BookingStatus.confirmed,
) -> SimpleNamespace:
    """Create a mock booking row compatible with serialize_booking."""
    return SimpleNamespace(
        id=booking_id,
        booking_reference=f"BK{booking_id:08d}",
        property_id=property_id,
        user_id=user_id,
        check_in_date=datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc),
        check_out_date=datetime(2026, 7, 5, 11, 0, tzinfo=timezone.utc),
        guests=2,
        nights=4,
        base_amount=8000.0,
        taxes_amount=1440.0,
        service_charges=400.0,
        discount_amount=0.0,
        total_amount=9840.0,
        booking_status=status,
        payment_status=None,
        payment_method=None,
        special_requests=None,
        cancellation_reason=None,
        cancellation_date=None,
        created_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
    )


def _make_property_row(property_id: int = 1) -> SimpleNamespace:
    """Create a mock property row compatible with serialize_property_basic."""
    return SimpleNamespace(
        id=property_id,
        title="Test Property",
        property_type=None,
        purpose=None,
        status=None,
        management_status=None,
        city="Delhi",
        locality="Karol Bagh",
        full_address="Karol Bagh, Delhi",
        base_price=5000000,
        monthly_rent=None,
        daily_rate=None,
        bedrooms=3,
        bathrooms=2,
        area_sqft=1200,
        is_available=True,
        is_managed=False,
        latitude=None,
        longitude=None,
        main_image_url=None,
        created_at=None,
    )


def _scalar_result(value):
    """Build a mock db.execute() result with sync scalar_one_or_none().

    The tool_ops code does ``(await db.execute(...)).scalar_one_or_none()``
    (no second await), so the method must be a sync MagicMock that returns
    the value directly.
    """
    from unittest.mock import MagicMock

    result = MagicMock()
    result.scalar_one_or_none = MagicMock(return_value=value)
    return result


# ---------------------------------------------------------------------------
# check_availability
# ---------------------------------------------------------------------------


class TestCheckAvailability:
    async def test_available_property(self) -> None:
        db = AsyncMock()
        svc_mock = AsyncMock(
            return_value={"available": True, "max_occupancy": 5, "reason": None}
        )
        with patch.object(bookings_tool_ops.booking_svc, "check_availability", svc_mock):
            result = await bookings_tool_ops.check_availability(
                db,
                property_id=1,
                check_in_date="2026-07-01",
                check_out_date="2026-07-05",
                guests=2,
            )

        assert result == {
            "available": True,
            "reason": None,
            "max_occupancy": 5,
        }
        svc_mock.assert_awaited_once_with(db, 1, "2026-07-01", "2026-07-05", 2)

    async def test_nonexistent_property(self) -> None:
        db = AsyncMock()
        svc_mock = AsyncMock(
            return_value={"available": False, "reason": "Property not found"}
        )
        with patch.object(bookings_tool_ops.booking_svc, "check_availability", svc_mock):
            result = await bookings_tool_ops.check_availability(
                db,
                property_id=999,
                check_in_date="2026-07-01",
                check_out_date="2026-07-05",
                guests=1,
            )

        assert result["available"] is False
        assert result["reason"] == "Property not found"

    async def test_guests_exceed_max(self) -> None:
        db = AsyncMock()
        svc_mock = AsyncMock(
            return_value={
                "available": False,
                "reason": "Property can accommodate maximum 4 guests",
                "max_occupancy": 4,
            }
        )
        with patch.object(bookings_tool_ops.booking_svc, "check_availability", svc_mock):
            result = await bookings_tool_ops.check_availability(
                db,
                property_id=1,
                check_in_date="2026-07-01",
                check_out_date="2026-07-05",
                guests=10,
            )

        assert result["available"] is False
        assert "maximum 4 guests" in result["reason"]
        assert result["max_occupancy"] == 4


# ---------------------------------------------------------------------------
# get_pricing
# ---------------------------------------------------------------------------


class TestGetPricing:
    async def test_valid_dates(self) -> None:
        db = AsyncMock()
        pricing_dict = {
            "nights": 4,
            "base_amount": 8000,
            "taxes_amount": 1440,
            "service_charges": 400,
            "total_amount": 9840,
        }
        svc_mock = AsyncMock(return_value=pricing_dict)
        with patch.object(bookings_tool_ops.booking_svc, "calculate_pricing", svc_mock):
            result = await bookings_tool_ops.get_pricing(
                db,
                property_id=1,
                check_in_date="2026-07-01T12:00:00",
                check_out_date="2026-07-05T11:00:00",
                guests=2,
            )

        assert result["pricing"] == pricing_dict
        assert "error" not in result
        # calculate_pricing is called with parsed datetime objects
        call_args = svc_mock.await_args
        assert call_args.args[0] is db
        assert call_args.args[1] == 1
        assert isinstance(call_args.args[2], datetime)
        assert isinstance(call_args.args[3], datetime)
        assert call_args.args[4] == 2

    async def test_invalid_date_format(self) -> None:
        db = AsyncMock()
        svc_mock = AsyncMock()
        with patch.object(bookings_tool_ops.booking_svc, "calculate_pricing", svc_mock):
            result = await bookings_tool_ops.get_pricing(
                db,
                property_id=1,
                check_in_date="not-a-date",
                check_out_date="2026-07-05",
                guests=1,
            )

        assert result["error"] is True
        assert "ISO-8601" in result["message"]
        svc_mock.assert_not_awaited()

    async def test_nonexistent_property(self) -> None:
        db = AsyncMock()
        svc_mock = AsyncMock(return_value={"error": "Property not found"})
        with patch.object(bookings_tool_ops.booking_svc, "calculate_pricing", svc_mock):
            result = await bookings_tool_ops.get_pricing(
                db,
                property_id=999,
                check_in_date="2026-07-01",
                check_out_date="2026-07-05",
                guests=1,
            )

        assert result["error"] is True
        assert result["message"] == "Property not found"


# ---------------------------------------------------------------------------
# create_booking
# ---------------------------------------------------------------------------


class TestCreateBooking:
    async def test_success(self) -> None:
        db = AsyncMock()
        avail_mock = AsyncMock(return_value={"available": True, "max_occupancy": 5})
        created = _make_booking(booking_id=42)
        create_mock = AsyncMock(return_value=created)

        with (
            patch.object(bookings_tool_ops.booking_svc, "check_availability", avail_mock),
            patch.object(bookings_tool_ops.booking_svc, "create_booking", create_mock),
        ):
            result = await bookings_tool_ops.create_booking(
                db,
                user_id=10,
                property_id=1,
                check_in_date="2026-07-01T12:00:00",
                check_out_date="2026-07-05T11:00:00",
                guests=2,
                special_requests="Early check-in",
            )

        assert result["message"] == "Booking created successfully"
        assert result["booking"]["id"] == 42
        # create_booking(db, user_id, booking_data) — booking_data is args[2]
        call_args = create_mock.await_args
        assert call_args.args[0] is db
        assert call_args.args[1] == 10  # user_id
        booking_data = call_args.args[2]
        assert booking_data.property_id == 1
        assert booking_data.guests == 2
        assert booking_data.special_requests == "Early check-in"
        db.commit.assert_awaited_once()

    async def test_property_not_found(self) -> None:
        db = AsyncMock()
        avail_mock = AsyncMock(
            return_value={"available": False, "reason": "Property not found"}
        )
        create_mock = AsyncMock()

        with (
            patch.object(bookings_tool_ops.booking_svc, "check_availability", avail_mock),
            patch.object(bookings_tool_ops.booking_svc, "create_booking", create_mock),
        ):
            result = await bookings_tool_ops.create_booking(
                db,
                user_id=10,
                property_id=999,
                check_in_date="2026-07-01",
                check_out_date="2026-07-05",
                guests=1,
            )

        assert result["error"] is True
        assert "Property not found" in result["message"]
        create_mock.assert_not_awaited()
        db.commit.assert_not_awaited()

    async def test_overlapping_allowed(self) -> None:
        """Business rule: overlapping bookings ARE allowed at the tool_ops layer.

        The tool_ops layer delegates to booking_svc.check_availability which only
        validates property existence + max_occupancy. No date overlap conflict
        check exists, so two overlapping date ranges should both succeed.
        """
        db = AsyncMock()
        avail_mock = AsyncMock(return_value={"available": True, "max_occupancy": 5})

        first_booking = _make_booking(booking_id=1)
        second_booking = _make_booking(booking_id=2)
        create_mock = AsyncMock(side_effect=[first_booking, second_booking])

        with (
            patch.object(bookings_tool_ops.booking_svc, "check_availability", avail_mock),
            patch.object(bookings_tool_ops.booking_svc, "create_booking", create_mock),
        ):
            # First booking: July 1-5
            r1 = await bookings_tool_ops.create_booking(
                db,
                user_id=10,
                property_id=1,
                check_in_date="2026-07-01T12:00:00",
                check_out_date="2026-07-05T11:00:00",
            )
            # Second booking: July 3-7 (overlapping with first)
            r2 = await bookings_tool_ops.create_booking(
                db,
                user_id=11,
                property_id=1,
                check_in_date="2026-07-03T12:00:00",
                check_out_date="2026-07-07T11:00:00",
            )

        assert "error" not in r1
        assert "error" not in r2
        assert r1["booking"]["id"] == 1
        assert r2["booking"]["id"] == 2
        # create_booking called twice (no overlap rejection)
        assert create_mock.await_count == 2
        # check_availability never received an overlap-related reason
        for call in avail_mock.await_args_list:
            assert "overlap" not in str(call).lower()


# ---------------------------------------------------------------------------
# list_user_bookings
# ---------------------------------------------------------------------------


class TestListUserBookings:
    async def test_returns_bookings(self) -> None:
        db = AsyncMock()
        rows = [
            _make_booking(booking_id=1, status=BookingStatus.confirmed),
            _make_booking(booking_id=2, status=BookingStatus.completed),
        ]
        svc_mock = AsyncMock(return_value=(rows, None, 2))

        with patch.object(bookings_tool_ops.booking_svc, "get_user_bookings", svc_mock):
            result = await bookings_tool_ops.list_user_bookings(db, user_id=10, limit=20)

        assert result["total"] == 2
        assert result["upcoming"] == 1
        assert result["completed"] == 1
        assert result["cancelled"] == 0
        assert result["has_more"] is False
        assert result["next_cursor"] is None
        assert len(result["bookings"]) == 2

    async def test_empty_result(self) -> None:
        db = AsyncMock()
        svc_mock = AsyncMock(return_value=([], None, 0))

        with patch.object(bookings_tool_ops.booking_svc, "get_user_bookings", svc_mock):
            result = await bookings_tool_ops.list_user_bookings(db, user_id=10)

        assert result["total"] == 0
        assert result["upcoming"] == 0
        assert result["completed"] == 0
        assert result["bookings"] == []

    async def test_status_filter(self) -> None:
        db = AsyncMock()
        rows = [
            _make_booking(booking_id=1, status=BookingStatus.confirmed),
            _make_booking(booking_id=2, status=BookingStatus.cancelled),
            _make_booking(booking_id=3, status=BookingStatus.confirmed),
        ]
        svc_mock = AsyncMock(return_value=(rows, None, 3))

        with patch.object(bookings_tool_ops.booking_svc, "get_user_bookings", svc_mock):
            result = await bookings_tool_ops.list_user_bookings(
                db, user_id=10, status="confirmed"
            )

        # Only confirmed bookings survive the in-memory filter
        assert result["total"] == 2
        assert all(b["booking_status"] == "confirmed" for b in result["bookings"])
        assert result["upcoming"] == 2

    async def test_limit_clamped_to_max(self) -> None:
        db = AsyncMock()
        svc_mock = AsyncMock(return_value=([], None, 0))

        with patch.object(bookings_tool_ops.booking_svc, "get_user_bookings", svc_mock):
            await bookings_tool_ops.list_user_bookings(db, user_id=10, limit=9999)

        assert svc_mock.await_args.kwargs["limit"] == 100

    async def test_limit_clamped_to_min(self) -> None:
        db = AsyncMock()
        svc_mock = AsyncMock(return_value=([], None, 0))

        with patch.object(bookings_tool_ops.booking_svc, "get_user_bookings", svc_mock):
            await bookings_tool_ops.list_user_bookings(db, user_id=10, limit=0)

        assert svc_mock.await_args.kwargs["limit"] == 1

    async def test_pagination_next_cursor_emitted(self) -> None:
        db = AsyncMock()
        rows = [_make_booking(booking_id=1)]
        next_payload = {"v": 1, "k": ["2026-06-01T00:00:00+00:00", 1]}
        svc_mock = AsyncMock(return_value=(rows, next_payload, 50))

        with patch.object(bookings_tool_ops.booking_svc, "get_user_bookings", svc_mock):
            result = await bookings_tool_ops.list_user_bookings(db, user_id=10, limit=1)

        assert result["has_more"] is True
        assert result["next_cursor"] is not None


# ---------------------------------------------------------------------------
# get_booking_detail
# ---------------------------------------------------------------------------


class TestGetBookingDetail:
    async def test_success(self) -> None:
        db = AsyncMock()
        booking = _make_booking(booking_id=7, user_id=10, property_id=3)
        prop = _make_property_row(property_id=3)
        db.execute = AsyncMock(return_value=_scalar_result(prop))

        with patch.object(bookings_tool_ops.booking_svc, "get_booking", AsyncMock(return_value=booking)):
            result = await bookings_tool_ops.get_booking_detail(
                db, booking_id=7, user_id=10
            )

        assert "error" not in result
        assert result["booking"]["id"] == 7
        assert result["property"]["id"] == 3
        assert result["property"]["title"] == "Test Property"

    async def test_not_found(self) -> None:
        db = AsyncMock()
        with patch.object(bookings_tool_ops.booking_svc, "get_booking", AsyncMock(return_value=None)):
            result = await bookings_tool_ops.get_booking_detail(
                db, booking_id=999, user_id=10
            )

        assert result["error"] is True
        assert result["code"] == bookings_tool_ops.TOOL_OPS_NOT_FOUND
        assert "999" in result["message"]
        db.execute.assert_not_awaited()

    async def test_insufficient_permissions(self) -> None:
        db = AsyncMock()
        # Booking belongs to user 10, but requester is user 99
        booking = _make_booking(booking_id=7, user_id=10)
        with patch.object(bookings_tool_ops.booking_svc, "get_booking", AsyncMock(return_value=booking)):
            result = await bookings_tool_ops.get_booking_detail(
                db, booking_id=7, user_id=99
            )

        assert result["error"] is True
        assert result["code"] == bookings_tool_ops.TOOL_OPS_FORBIDDEN
        assert "own bookings" in result["message"]
        db.execute.assert_not_awaited()


# ---------------------------------------------------------------------------
# cancel_booking
# ---------------------------------------------------------------------------


class TestCancelBooking:
    async def test_success(self) -> None:
        db = AsyncMock()
        booking = _make_booking(booking_id=5, user_id=10, status=BookingStatus.confirmed)
        cancel_mock = AsyncMock(return_value=True)

        with (
            patch.object(bookings_tool_ops.booking_svc, "get_booking", AsyncMock(return_value=booking)),
            patch.object(bookings_tool_ops.booking_svc, "cancel_booking", cancel_mock),
        ):
            result = await bookings_tool_ops.cancel_booking(
                db, booking_id=5, user_id=10, reason="Change of plans"
            )

        assert result["message"] == "Booking 5 cancelled."
        assert result["booking_id"] == 5
        cancel_mock.assert_awaited_once_with(db, 5, "Change of plans")
        db.commit.assert_awaited_once()

    async def test_not_found(self) -> None:
        db = AsyncMock()
        cancel_mock = AsyncMock()
        with (
            patch.object(bookings_tool_ops.booking_svc, "get_booking", AsyncMock(return_value=None)),
            patch.object(bookings_tool_ops.booking_svc, "cancel_booking", cancel_mock),
        ):
            result = await bookings_tool_ops.cancel_booking(
                db, booking_id=999, user_id=10, reason="N/A"
            )

        assert result["error"] is True
        assert result["code"] == bookings_tool_ops.TOOL_OPS_NOT_FOUND
        cancel_mock.assert_not_awaited()
        db.commit.assert_not_awaited()

    async def test_already_cancelled(self) -> None:
        db = AsyncMock()
        booking = _make_booking(
            booking_id=5, user_id=10, status=BookingStatus.cancelled
        )
        cancel_mock = AsyncMock()
        with (
            patch.object(bookings_tool_ops.booking_svc, "get_booking", AsyncMock(return_value=booking)),
            patch.object(bookings_tool_ops.booking_svc, "cancel_booking", cancel_mock),
        ):
            result = await bookings_tool_ops.cancel_booking(
                db, booking_id=5, user_id=10, reason="N/A"
            )

        assert result["error"] is True
        assert result["code"] == bookings_tool_ops.TOOL_OPS_OPERATION_FAILED
        assert "cancelled" in result["message"]
        cancel_mock.assert_not_awaited()
        db.commit.assert_not_awaited()

    async def test_insufficient_permissions(self) -> None:
        db = AsyncMock()
        booking = _make_booking(booking_id=5, user_id=10, status=BookingStatus.confirmed)
        cancel_mock = AsyncMock()
        with (
            patch.object(bookings_tool_ops.booking_svc, "get_booking", AsyncMock(return_value=booking)),
            patch.object(bookings_tool_ops.booking_svc, "cancel_booking", cancel_mock),
        ):
            result = await bookings_tool_ops.cancel_booking(
                db, booking_id=5, user_id=99, reason="N/A"
            )

        assert result["error"] is True
        assert result["code"] == bookings_tool_ops.TOOL_OPS_FORBIDDEN
        cancel_mock.assert_not_awaited()
        db.commit.assert_not_awaited()

    @pytest.mark.parametrize(
        "status",
        [
            BookingStatus.completed,
            BookingStatus.checked_out,
        ],
    )
    async def test_cannot_cancel_terminal_status(self, status: BookingStatus) -> None:
        db = AsyncMock()
        booking = _make_booking(booking_id=5, user_id=10, status=status)
        with (
            patch.object(bookings_tool_ops.booking_svc, "get_booking", AsyncMock(return_value=booking)),
            patch.object(bookings_tool_ops.booking_svc, "cancel_booking", AsyncMock()),
        ):
            result = await bookings_tool_ops.cancel_booking(
                db, booking_id=5, user_id=10, reason="N/A"
            )

        assert result["error"] is True
        assert result["code"] == bookings_tool_ops.TOOL_OPS_OPERATION_FAILED
