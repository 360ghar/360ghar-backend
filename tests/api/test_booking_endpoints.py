"""
Tests for booking endpoints.

These tests verify the booking-related API endpoints work correctly.
They mock the service layer to isolate endpoint testing.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

from app.models.enums import BookingStatus, PaymentStatus
from app.schemas.booking import Booking


def create_mock_booking(
    booking_id: int = 1,
    user_id: int = 1,
    property_id: int = 1,
    booking_status: BookingStatus = BookingStatus.pending,
    payment_status: PaymentStatus = PaymentStatus.pending,
) -> Booking:
    """Create a mock booking schema object."""
    return Booking(
        id=booking_id,
        user_id=user_id,
        property_id=property_id,
        booking_reference=f"BK{booking_id:08d}",
        check_in_date=datetime.now(timezone.utc) + timedelta(days=7),
        check_out_date=datetime.now(timezone.utc) + timedelta(days=10),
        guests=2,
        primary_guest_name="Test Guest",
        primary_guest_phone="+919876543210",
        primary_guest_email="guest@example.com",
        special_requests=None,
        nights=3,
        base_amount=6000.0,
        taxes_amount=1080.0,
        service_charges=300.0,
        discount_amount=0.0,
        total_amount=7380.0,
        booking_status=booking_status,
        payment_status=payment_status,
        guest_details=None,
        internal_notes=None,
        actual_check_in=None,
        actual_check_out=None,
        early_check_in=False,
        late_check_out=False,
        cancellation_date=None,
        cancellation_reason=None,
        refund_amount=None,
        payment_method=None,
        transaction_id=None,
        payment_date=None,
        guest_rating=None,
        guest_review=None,
        host_rating=None,
        host_review=None,
        created_at=datetime.now(timezone.utc),
        updated_at=None,
    )


class TestCreateBookingEndpoint:
    """Tests for POST /api/v1/bookings/ endpoint."""

    @pytest.mark.asyncio
    async def test_create_booking_success(self, authenticated_client: AsyncClient):
        """Test successful booking creation."""
        check_in = datetime.now(timezone.utc) + timedelta(days=7)
        check_out = check_in + timedelta(days=3)

        with patch(
            "app.api.api_v1.endpoints.bookings.create_booking",
            new_callable=AsyncMock,
        ) as mock_create:
            mock_create.return_value = create_mock_booking(
                booking_id=1,
                property_id=123,
            )

            response = await authenticated_client.post(
                "/api/v1/bookings/",
                json={
                    "property_id": 123,
                    "check_in_date": check_in.isoformat(),
                    "check_out_date": check_out.isoformat(),
                    "guests": 2,
                    "primary_guest_name": "Test Guest",
                    "primary_guest_phone": "+919876543210",
                    "primary_guest_email": "guest@example.com",
                },
            )

            assert response.status_code == 200
            data = response.json()
            assert "booking_reference" in data

    @pytest.mark.asyncio
    async def test_create_booking_unauthorized(self, client: AsyncClient):
        """Test booking creation without auth."""
        check_in = datetime.now(timezone.utc) + timedelta(days=7)
        check_out = check_in + timedelta(days=3)

        response = await client.post(
            "/api/v1/bookings/",
            json={
                "property_id": 123,
                "check_in_date": check_in.isoformat(),
                "check_out_date": check_out.isoformat(),
                "guests": 2,
                "primary_guest_name": "Test Guest",
                "primary_guest_phone": "+919876543210",
                "primary_guest_email": "guest@example.com",
            },
        )

        assert response.status_code == 401


class TestGetBookingEndpoint:
    """Tests for GET /api/v1/bookings/{booking_id} endpoint."""

    @pytest.mark.asyncio
    async def test_get_booking_success(self, authenticated_client: AsyncClient, test_user):
        """Test getting booking by ID."""
        mock_booking = create_mock_booking(booking_id=42, user_id=test_user.id)

        with patch(
            "app.api.api_v1.endpoints.bookings.get_booking",
            new_callable=AsyncMock,
        ) as mock_get:
            mock_get.return_value = mock_booking

            response = await authenticated_client.get("/api/v1/bookings/42")

            assert response.status_code == 200
            data = response.json()
            assert data["id"] == 42

    @pytest.mark.asyncio
    async def test_get_booking_not_found(self, authenticated_client: AsyncClient):
        """Test getting non-existent booking."""
        with patch(
            "app.api.api_v1.endpoints.bookings.get_booking",
            new_callable=AsyncMock,
        ) as mock_get:
            mock_get.return_value = None

            response = await authenticated_client.get("/api/v1/bookings/99999")

            assert response.status_code == 404


class TestGetUserBookingsEndpoint:
    """Tests for GET /api/v1/bookings/ endpoint."""

    @pytest.mark.asyncio
    async def test_get_user_bookings(self, authenticated_client: AsyncClient):
        """Test getting user's bookings."""
        with patch(
            "app.api.api_v1.endpoints.bookings.get_user_bookings",
            new_callable=AsyncMock,
        ) as mock_get:
            mock_get.return_value = ([], None, None)

            response = await authenticated_client.get("/api/v1/bookings/")

            assert response.status_code == 200
            data = response.json()
            assert "items" in data


