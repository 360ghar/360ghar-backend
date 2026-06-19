"""
Tests for swipe endpoints.

These tests verify the swipe-related API endpoints work correctly.
They mock the service layer to isolate endpoint testing.
"""

from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient


class TestRecordSwipeEndpoint:
    """Tests for POST /api/v1/swipes/ endpoint."""

    @pytest.mark.asyncio
    async def test_record_swipe_like(self, authenticated_client: AsyncClient):
        """Test recording a like swipe."""
        with patch(
            "app.api.api_v1.endpoints.swipes.record_swipe",
            new_callable=AsyncMock,
        ) as mock_swipe:
            mock_swipe.return_value = True

            response = await authenticated_client.post(
                "/api/v1/swipes/",
                json={
                    "property_id": 1,
                    "is_liked": True,
                },
            )

            assert response.status_code == 200
            data = response.json()
            assert "message" in data

    @pytest.mark.asyncio
    async def test_record_swipe_dislike(self, authenticated_client: AsyncClient):
        """Test recording a dislike swipe."""
        with patch(
            "app.api.api_v1.endpoints.swipes.record_swipe",
            new_callable=AsyncMock,
        ) as mock_swipe:
            mock_swipe.return_value = True

            response = await authenticated_client.post(
                "/api/v1/swipes/",
                json={
                    "property_id": 1,
                    "is_liked": False,
                },
            )

            assert response.status_code == 200
            data = response.json()
            assert "message" in data

    @pytest.mark.asyncio
    async def test_record_swipe_unauthorized(self, client: AsyncClient):
        """Test swipe without auth."""
        response = await client.post(
            "/api/v1/swipes/",
            json={
                "property_id": 1,
                "is_liked": True,
            },
        )

        assert response.status_code == 401


class TestGetSwipeHistoryEndpoint:
    """Tests for GET /api/v1/swipes/ endpoint."""

    @pytest.mark.asyncio
    async def test_get_swipe_history(self, authenticated_client: AsyncClient):
        """Test getting swipe history."""
        with patch(
            "app.api.api_v1.endpoints.swipes.get_swipe_history",
            new_callable=AsyncMock,
        ) as mock_history:
            mock_history.return_value = ([], None, None)

            response = await authenticated_client.get("/api/v1/swipes/")

            assert response.status_code == 200
            data = response.json()
            assert "items" in data
            assert "has_more" in data

    @pytest.mark.asyncio
    async def test_get_swipe_history_liked_only(self, authenticated_client: AsyncClient):
        """Test getting only liked swipes."""
        with patch(
            "app.api.api_v1.endpoints.swipes.get_swipe_history",
            new_callable=AsyncMock,
        ) as mock_history:
            mock_history.return_value = ([], None, None)

            response = await authenticated_client.get(
                "/api/v1/swipes/",
                params={"is_liked": "true"},
            )

            assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_get_swipe_history_unauthorized(self, client: AsyncClient):
        """Test swipe history requires auth."""
        response = await client.get("/api/v1/swipes/")

        assert response.status_code == 401


class TestUndoSwipeEndpoint:
    """Tests for DELETE /api/v1/swipes/undo/ endpoint."""

    @pytest.mark.asyncio
    async def test_undo_last_swipe(self, authenticated_client: AsyncClient):
        """Test undoing last swipe."""
        with patch(
            "app.api.api_v1.endpoints.swipes.undo_last_swipe",
            new_callable=AsyncMock,
        ) as mock_undo:
            # Return a truthy value to indicate success
            mock_undo.return_value = {"id": 1, "property_id": 1}

            response = await authenticated_client.delete("/api/v1/swipes/undo/")

            assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_undo_swipe_no_swipes(self, authenticated_client: AsyncClient):
        """Test undoing when no swipes exist."""
        with patch(
            "app.api.api_v1.endpoints.swipes.undo_last_swipe",
            new_callable=AsyncMock,
        ) as mock_undo:
            mock_undo.return_value = None

            response = await authenticated_client.delete("/api/v1/swipes/undo/")

            assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_undo_swipe_unauthorized(self, client: AsyncClient):
        """Test undo swipe requires auth."""
        response = await client.delete("/api/v1/swipes/undo/")

        assert response.status_code == 401


class TestToggleSwipeEndpoint:
    """Tests for PUT /api/v1/swipes/{swipe_id}/toggle/ endpoint."""

    @pytest.mark.asyncio
    async def test_toggle_swipe_success(self, authenticated_client: AsyncClient):
        """Test toggling swipe status."""
        with patch(
            "app.api.api_v1.endpoints.swipes.toggle_swipe",
            new_callable=AsyncMock,
        ) as mock_toggle:
            mock_toggle.return_value = {"new_status": True, "property_id": 1}

            response = await authenticated_client.put("/api/v1/swipes/1/toggle/")

            assert response.status_code == 200
            data = response.json()
            assert "message" in data

    @pytest.mark.asyncio
    async def test_toggle_swipe_not_found(self, authenticated_client: AsyncClient):
        """Test toggling non-existent swipe."""
        with patch(
            "app.api.api_v1.endpoints.swipes.toggle_swipe",
            new_callable=AsyncMock,
        ) as mock_toggle:
            mock_toggle.return_value = None

            response = await authenticated_client.put("/api/v1/swipes/99999/toggle/")

            assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_toggle_swipe_unauthorized(self, client: AsyncClient):
        """Test toggle swipe requires auth."""
        response = await client.put("/api/v1/swipes/1/toggle/")

        assert response.status_code == 401


class TestGetSwipeStatsEndpoint:
    """Tests for GET /api/v1/swipes/stats/ endpoint."""

    @pytest.mark.asyncio
    async def test_get_swipe_stats(self, authenticated_client: AsyncClient):
        """Test getting swipe statistics."""
        with patch(
            "app.api.api_v1.endpoints.swipes.get_swipe_stats",
            new_callable=AsyncMock,
        ) as mock_stats:
            mock_stats.return_value = {
                "total_swipes": 100,
                "liked_count": 60,
                "disliked_count": 40,
                "like_percentage": 60.0,
            }

            response = await authenticated_client.get("/api/v1/swipes/stats/")

            assert response.status_code == 200
            data = response.json()
            assert "total_swipes" in data
            assert "like_percentage" in data

    @pytest.mark.asyncio
    async def test_get_swipe_stats_unauthorized(self, client: AsyncClient):
        """Test swipe stats requires auth."""
        response = await client.get("/api/v1/swipes/stats/")

        assert response.status_code == 401
