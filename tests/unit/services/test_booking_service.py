"""
Tests for booking service module.
"""

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.bookings import Booking
from app.models.enums import BookingStatus, PaymentStatus


class TestCreateBooking:
    """Tests for create_booking function."""

    @pytest.mark.asyncio
    async def test_create_booking_success(
        self,
        db_session: AsyncSession,
        test_user_2,
        test_short_stay_property,
    ):
        """Test successful booking creation."""
        from app.services.booking import create_booking
        from app.schemas.booking import BookingCreate

        check_in = datetime.now(timezone.utc) + timedelta(days=7)
        check_out = check_in + timedelta(days=3)

        booking_data = BookingCreate(
            property_id=test_short_stay_property.id,
            check_in_date=check_in,
            check_out_date=check_out,
            guests=2,
            primary_guest_name="Test Guest",
            primary_guest_phone="+919876543210",
            primary_guest_email="guest@test.com",
        )

        with patch("app.services.booking.calculate_pricing", new_callable=AsyncMock) as mock_pricing:
            mock_pricing.return_value = {
                "nights": 3,
                "base_amount": Decimal("6000"),
                "taxes_amount": Decimal("1080"),
                "service_charges": Decimal("300"),
                "discount_amount": Decimal("0"),
                "total_amount": Decimal("7380"),
            }

            result = await create_booking(db_session, test_user_2.id, booking_data)

            assert result is not None
            assert result.user_id == test_user_2.id
            assert result.property_id == test_short_stay_property.id
            assert result.booking_status == "pending"
            assert result.payment_status == "pending"
            assert result.booking_reference.startswith("BK")

    @pytest.mark.asyncio
    async def test_create_booking_invalid_dates(
        self,
        db_session: AsyncSession,
        test_user_2,
        test_short_stay_property,
    ):
        """Test booking creation fails with invalid date range."""
        from app.schemas.booking import BookingCreate
        from pydantic import ValidationError

        check_in = datetime.now(timezone.utc) + timedelta(days=7)
        check_out = check_in - timedelta(days=1)  # Invalid: checkout before checkin

        # Pydantic validation catches this at schema creation time
        with pytest.raises(ValidationError) as exc_info:
            BookingCreate(
                property_id=test_short_stay_property.id,
                check_in_date=check_in,
                check_out_date=check_out,
                guests=2,
                primary_guest_name="Test Guest",
                primary_guest_phone="+919876543210",
                primary_guest_email="guest@test.com",
            )

        assert "Check-out date must be after check-in date" in str(exc_info.value)


class TestGetBooking:
    """Tests for get_booking function."""

    @pytest.mark.asyncio
    async def test_get_booking_success(
        self,
        db_session: AsyncSession,
        test_booking,
    ):
        """Test getting booking by ID."""
        from app.services.booking import get_booking

        result = await get_booking(db_session, test_booking.id)

        assert result is not None
        assert result.id == test_booking.id

    @pytest.mark.asyncio
    async def test_get_booking_not_found(self, db_session: AsyncSession):
        """Test getting non-existent booking."""
        from app.services.booking import get_booking

        result = await get_booking(db_session, 99999)

        assert result is None


class TestGetUserBookings:
    """Tests for get_user_bookings function."""

    @pytest.mark.asyncio
    async def test_get_user_bookings(
        self,
        db_session: AsyncSession,
        test_user,
        test_bookings,
    ):
        """Test getting all bookings for a user."""
        from app.services.booking import get_user_bookings

        result = await get_user_bookings(db_session, test_user.id)

        assert "bookings" in result
        assert "total" in result
        assert "upcoming" in result
        assert "completed" in result
        assert "cancelled" in result
        assert result["total"] == len(test_bookings)

    @pytest.mark.asyncio
    async def test_get_user_bookings_empty(self, db_session: AsyncSession, test_user_2):
        """Test getting bookings for user with no bookings."""
        from app.services.booking import get_user_bookings

        # test_user_2 has no bookings in this scenario
        result = await get_user_bookings(db_session, 99999)  # Non-existent user

        assert result["total"] == 0
        assert len(result["bookings"]) == 0


class TestGetUserUpcomingBookings:
    """Tests for get_user_upcoming_bookings function."""

    @pytest.mark.asyncio
    async def test_get_upcoming_bookings(
        self,
        db_session: AsyncSession,
        test_user,
        test_bookings,
    ):
        """Test getting upcoming bookings."""
        from app.services.booking import get_user_upcoming_bookings

        result = await get_user_upcoming_bookings(db_session, test_user.id)

        assert "bookings" in result
        assert "total" in result


class TestGetUserPastBookings:
    """Tests for get_user_past_bookings function."""

    @pytest.mark.asyncio
    async def test_get_past_bookings(
        self,
        db_session: AsyncSession,
        test_user,
        test_bookings,
    ):
        """Test getting past bookings."""
        from app.services.booking import get_user_past_bookings

        result = await get_user_past_bookings(db_session, test_user.id)

        assert "bookings" in result


class TestBookingStatusTransitions:
    """Tests for booking status transitions."""

    @pytest.mark.asyncio
    async def test_booking_starts_as_pending(self, test_booking):
        """Test new booking starts with pending status."""
        assert test_booking.booking_status == BookingStatus.pending.value

    @pytest.mark.asyncio
    async def test_confirmed_booking(self, confirmed_booking):
        """Test confirmed booking has correct status."""
        assert confirmed_booking.booking_status == BookingStatus.confirmed.value
        assert confirmed_booking.payment_status == PaymentStatus.paid.value


class TestBookingReferenceGeneration:
    """Tests for booking reference generation."""

    @pytest.mark.asyncio
    async def test_booking_reference_format(self, test_booking):
        """Test booking reference has correct format."""
        assert test_booking.booking_reference.startswith("BK")
        assert len(test_booking.booking_reference) == 10  # BK + 8 chars

    @pytest.mark.asyncio
    async def test_booking_references_are_unique(
        self,
        db_session: AsyncSession,
        test_bookings,
    ):
        """Test each booking has unique reference."""
        references = [b.booking_reference for b in test_bookings]
        assert len(references) == len(set(references))


class TestAddReview:
    """Tests for add_review function."""

    @pytest.mark.asyncio
    async def test_add_review_maps_guest_fields_correctly(
        self,
        db_session: AsyncSession,
        test_booking,
    ):
        """Review payload should persist guest_rating/guest_review fields."""
        from app.schemas.booking import BookingReview
        from app.services.booking import add_review

        review_data = BookingReview(
            booking_id=test_booking.id,
            guest_rating=5,
            guest_review="Great stay and smooth check-in.",
        )

        result = await add_review(db_session, review_data)

        assert result is True
        await db_session.refresh(test_booking)
        assert test_booking.guest_rating == 5
        assert test_booking.guest_review == "Great stay and smooth check-in."
