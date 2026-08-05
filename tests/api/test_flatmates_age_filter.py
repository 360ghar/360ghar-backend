"""API tests for the flatmates discover age filters.

Note: these tests use the authenticated_client fixture which needs a local
Postgres (localhost:5432) — in environments without the DB they are collected
but error at setup, matching the rest of tests/api/.
"""

from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient


class TestFlatmatesDiscoverAgeFilter:
    @pytest.mark.asyncio
    async def test_age_range_params_forwarded_to_service(self, authenticated_client: AsyncClient):
        with patch(
            "app.api.api_v1.endpoints.flatmates.list_discoverable_profiles",
            new_callable=AsyncMock,
        ) as mock_list:
            mock_list.return_value = ([], None, None)

            response = await authenticated_client.get(
                "/api/v1/flatmates/profiles",
                params={"age_min": 25, "age_max": 30},
            )

            assert response.status_code == 200
            kwargs = mock_list.await_args.kwargs
            assert kwargs["age_min"] == 25
            assert kwargs["age_max"] == 30

    @pytest.mark.asyncio
    async def test_inverted_age_range_rejected_with_invalid_age_range(
        self, authenticated_client: AsyncClient
    ):
        response = await authenticated_client.get(
            "/api/v1/flatmates/profiles",
            params={"age_min": 30, "age_max": 25},
        )

        assert response.status_code == 400
        data = response.json()
        assert data["error"]["code"] == "INVALID_AGE_RANGE"

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "params",
        [
            {"age_min": 17},
            {"age_min": 101},
            {"age_max": 17},
            {"age_max": 101},
        ],
    )
    async def test_out_of_bounds_age_rejected_with_422(
        self, authenticated_client: AsyncClient, params: dict
    ):
        response = await authenticated_client.get(
            "/api/v1/flatmates/profiles",
            params=params,
        )

        assert response.status_code == 422
