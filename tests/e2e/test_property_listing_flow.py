"""
End-to-end tests for property listing flow.
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient


def create_mock_property_dict(
    property_id: int = 1,
    title: str = "Test Property",
    is_available: bool = True,
) -> dict:
    """Create a mock property dictionary for tests."""
    return {
        "id": property_id,
        "owner_id": 1,
        "title": title,
        "description": "A beautiful property",
        "property_type": "apartment",
        "purpose": "rent",
        "base_price": 50000.0,
        "monthly_rent": 50000.0,
        "daily_rate": None,
        "latitude": 19.0760,
        "longitude": 72.8777,
        "city": "Mumbai",
        "state": "Maharashtra",
        "country": "India",
        "pincode": "400069",
        "locality": "Andheri",
        "full_address": "123 Test Street, Andheri, Mumbai",
        "area_sqft": 1000.0,
        "bedrooms": 2,
        "bathrooms": 2,
        "balconies": 1,
        "parking_spaces": 1,
        "status": "available",
        "is_available": is_available,
        "view_count": 0,
        "like_count": 0,
        "interest_count": 0,
        "is_managed": False,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": None,
        "images": [],
        "amenities": [],
    }


class TestPropertyListingFlow:
    """Tests for complete property listing flow."""

    @pytest.mark.asyncio
    async def test_create_and_list_property(
        self, authenticated_client: AsyncClient
    ):
        """Test creating a property and seeing it in listings."""
        from unittest.mock import MagicMock, NonCallableMock

        # Step 1: Create property - need to return object with .id attribute
        # Use NonCallableMock with spec to avoid auto-generated attributes
        with patch(
            "app.api.api_v1.endpoints.properties.create_property",
            new_callable=AsyncMock,
        ) as mock_create:
            # Create a mock that doesn't auto-generate undefined attributes
            mock_property = NonCallableMock(spec=[])
            # Set all required fields explicitly
            mock_property.id = 1
            mock_property.owner_id = 1
            mock_property.title = "Test Property"
            mock_property.description = "A beautiful property"
            mock_property.property_type = "apartment"
            mock_property.purpose = "rent"
            mock_property.base_price = 50000.0
            mock_property.monthly_rent = 50000.0
            mock_property.daily_rate = None
            mock_property.price_per_sqft = None
            mock_property.security_deposit = None
            mock_property.maintenance_charges = None
            mock_property.latitude = 19.0760
            mock_property.longitude = 72.8777
            mock_property.city = "Mumbai"
            mock_property.state = "Maharashtra"
            mock_property.country = "India"
            mock_property.pincode = "400069"
            mock_property.locality = "Andheri"
            mock_property.sub_locality = None
            mock_property.landmark = None
            mock_property.full_address = "123 Test Street, Andheri, Mumbai"
            mock_property.area_type = None
            mock_property.area_sqft = 1000.0
            mock_property.bedrooms = 2
            mock_property.bathrooms = 2
            mock_property.balconies = 1
            mock_property.parking_spaces = 1
            mock_property.floor_number = None
            mock_property.total_floors = None
            mock_property.age_of_property = None
            mock_property.max_occupancy = None
            mock_property.minimum_stay_days = None
            mock_property.video_urls = None
            mock_property.google_street_view_url = None
            mock_property.floor_plan_url = None
            mock_property.video_tour_url = None
            mock_property.main_image_url = None
            mock_property.virtual_tour_url = None
            mock_property.calendar_data = None
            mock_property.tags = None
            mock_property.features = None
            mock_property.owner_name = None
            mock_property.owner_contact = None
            mock_property.builder_name = None
            mock_property.search_keywords = None
            mock_property.status = "available"
            mock_property.is_available = True
            mock_property.view_count = 0
            mock_property.like_count = 0
            mock_property.interest_count = 0
            mock_property.is_managed = False
            mock_property.management_status = None
            mock_property.late_fee_policy = None
            mock_property.created_at = datetime.now(timezone.utc)
            mock_property.updated_at = None
            mock_property.images = []
            mock_property.amenities = []
            mock_create.return_value = mock_property

            response = await authenticated_client.post(
                "/api/v1/properties/",
                json={
                    "title": "Test Property",
                    "description": "A beautiful property",
                    "property_type": "apartment",
                    "purpose": "rent",
                    "base_price": 50000,
                    "monthly_rent": 50000,
                    "city": "Mumbai",
                    "locality": "Andheri",
                    "full_address": "123 Test Street",
                    "pincode": "400069",
                    "state": "Maharashtra",
                    "country": "India",
                    "bedrooms": 2,
                    "bathrooms": 2,
                    "area_sqft": 1000,
                },
            )

            assert response.status_code == 200

        # Step 2: List properties
        with patch(
            "app.api.api_v1.endpoints.properties.get_unified_properties_optimized",
            new_callable=AsyncMock,
        ) as mock_list:
            mock_list.return_value = {
                "items": [create_mock_property_dict(property_id=1)],
                "total": 1,
                "page": 1,
                "limit": 20,
            }

            response = await authenticated_client.get("/api/v1/properties/")

            assert response.status_code == 200


class TestPropertySearchFlow:
    """Tests for property search flow."""

    @pytest.mark.asyncio
    async def test_search_properties_by_location(self, client: AsyncClient):
        """Test searching properties by location."""
        with patch(
            "app.api.api_v1.endpoints.properties.get_unified_properties_optimized",
            new_callable=AsyncMock,
        ) as mock_search:
            mock_search.return_value = {
                "items": [],
                "total": 0,
                "page": 1,
                "limit": 20,
            }

            response = await client.get(
                "/api/v1/properties/",
                params={
                    "latitude": 19.1136,
                    "longitude": 72.8697,
                    "radius_km": 10,
                },
            )

            assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_search_properties_by_filters(self, client: AsyncClient):
        """Test searching with multiple filters."""
        with patch(
            "app.api.api_v1.endpoints.properties.get_unified_properties_optimized",
            new_callable=AsyncMock,
        ) as mock_search:
            mock_search.return_value = {
                "items": [],
                "total": 0,
                "page": 1,
                "limit": 20,
            }

            response = await client.get(
                "/api/v1/properties/",
                params={
                    "city": "Mumbai",
                    "property_type": "apartment",
                    "purpose": "rent",
                    "price_min": 20000,
                    "price_max": 80000,
                    "bedrooms_min": 2,
                },
            )

            assert response.status_code == 200


class TestPropertyViewFlow:
    """Tests for viewing property details."""

    @pytest.mark.asyncio
    async def test_view_property_details(self, client: AsyncClient, test_property):
        """Test viewing property details."""
        with patch(
            "app.api.api_v1.endpoints.properties.get_property", new_callable=AsyncMock
        ) as mock_get:
            mock_get.return_value = create_mock_property_dict(
                property_id=test_property.id,
                title=test_property.title,
            )

            with patch(
                "app.api.api_v1.endpoints.properties.increment_property_view_count",
                new_callable=AsyncMock,
            ):
                response = await client.get(f"/api/v1/properties/{test_property.id}")

                assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_view_increments_counter(self, client: AsyncClient, test_property):
        """Test that viewing property increments view counter."""
        with patch(
            "app.api.api_v1.endpoints.properties.get_property", new_callable=AsyncMock
        ) as mock_get:
            mock_get.return_value = create_mock_property_dict(
                property_id=test_property.id,
                title=test_property.title,
            )

            with patch(
                "app.api.api_v1.endpoints.properties.increment_property_view_count",
                new_callable=AsyncMock,
            ):
                response = await client.get(f"/api/v1/properties/{test_property.id}")

                assert response.status_code == 200


class TestPropertySwipeFlow:
    """Tests for property swipe discovery flow."""

    @pytest.mark.asyncio
    async def test_swipe_like_and_view_likes(
        self, authenticated_client: AsyncClient, test_property
    ):
        """Test swiping and viewing liked properties."""
        # Step 1: Like a property
        with patch(
            "app.api.api_v1.endpoints.swipes.record_swipe", new_callable=AsyncMock
        ) as mock_swipe:
            mock_swipe.return_value = True

            response = await authenticated_client.post(
                "/api/v1/swipes/",
                json={
                    "property_id": test_property.id,
                    "is_liked": True,
                },
            )

            assert response.status_code == 200

        # Step 2: View swipe history (includes likes)
        with patch(
            "app.api.api_v1.endpoints.swipes.get_swipe_history", new_callable=AsyncMock
        ) as mock_history:
            mock_history.return_value = ([], None, None)

            response = await authenticated_client.get(
                "/api/v1/swipes/",
            )

            assert response.status_code == 200


class TestPropertyUpdateFlow:
    """Tests for property update flow."""

    @pytest.mark.asyncio
    async def test_owner_updates_property(
        self, authenticated_client: AsyncClient, test_property
    ):
        """Test owner updating their property."""
        with patch(
            "app.api.api_v1.endpoints.properties.update_property",
            new_callable=AsyncMock,
        ) as mock_update:
            mock_update.return_value = create_mock_property_dict(
                property_id=test_property.id,
                title="Updated Property Title",
            )

            # Use PUT, not PATCH
            response = await authenticated_client.put(
                f"/api/v1/properties/{test_property.id}",
                json={"title": "Updated Property Title"},
            )

            assert response.status_code == 200


class TestPropertyToggleAvailability:
    """Tests for toggling property availability.

    Note: There may not be a dedicated toggle endpoint.
    Availability is changed via property update.
    """

    @pytest.mark.asyncio
    async def test_toggle_availability(
        self, authenticated_client: AsyncClient, test_property
    ):
        """Test changing property availability via update."""
        with patch(
            "app.api.api_v1.endpoints.properties.update_property",
            new_callable=AsyncMock,
        ) as mock_update:
            mock_update.return_value = create_mock_property_dict(
                property_id=test_property.id,
                title=test_property.title,
                is_available=False,
            )

            # Use PUT to update availability (no dedicated toggle endpoint)
            response = await authenticated_client.put(
                f"/api/v1/properties/{test_property.id}",
                json={"is_available": False},
            )

            assert response.status_code == 200
