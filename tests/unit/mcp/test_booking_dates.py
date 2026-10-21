"""Mixed offset and no-offset dates compare as UTC, so a bad range is a message, not a TypeError."""

from unittest.mock import AsyncMock, patch

import pytest

from app.mcp.tool_ops import bookings as booking_ops


@pytest.mark.asyncio
async def test_create_booking_compares_mixed_date_forms_without_type_error():
    with patch.object(booking_ops.booking_svc, "check_availability", new=AsyncMock()) as avail:
        result = await booking_ops.create_booking(
            None,
            user_id=1,
            property_id=2,
            check_in_date="2026-10-20T10:00:00Z",
            check_out_date="2026-10-19",
        )

    assert result == {"error": True, "message": "Check-out date must be after check-in date"}
    avail.assert_not_called()


@pytest.mark.asyncio
async def test_get_pricing_accepts_naive_and_offset_dates():
    with patch.object(
        booking_ops.booking_svc, "calculate_pricing", new=AsyncMock(return_value={"total": 1})
    ) as pricing:
        result = await booking_ops.get_pricing(
            None,
            property_id=2,
            check_in_date="2026-10-20",
            check_out_date="2026-10-22T00:00:00+05:30",
        )

    assert result == {"pricing": {"total": 1}}
    check_in, check_out = pricing.await_args.args[2], pricing.await_args.args[3]
    assert check_in.tzinfo is not None and check_out.tzinfo is not None
