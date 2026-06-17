"""
Tests for PM (Property Management) endpoints.

These tests verify PM-related API endpoints work correctly.
They mock the service layer to isolate endpoint testing.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient


class TestPMDashboardEndpoints:
    """Tests for PM dashboard endpoints."""

    @pytest.mark.asyncio
    async def test_get_dashboard_overview(self, authenticated_client: AsyncClient):
        """Test getting dashboard overview."""
        with patch(
            "app.services.pm_dashboard.get_dashboard_overview",
            new_callable=AsyncMock,
        ) as mock_get:
            mock_get.return_value = {
                "total_properties": 5,
                "occupied_properties": 3,
                "vacant_properties": 2,
                "active_leases": 3,
                "expiring_soon": 1,
                "total_tenants": 3,
                "monthly_revenue": 150000.0,
                "collected_revenue": 100000.0,
                "pending_revenue": 50000.0,
                "open_maintenance": 2,
                "pending_expenses": 1,
            }

            response = await authenticated_client.get(
                "/api/v1/pm/dashboard/overview"
            )

            assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_get_dashboard_activity(self, authenticated_client: AsyncClient):
        """Test getting dashboard activity."""
        with patch(
            "app.services.pm_dashboard.get_recent_activity",
            new_callable=AsyncMock,
        ) as mock_get:
            mock_get.return_value = ([], None, None)

            response = await authenticated_client.get(
                "/api/v1/pm/dashboard/activity"
            )

            assert response.status_code == 200
            body = response.json()
            assert "items" in body
            assert "has_more" in body


class TestPMLeaseEndpoints:
    """Tests for PM lease endpoints."""

    @pytest.mark.asyncio
    async def test_list_leases(self, authenticated_client: AsyncClient):
        """Test listing leases returns cursor-paginated envelope."""
        with patch(
            "app.services.pm_leases.list_leases",
            new_callable=AsyncMock,
        ) as mock_list:
            # list_leases now returns (rows, next_payload, count_total)
            mock_list.return_value = ([], None, None)

            response = await authenticated_client.get(
                "/api/v1/pm/leases/"
            )

            assert response.status_code == 200
            body = response.json()
            assert "items" in body
            assert "has_more" in body

    @pytest.mark.asyncio
    async def test_list_leases_unauthorized(self, client: AsyncClient):
        """Test listing leases requires auth."""
        response = await client.get("/api/v1/pm/leases/")
        assert response.status_code == 401


class TestPMRentEndpoints:
    """Tests for PM rent endpoints."""

    @pytest.mark.asyncio
    async def test_list_rent_charges(self, authenticated_client: AsyncClient):
        """Test listing rent charges."""
        with patch(
            "app.services.pm_rent.list_rent_charges",
            new_callable=AsyncMock,
        ) as mock_list:
            mock_list.return_value = ([], None, None)

            response = await authenticated_client.get(
                "/api/v1/pm/rent/charges"
            )

            assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_list_rent_charges_unauthorized(self, client: AsyncClient):
        """Test listing rent charges requires auth."""
        response = await client.get("/api/v1/pm/rent/charges")
        assert response.status_code == 401


class TestPMMaintenanceEndpoints:
    """Tests for PM maintenance endpoints."""

    @pytest.mark.asyncio
    async def test_list_maintenance_requests(self, authenticated_client: AsyncClient):
        """Test listing maintenance requests."""
        with patch(
            "app.services.pm_maintenance.list_maintenance_requests",
            new_callable=AsyncMock,
        ) as mock_list:
            mock_list.return_value = ([], None, None)

            response = await authenticated_client.get(
                "/api/v1/pm/maintenance/requests"
            )

            assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_list_maintenance_unauthorized(self, client: AsyncClient):
        """Test listing maintenance requires auth."""
        response = await client.get("/api/v1/pm/maintenance/requests")
        assert response.status_code == 401


class TestPMTenantEndpoints:
    """Tests for PM tenant endpoints."""

    @pytest.mark.asyncio
    async def test_list_tenants(self, authenticated_client: AsyncClient):
        """Test listing tenants returns cursor-paginated envelope."""
        with patch(
            "app.services.pm_tenants.list_tenants",
            new_callable=AsyncMock,
        ) as mock_list:
            mock_list.return_value = ([], None, None)

            response = await authenticated_client.get(
                "/api/v1/pm/tenants/"
            )

            assert response.status_code == 200
            body = response.json()
            assert "items" in body
            assert "has_more" in body

    @pytest.mark.asyncio
    async def test_list_tenants_unauthorized(self, client: AsyncClient):
        """Test listing tenants requires auth."""
        response = await client.get("/api/v1/pm/tenants/")
        assert response.status_code == 401


class TestPMExpenseEndpoints:
    """Tests for PM expense endpoints."""

    @pytest.mark.asyncio
    async def test_list_expenses(self, authenticated_client: AsyncClient):
        """Test listing expenses."""
        with patch(
            "app.services.pm_expenses.list_expenses",
            new_callable=AsyncMock,
        ) as mock_list:
            mock_list.return_value = ([], None, None)

            response = await authenticated_client.get(
                "/api/v1/pm/expenses/"
            )

            assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_list_expenses_unauthorized(self, client: AsyncClient):
        """Test listing expenses requires auth."""
        response = await client.get("/api/v1/pm/expenses/")
        assert response.status_code == 401
