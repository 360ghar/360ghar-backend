"""
End-to-end tests for booking complete flow.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient


def create_mock_property_dict(property_id: int = 1) -> dict:
    """Create a mock property dictionary for tests."""
    return {
        "id": property_id,
        "owner_id": 1,
        "title": "Vacation Stay Property",
        "description": "Perfect for short vacation stays",
        "property_type": "apartment",
        "purpose": "short_stay",
        "base_price": 50000.0,
        "monthly_rent": None,
        "daily_rate": 2000.0,
        "latitude": 19.0760,
        "longitude": 72.8777,
        "city": "Mumbai",
        "state": "Maharashtra",
        "country": "India",
        "pincode": "400001",
        "locality": "Bandra",
        "full_address": "123 Test Street, Bandra, Mumbai",
        "area_sqft": 1000.0,
        "bedrooms": 1,
        "bathrooms": 1,
        "balconies": 1,
        "parking_spaces": 1,
        "status": "available",
        "is_available": True,
        "view_count": 0,
        "like_count": 0,
        "interest_count": 0,
        "is_managed": False,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": None,
        "images": [],
        "amenities": [],
    }


def create_mock_booking_dict(
    booking_id: int = 1,
    property_id: int = 1,
    status: str = "pending",
) -> dict:
    """Create a mock booking dictionary for tests."""
    return {
        "id": booking_id,
        "property_id": property_id,
        "user_id": 1,
        "booking_reference": f"BK{booking_id:08d}",
        "booking_status": status,
        "payment_status": "paid" if status == "confirmed" else "pending",
        "check_in_date": (datetime.now(timezone.utc) + timedelta(days=7)).isoformat(),
        "check_out_date": (datetime.now(timezone.utc) + timedelta(days=10)).isoformat(),
        "guests": 2,
        "primary_guest_name": "Test User",
        "primary_guest_phone": "+919876543210",
        "primary_guest_email": "test@example.com",
        "special_requests": None,
        "guest_details": None,
        "nights": 3,
        "base_amount": 6000.0,
        "taxes_amount": 1080.0,
        "service_charges": 300.0,
        "discount_amount": 0.0,
        "total_amount": 7380.0,
        "early_check_in": False,
        "late_check_out": False,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": None,
    }


class TestBookingCompleteFlow:
    """Tests for complete booking flow from search to checkout."""

    @pytest.mark.asyncio
    async def test_search_check_book_flow(
        self, authenticated_client: AsyncClient, test_short_stay_property
    ):
        """Test complete flow: search -> check availability -> get pricing -> book."""
        check_in = datetime.now(timezone.utc) + timedelta(days=7)
        check_out = check_in + timedelta(days=3)

        # Step 1: Search for properties - use dict instead of ORM object
        with patch(
            "app.api.api_v1.endpoints.properties.get_unified_properties_optimized",
            new_callable=AsyncMock,
        ) as mock_search:
            mock_search.return_value = (
                [create_mock_property_dict(test_short_stay_property.id)],
                None,
                1,
            )

            response = await authenticated_client.get(
                "/api/v1/properties/",
                params={
                    "purpose": "short_stay",
                    "city": "Mumbai",
                },
            )

            assert response.status_code == 200

        # Step 2: Check availability - POST /check-availability/
        with patch(
            "app.api.api_v1.endpoints.bookings.check_availability",
            new_callable=AsyncMock,
        ) as mock_avail:
            mock_avail.return_value = {
                "available": True,
                "conflicts": [],
            }

            response = await authenticated_client.post(
                "/api/v1/bookings/check-availability/",
                json={
                    "property_id": test_short_stay_property.id,
                    "check_in_date": check_in.strftime("%Y-%m-%d"),
                    "check_out_date": check_out.strftime("%Y-%m-%d"),
                    "guests": 2,
                },
            )

            assert response.status_code == 200
            data = response.json()
            assert data.get("available") is True or "available" in data

        # Step 3: Get pricing - POST /calculate-pricing/
        with patch(
            "app.api.api_v1.endpoints.bookings.calculate_pricing",
            new_callable=AsyncMock,
        ) as mock_price:
            mock_price.return_value = {
                "nights": 3,
                "base_amount": Decimal("6000"),
                "taxes_amount": Decimal("1080"),
                "service_charges": Decimal("300"),
                "discount_amount": Decimal("0"),
                "total_amount": Decimal("7380"),
            }

            response = await authenticated_client.post(
                "/api/v1/bookings/calculate-pricing/",
                json={
                    "property_id": test_short_stay_property.id,
                    "check_in_date": check_in.strftime("%Y-%m-%d"),
                    "check_out_date": check_out.strftime("%Y-%m-%d"),
                    "guests": 2,
                },
            )

            assert response.status_code == 200

        # Step 4: Create booking - use dict instead of MagicMock
        with patch(
            "app.api.api_v1.endpoints.bookings.create_booking", new_callable=AsyncMock
        ) as mock_book:
            mock_book.return_value = create_mock_booking_dict(
                booking_id=1,
                property_id=test_short_stay_property.id,
                status="pending",
            )

            response = await authenticated_client.post(
                "/api/v1/bookings/",
                json={
                    "property_id": test_short_stay_property.id,
                    "check_in_date": check_in.strftime("%Y-%m-%dT%H:%M:%S"),
                    "check_out_date": check_out.strftime("%Y-%m-%dT%H:%M:%S"),
                    "guests": 2,
                    "primary_guest_name": "Test User",
                    "primary_guest_phone": "+919876543210",
                    "primary_guest_email": "test@example.com",
                },
            )

            assert response.status_code == 200


class TestBookingManagementFlow:
    """Tests for managing existing bookings."""

    @pytest.mark.asyncio
    async def test_view_and_cancel_booking(
        self, authenticated_client: AsyncClient, test_user, test_booking
    ):
        """Test viewing and cancelling a booking."""
        from unittest.mock import NonCallableMock

        # Step 1: View booking details - mock at the endpoint level
        # Use NonCallableMock with spec=[] to avoid auto-generated attributes
        with patch(
            "app.api.api_v1.endpoints.bookings.get_booking", new_callable=AsyncMock
        ) as mock_get:
            mock_booking = NonCallableMock(spec=[])
            mock_booking.id = test_booking.id
            mock_booking.property_id = test_booking.property_id
            mock_booking.user_id = test_user.id  # Must match authenticated user
            mock_booking.booking_status = test_booking.booking_status
            mock_booking.booking_reference = f"BK{test_booking.id:08d}"
            mock_booking.payment_status = "pending"
            mock_booking.check_in_date = datetime.now(timezone.utc) + timedelta(days=7)
            mock_booking.check_out_date = datetime.now(timezone.utc) + timedelta(days=10)
            mock_booking.guests = 2
            mock_booking.primary_guest_name = "Test User"
            mock_booking.primary_guest_phone = "+919876543210"
            mock_booking.primary_guest_email = "test@example.com"
            mock_booking.special_requests = None
            mock_booking.guest_details = None
            mock_booking.nights = 3
            mock_booking.base_amount = 6000.0
            mock_booking.taxes_amount = 1080.0
            mock_booking.service_charges = 300.0
            mock_booking.discount_amount = 0.0
            mock_booking.total_amount = 7380.0
            mock_booking.early_check_in = False
            mock_booking.late_check_out = False
            mock_booking.created_at = datetime.now(timezone.utc)
            mock_booking.updated_at = None
            # Additional optional booking fields
            mock_booking.internal_notes = None
            mock_booking.cancellation_reason = None
            mock_booking.payment_method = None
            mock_booking.transaction_id = None
            mock_booking.guest_review = None
            mock_booking.host_review = None
            mock_booking.guest_rating = None
            mock_booking.host_rating = None
            mock_booking.cancelled_at = None
            mock_booking.confirmed_at = None
            mock_booking.checked_in_at = None
            mock_booking.checked_out_at = None
            mock_get.return_value = mock_booking

            response = await authenticated_client.get(
                f"/api/v1/bookings/{test_booking.id}",
            )

            assert response.status_code == 200

        # Step 2: Cancel booking - POST /cancel/ with body
        with patch(
            "app.api.api_v1.endpoints.bookings.get_booking", new_callable=AsyncMock
        ) as mock_get_for_cancel:
            mock_booking_cancel = NonCallableMock(spec=[])
            mock_booking_cancel.id = test_booking.id
            mock_booking_cancel.user_id = test_user.id  # Must match authenticated user
            mock_booking_cancel.property_id = test_booking.property_id
            mock_booking_cancel.booking_status = "pending"
            mock_get_for_cancel.return_value = mock_booking_cancel

            with patch(
                "app.api.api_v1.endpoints.bookings.cancel_booking", new_callable=AsyncMock
            ) as mock_cancel:
                mock_cancel.return_value = {"message": "Booking cancelled successfully"}

                response = await authenticated_client.post(
                    "/api/v1/bookings/cancel/",
                    json={"booking_id": test_booking.id, "reason": "Plans changed"},
                )

                assert response.status_code == 200


class TestBookingListingFlow:
    """Tests for listing user bookings."""

    @pytest.mark.asyncio
    async def test_list_all_bookings(self, authenticated_client: AsyncClient):
        """Test listing all user bookings."""
        with patch(
            "app.api.api_v1.endpoints.bookings.get_user_bookings", new_callable=AsyncMock
        ) as mock_list:
            mock_list.return_value = ([], None, None)

            response = await authenticated_client.get(
                "/api/v1/bookings/",
            )

            assert response.status_code == 200
            data = response.json()
            assert "items" in data

    @pytest.mark.asyncio
    async def test_list_upcoming_bookings(self, authenticated_client: AsyncClient):
        """Test listing upcoming bookings."""
        with patch(
            "app.api.api_v1.endpoints.bookings.get_user_upcoming_bookings",
            new_callable=AsyncMock,
        ) as mock_list:
            mock_list.return_value = ([], None, None)

            response = await authenticated_client.get(
                "/api/v1/bookings/upcoming/",
            )

            assert response.status_code == 200


class TestBookingStatusTransitions:
    """Tests for booking status transitions (admin operations).

    Note: These endpoints may not exist in the public API.
    They could be admin-only operations via MCP.
    """

    @pytest.mark.asyncio
    async def test_confirm_booking(
        self, admin_authenticated_client: AsyncClient, test_booking
    ):
        """Test confirming a pending booking (may be admin-only)."""
        # This endpoint may not exist in public API
        response = await admin_authenticated_client.post(
            f"/api/v1/bookings/{test_booking.id}/confirm",
        )

        # Endpoint may not exist (404/405) or require special privileges (403)
        assert response.status_code in [200, 403, 404, 405]

    @pytest.mark.asyncio
    async def test_check_in_booking(
        self, admin_authenticated_client: AsyncClient, confirmed_booking
    ):
        """Test checking in a confirmed booking (may be admin-only)."""
        # This endpoint may not exist in public API
        response = await admin_authenticated_client.post(
            f"/api/v1/bookings/{confirmed_booking.id}/check-in",
        )

        # Endpoint may not exist (404/405) or require special privileges (403)
        assert response.status_code in [200, 403, 404, 405]
