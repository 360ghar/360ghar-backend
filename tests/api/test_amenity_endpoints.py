"""
Tests for amenity endpoints.
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

NOW = datetime(2026, 10, 1, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _uncached_amenities():
    """Read amenities without the shared cache, so one test cannot leak rows into another."""
    import app.services.property as property_service
    from app.api.api_v1.endpoints import amenities as amenities_endpoint
    from app.schemas.amenity import Amenity

    async def _uncached(db):
        raw = await property_service.get_all_amenities(db)
        return [Amenity.model_validate(item) if isinstance(item, dict) else item for item in raw]

    with patch.object(amenities_endpoint, "get_amenities_cached", _uncached):
        yield


class TestListAmenitiesEndpoint:
    """Tests for GET /api/v1/amenities/ endpoint."""

    @pytest.mark.asyncio
    async def test_list_amenities(self, client: AsyncClient):
        """Test listing all amenities."""
        with patch(
            "app.services.property.get_all_amenities",
            new_callable=AsyncMock,
        ) as mock_get:
            mock_get.return_value = [
                {"id": 1, "title": "WiFi", "icon": "wifi", "created_at": NOW, "updated_at": NOW},
                {"id": 2, "title": "Parking", "icon": "car", "created_at": NOW, "updated_at": NOW},
                {"id": 3, "title": "Pool", "icon": "pool", "created_at": NOW, "updated_at": NOW},
            ]

            response = await client.get("/api/v1/amenities/")

            assert response.status_code == 200
            data = response.json()
            assert [item["title"] for item in data["items"]] == ["Parking", "Pool", "WiFi"]
            assert data["has_more"] is False

    @pytest.mark.asyncio
    async def test_list_amenities_empty(self, client: AsyncClient):
        """Test listing amenities when none exist."""
        with patch(
            "app.services.property.get_all_amenities",
            new_callable=AsyncMock,
        ) as mock_get:
            mock_get.return_value = []

            response = await client.get("/api/v1/amenities/")

            assert response.status_code == 200
            data = response.json()
            assert data["items"] == []
            assert data["next_cursor"] is None
