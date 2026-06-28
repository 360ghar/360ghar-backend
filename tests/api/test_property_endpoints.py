"""
Tests for property API endpoints.

These tests verify the property-related API endpoints work correctly.
They mock the service layer to isolate endpoint testing.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy.exc import SQLAlchemyError

from app.models.enums import (
    ListingGenderPreference,
    ListingSharingType,
    PropertyPurpose,
    PropertyStatus,
    PropertyType,
)
from app.schemas.property import Property


def create_mock_property(
    property_id: int = 1,
    title: str = "Test Property",
    property_type: PropertyType = PropertyType.apartment,
    purpose: PropertyPurpose = PropertyPurpose.rent,
) -> Property:
    """Create a mock property schema object."""
    return Property(
        id=property_id,
        owner_id=1,
        title=title,
        description="A test property description",
        property_type=property_type,
        purpose=purpose,
        base_price=50000.0,
        monthly_rent=50000.0,
        latitude=19.0760,
        longitude=72.8777,
        city="Mumbai",
        state="Maharashtra",
        country="India",
        pincode="400001",
        locality="Andheri",
        full_address="123 Test Street, Andheri, Mumbai",
        area_sqft=1000.0,
        bedrooms=2,
        bathrooms=2,
        balconies=1,
        parking_spaces=1,
        listing_preferences=None,
        status=PropertyStatus.available,
        is_available=True,
        view_count=0,
        like_count=0,
        interest_count=0,
        is_managed=False,
        created_at=datetime.now(timezone.utc),
        updated_at=None,
        images=None,
        amenities=None,
    )


class TestCreateProperty:
    """Tests for POST /api/v1/properties/."""

    @pytest.mark.asyncio
    async def test_create_property_success(self, authenticated_client: AsyncClient):
        """Test successful property creation."""
        with patch(
            "app.api.api_v1.endpoints.properties.create_property",
            new_callable=AsyncMock,
        ) as mock_create:
            mock_create.return_value = create_mock_property(
                property_id=1,
                title="Test Property",
                property_type=PropertyType.apartment,
                purpose=PropertyPurpose.rent,
            )

            response = await authenticated_client.post(
                "/api/v1/properties/",
                json={
                    "title": "Test Property",
                    "description": "A test property",
                    "property_type": "apartment",
                    "purpose": "rent",
                    "base_price": 50000,
                    "monthly_rent": 50000,
                    "city": "Mumbai",
                    "locality": "Andheri",
                    "full_address": "123 Test Street",
                    "bedrooms": 2,
                    "bathrooms": 2,
                    "area_sqft": 1000,
                },
            )

            assert response.status_code == 200
            data = response.json()
            assert data["title"] == "Test Property"

    @pytest.mark.asyncio
    async def test_create_pg_property_rejects_non_rent_purpose(
        self,
        authenticated_client: AsyncClient,
    ):
        """Test PG body validation rejects non-rent purposes."""
        response = await authenticated_client.post(
            "/api/v1/properties/",
            json={
                "title": "Invalid PG Listing",
                "property_type": "pg",
                "purpose": "buy",
                "base_price": 18000,
            },
        )

        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_create_property_unauthenticated(self, client: AsyncClient):
        """Test property creation requires authentication."""
        response = await client.post(
            "/api/v1/properties/",
            json={
                "title": "Test Property",
                "property_type": "apartment",
                "purpose": "rent",
                "base_price": 50000,
            },
        )

        # Should require auth
        assert response.status_code == 401


class TestListProperties:
    """Tests for GET /api/v1/properties/."""

    @pytest.mark.asyncio
    async def test_list_properties_public(self, client: AsyncClient):
        """Test property listing is publicly accessible."""
        with patch(
            "app.api.api_v1.endpoints.properties.get_unified_properties_optimized",
            new_callable=AsyncMock,
        ) as mock_list:
            mock_list.return_value = ([], None, 0)

            response = await client.get("/api/v1/properties/")

            # Should be accessible without auth
            assert response.status_code == 200
            data = response.json()
            assert "items" in data
            assert "has_more" in data

    @pytest.mark.asyncio
    async def test_list_properties_with_filters(self, client: AsyncClient):
        """Test property listing with query filters."""
        with patch(
            "app.api.api_v1.endpoints.properties.get_unified_properties_optimized",
            new_callable=AsyncMock,
        ) as mock_list:
            mock_list.return_value = ([], None, 0)

            response = await client.get(
                "/api/v1/properties/",
                params={
                    "city": "Mumbai",
                    "purpose": "rent",
                    "price_min": 10000,
                    "price_max": 100000,
                    "bedrooms_min": 1,
                },
            )

            assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_list_properties_with_location(self, client: AsyncClient):
        """Test property listing with location-based search."""
        with patch(
            "app.api.api_v1.endpoints.properties.get_unified_properties_optimized",
            new_callable=AsyncMock,
        ) as mock_list:
            mock_list.return_value = ([], None, 0)

            response = await client.get(
                "/api/v1/properties/",
                params={
                    "lat": 19.0760,
                    "lng": 72.8777,
                    "radius": 10,
                },
            )

            assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_list_properties_with_ids_filter(self, client: AsyncClient):
        """Test property listing with repeated ids query params."""
        with patch(
            "app.api.api_v1.endpoints.properties.get_unified_properties_optimized",
            new_callable=AsyncMock,
        ) as mock_list:
            mock_list.return_value = ([], None, 0)

            response = await client.get(
                "/api/v1/properties",
                params=[("ids", "1"), ("ids", "2"), ("ids", "5")],
            )

            assert response.status_code == 200
            filters = mock_list.await_args.args[1]
            assert filters.property_ids == [1, 2, 5]

    @pytest.mark.asyncio
    async def test_list_properties_with_listing_preference_filters(
        self,
        client: AsyncClient,
    ):
        """Test property listing parses specialized listing filters."""
        with patch(
            "app.api.api_v1.endpoints.properties.get_unified_properties_optimized",
            new_callable=AsyncMock,
        ) as mock_list:
            mock_list.return_value = ([], None, 0)

            response = await client.get(
                "/api/v1/properties",
                params=[
                    ("property_type", "flatmate"),
                    ("gender_preference", "female"),
                    ("sharing_type", "shared_room"),
                ],
            )

            assert response.status_code == 200
            filters = mock_list.await_args.args[1]
            assert filters.property_type == [PropertyType.flatmate]
            assert filters.gender_preference == ListingGenderPreference.female
            assert filters.sharing_type == ListingSharingType.shared_room

    @pytest.mark.asyncio
    async def test_list_properties_returns_503_for_transient_db_error(self, client: AsyncClient):
        """Transient DB failures should map to 503."""
        with patch(
            "app.api.api_v1.endpoints.properties.get_unified_properties_optimized",
            new_callable=AsyncMock,
        ) as mock_list:
            mock_list.side_effect = SQLAlchemyError(
                "(ECHECKOUTTIMEOUT) unable to check out connection from the pool"
            )

            response = await client.get("/api/v1/properties/")

            assert response.status_code == 503


class TestRecommendations:
    @pytest.mark.asyncio
    async def test_recommendations_returns_503_for_transient_db_error(
        self, client: AsyncClient
    ):
        with patch(
            "app.api.api_v1.endpoints.properties.get_property_recommendations",
            new_callable=AsyncMock,
        ) as mock_reco:
            mock_reco.side_effect = SQLAlchemyError(
                "(EDBHANDLEREXITED) connection to database closed"
            )

            response = await client.get("/api/v1/properties/recommendations")

            assert response.status_code == 503


class TestGetProperty:
    """Tests for GET /api/v1/properties/{property_id}."""

    @pytest.mark.asyncio
    async def test_get_property_success(self, client: AsyncClient):
        """Test getting property by ID."""
        with patch(
            "app.api.api_v1.endpoints.properties.get_property",
            new_callable=AsyncMock,
        ) as mock_get, patch(
            "app.api.api_v1.endpoints.properties.increment_property_view_count",
            new_callable=AsyncMock,
        ):
            mock_get.return_value = create_mock_property(property_id=1)

            response = await client.get("/api/v1/properties/1")

            assert response.status_code == 200
            data = response.json()
            assert data["id"] == 1
            assert data["title"] == "Test Property"

    @pytest.mark.asyncio
    async def test_get_property_not_found(self, client: AsyncClient):
        """Test getting non-existent property returns 404."""
        from fastapi import HTTPException

        with patch(
            "app.api.api_v1.endpoints.properties.get_property",
            new_callable=AsyncMock,
        ) as mock_get, patch(
            "app.api.api_v1.endpoints.properties.increment_property_view_count",
            new_callable=AsyncMock,
        ):
            # Simulate not found by raising HTTPException
            mock_get.side_effect = HTTPException(status_code=404, detail="Property not found")

            response = await client.get("/api/v1/properties/99999")

            assert response.status_code == 404


class TestUpdateProperty:
    """Tests for PUT /api/v1/properties/{property_id}."""

    @pytest.mark.asyncio
    async def test_update_property_success(self, authenticated_client: AsyncClient):
        """Test successful property update."""
        with patch(
            "app.api.api_v1.endpoints.properties.update_property",
            new_callable=AsyncMock,
        ) as mock_update:
            mock_update.return_value = create_mock_property(
                property_id=1,
                title="Updated Title",
            )

            response = await authenticated_client.put(
                "/api/v1/properties/1",
                json={"title": "Updated Title"},
            )

            assert response.status_code == 200
            data = response.json()
            assert data["title"] == "Updated Title"

    @pytest.mark.asyncio
    async def test_update_property_unauthenticated(self, client: AsyncClient):
        """Test property update requires authentication."""
        response = await client.put(
            "/api/v1/properties/1",
            json={"title": "Updated Title"},
        )

        assert response.status_code == 401


class TestDeleteProperty:
    """Tests for DELETE /api/v1/properties/{property_id}/."""

    @pytest.mark.asyncio
    async def test_delete_property_success(self, authenticated_client: AsyncClient):
        """Test successful property deletion."""
        with patch(
            "app.api.api_v1.endpoints.properties.delete_property",
            new_callable=AsyncMock,
        ) as mock_delete:
            mock_delete.return_value = True

            response = await authenticated_client.delete("/api/v1/properties/1/")

            assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_delete_property_unauthenticated(self, client: AsyncClient):
        """Test property deletion requires authentication."""
        response = await client.delete("/api/v1/properties/1/")

        assert response.status_code == 401


class TestPropertyFilters:
    """Tests for property filter validation."""

    @pytest.mark.asyncio
    async def test_invalid_radius(self, client: AsyncClient):
        """Test invalid radius is rejected."""
        response = await client.get(
            "/api/v1/properties/",
            params={"radius": 200},  # Max is 100
        )

        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_invalid_price_range(self, client: AsyncClient):
        """Test negative price is rejected."""
        response = await client.get(
            "/api/v1/properties/",
            params={"price_min": -1000},
        )

        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_valid_property_type_filter(self, client: AsyncClient):
        """Test valid property type filter."""
        with patch(
            "app.api.api_v1.endpoints.properties.get_unified_properties_optimized",
            new_callable=AsyncMock,
        ) as mock_list:
            mock_list.return_value = ([], None, 0)

            response = await client.get(
                "/api/v1/properties/",
                params={"property_type": ["apartment", "house"]},
            )

            assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_valid_expanded_property_type_filter(self, client: AsyncClient):
        """Test expanded property type filter values."""
        with patch(
            "app.api.api_v1.endpoints.properties.get_unified_properties_optimized",
            new_callable=AsyncMock,
        ) as mock_list:
            mock_list.return_value = ([], None, 0)

            response = await client.get(
                "/api/v1/properties/",
                params=[("property_type", "condo"), ("property_type", "studio")],
            )

            assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_valid_purpose_filter(self, client: AsyncClient):
        """Test valid purpose filter."""
        with patch(
            "app.api.api_v1.endpoints.properties.get_unified_properties_optimized",
            new_callable=AsyncMock,
        ) as mock_list:
            mock_list.return_value = ([], None, 0)

            response = await client.get(
                "/api/v1/properties/",
                params={"purpose": "rent"},
            )

            assert response.status_code == 200


class TestPropertyRecommendations:
    """Tests for property recommendations endpoint."""

    @pytest.mark.asyncio
    async def test_recommendations_endpoint(self, client: AsyncClient):
        """Test recommendations endpoint exists."""
        with patch(
            "app.api.api_v1.endpoints.properties.get_property_recommendations",
            new_callable=AsyncMock,
        ) as mock_rec:
            mock_rec.return_value = ([], None, None)

            response = await client.get("/api/v1/properties/recommendations/")

            assert response.status_code == 200


class TestMyProperties:
    """Tests for GET /api/v1/properties/me/."""

    @pytest.mark.asyncio
    async def test_my_properties_success(self, authenticated_client: AsyncClient):
        """Test getting user's own properties."""
        with patch(
            "app.api.api_v1.endpoints.properties.list_user_properties",
            new_callable=AsyncMock,
        ) as mock_list:
            mock_list.return_value = ([create_mock_property(property_id=1)], None, 1)

            response = await authenticated_client.get("/api/v1/properties/me/")

            assert response.status_code == 200
            data = response.json()
            assert len(data["items"]) == 1

    @pytest.mark.asyncio
    async def test_my_properties_requires_auth(self, client: AsyncClient):
        """Test my properties requires authentication."""
        response = await client.get("/api/v1/properties/me/")

        assert response.status_code == 401