class TestCancelBookingEndpoint:
    """Tests for POST /api/v1/bookings/cancel/ endpoint."""

    @pytest.mark.asyncio
    async def test_cancel_booking_success(self, authenticated_client: AsyncClient, test_user):
        """Test successful booking cancellation."""
        mock_booking = create_mock_booking(booking_id=42, user_id=test_user.id)

        with patch(
            "app.api.api_v1.endpoints.bookings.get_booking",
            new_callable=AsyncMock,
        ) as mock_get, patch(
            "app.api.api_v1.endpoints.bookings.cancel_booking",
            new_callable=AsyncMock,
        ) as mock_cancel:
            mock_get.return_value = mock_booking
            mock_cancel.return_value = True

            response = await authenticated_client.post(
                "/api/v1/bookings/cancel/",
                json={"booking_id": 42, "reason": "Change of plans"},
            )

            assert response.status_code == 200


class TestCheckAvailabilityEndpoint:
    """Tests for POST /api/v1/bookings/check-availability/ endpoint."""

    @pytest.mark.asyncio
    async def test_check_availability(self, client: AsyncClient):
        """Test checking property availability."""
        check_in = datetime.now(timezone.utc) + timedelta(days=7)
        check_out = check_in + timedelta(days=3)

        with patch(
            "app.api.api_v1.endpoints.bookings.check_availability",
            new_callable=AsyncMock,
        ) as mock_check:
            mock_check.return_value = {
                "available": True,
                "conflicts": [],
            }

            response = await client.post(
                "/api/v1/bookings/check-availability/",
                json={
                    "property_id": 123,
                    "check_in_date": check_in.isoformat(),
                    "check_out_date": check_out.isoformat(),
                    "guests": 2,
                },
            )

            assert response.status_code == 200
            data = response.json()
            assert "available" in data


class TestGetPricingEndpoint:
    """Tests for POST /api/v1/bookings/calculate-pricing/ endpoint."""

    @pytest.mark.asyncio
    async def test_get_pricing(self, client: AsyncClient):
        """Test getting booking pricing."""
        check_in = datetime.now(timezone.utc) + timedelta(days=7)
        check_out = check_in + timedelta(days=3)

        with patch(
            "app.api.api_v1.endpoints.bookings.calculate_pricing",
            new_callable=AsyncMock,
        ) as mock_price:
            mock_price.return_value = {
                "nights": 3,
                "base_amount": 6000,
                "taxes_amount": 1080,
                "service_charges": 300,
                "discount_amount": 0,
                "total_amount": 7380,
            }

            response = await client.post(
                "/api/v1/bookings/calculate-pricing/",
                json={
                    "property_id": 123,
                    "check_in_date": check_in.isoformat(),
                    "check_out_date": check_out.isoformat(),
                    "guests": 2,
                },
            )

            assert response.status_code == 200
            data = response.json()
            assert "total_amount" in data


class TestAddReviewEndpoint:
    """Tests for POST /api/v1/bookings/review/ endpoint."""

    @pytest.mark.asyncio
    async def test_add_review_success(self, authenticated_client: AsyncClient, test_user):
        """Test successful booking review submission with canonical guest_* fields."""
        mock_booking = create_mock_booking(booking_id=42, user_id=test_user.id)

        with patch(
            "app.api.api_v1.endpoints.bookings.get_booking",
            new_callable=AsyncMock,
        ) as mock_get, patch(
            "app.api.api_v1.endpoints.bookings.add_review",
            new_callable=AsyncMock,
        ) as mock_add_review:
            mock_get.return_value = mock_booking
            mock_add_review.return_value = True

            response = await authenticated_client.post(
                "/api/v1/bookings/review/",
                json={
                    "booking_id": 42,
                    "guest_rating": 5,
                    "guest_review": "Excellent stay",
                },
            )

            assert response.status_code == 200
            payload = response.json()
            assert payload["message"] == "Review added successfully"

            review_input = mock_add_review.await_args.args[1]
            assert review_input.booking_id == 42
            assert review_input.guest_rating == 5
            assert review_input.guest_review == "Excellent stay"

    @pytest.mark.asyncio
    async def test_add_review_rejects_legacy_fields(self, authenticated_client: AsyncClient):
        """Legacy rating/review keys must be rejected by schema validation."""
        response = await authenticated_client.post(
            "/api/v1/bookings/review/",
            json={
                "booking_id": 42,
                "rating": 5,
                "review": "Legacy payload",
            },
        )

        assert response.status_code == 422
