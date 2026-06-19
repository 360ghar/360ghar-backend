"""Tests for swipe batch-remove endpoint."""

from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient


class TestBatchRemoveSwipesEndpoint:
    """Tests for POST /api/v1/swipes/batch-remove/ endpoint."""

    @pytest.mark.asyncio
    async def test_batch_remove_success(self, authenticated_client: AsyncClient):
        with patch(
            "app.api.api_v1.endpoints.swipes.batch_unswipe",
            new_callable=AsyncMock,
        ) as mock_batch:
            mock_batch.return_value = 3

            response = await authenticated_client.post(
                "/api/v1/swipes/batch-remove",
                json={"property_ids": [1, 2, 3]},
            )

            assert response.status_code == 200
            data = response.json()
            assert "message" in data
            assert "3" in data["message"]
            mock_batch.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_batch_remove_empty_list(self, authenticated_client: AsyncClient):
        with patch(
            "app.api.api_v1.endpoints.swipes.batch_unswipe",
            new_callable=AsyncMock,
        ) as mock_batch:
            mock_batch.return_value = 0

            response = await authenticated_client.post(
                "/api/v1/swipes/batch-remove",
                json={"property_ids": []},
            )

            assert response.status_code == 200
            assert "0" in response.json()["message"]

    @pytest.mark.asyncio
    async def test_batch_remove_unauthorized(self, client: AsyncClient):
        response = await client.post(
            "/api/v1/swipes/batch-remove",
            json={"property_ids": [1, 2]},
        )
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_batch_remove_missing_payload(self, authenticated_client: AsyncClient):
        response = await authenticated_client.post(
            "/api/v1/swipes/batch-remove",
            json={},
        )
        assert response.status_code == 422
