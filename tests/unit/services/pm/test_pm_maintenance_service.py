"""
Tests for PM maintenance service module.
"""


import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import (
    MaintenanceCategory,
    MaintenanceRequestStatus,
    MaintenanceUrgency,
)


class TestCreateMaintenanceRequest:
    """Tests for create_maintenance_request function."""

    @pytest.mark.asyncio
    async def test_create_maintenance_request_as_owner(
        self,
        db_session: AsyncSession,
        test_user,
        test_managed_property,
    ):
        """Test owner creating maintenance request."""
        from app.services.pm_maintenance import create_maintenance_request

        result = await create_maintenance_request(
            db_session,
            actor=test_user,
            property_id=test_managed_property.id,
            category=MaintenanceCategory.plumbing,
            urgency=MaintenanceUrgency.medium,
            title="Leaky faucet",
            description="Kitchen faucet is dripping",
        )

        assert result is not None
        assert result.title == "Leaky faucet"
        assert result.request_status == MaintenanceRequestStatus.open
        assert result.category == MaintenanceCategory.plumbing
        assert result.urgency == MaintenanceUrgency.medium


class TestListMaintenanceRequests:
    """Tests for list_maintenance_requests function."""

    @pytest.mark.asyncio
    async def test_list_requests_for_owner(
        self,
        db_session: AsyncSession,
        test_user,
        test_maintenance_request,
    ):
        """Test listing maintenance requests for owner."""
        from app.services.pm_maintenance import list_maintenance_requests

        rows, _next, _total = await list_maintenance_requests(
            db_session,
            actor=test_user,
            cursor_payload={},
        )

        assert isinstance(rows, list)
        assert len(rows) >= 1


class TestUpdateMaintenanceRequest:
    """Tests for update_maintenance_request function."""

    @pytest.mark.asyncio
    async def test_update_request_status(
        self,
        db_session: AsyncSession,
        test_user,
        test_maintenance_request,
    ):
        """Test updating maintenance request status."""
        from app.services.pm_maintenance import update_maintenance_request

        result = await update_maintenance_request(
            db_session,
            actor=test_user,
            request_id=test_maintenance_request.id,
            request_status=MaintenanceRequestStatus.in_review,
        )

        assert result is not None
        assert result.request_status == MaintenanceRequestStatus.in_review

    @pytest.mark.asyncio
    async def test_update_request_estimated_cost(
        self,
        db_session: AsyncSession,
        test_user,
        test_maintenance_request,
    ):
        """Test updating maintenance request estimated cost."""
        from app.services.pm_maintenance import update_maintenance_request

        result = await update_maintenance_request(
            db_session,
            actor=test_user,
            request_id=test_maintenance_request.id,
            estimated_cost=2500.0,
        )

        assert result is not None
        assert result.estimated_cost == 2500.0


class TestMaintenanceEnums:
    """Tests for maintenance enum values."""

    def test_urgency_enum_values(self):
        """Test urgency enum values."""
        assert MaintenanceUrgency.low.value == "low"
        assert MaintenanceUrgency.medium.value == "medium"
        assert MaintenanceUrgency.high.value == "high"
        assert MaintenanceUrgency.emergency.value == "emergency"

    def test_status_enum_values(self):
        """Test status enum values."""
        assert MaintenanceRequestStatus.open.value == "open"
        assert MaintenanceRequestStatus.in_review.value == "in_review"
        assert MaintenanceRequestStatus.resolved.value == "resolved"
        assert MaintenanceRequestStatus.closed.value == "closed"

    def test_category_enum_values(self):
        """Test category enum values."""
        assert MaintenanceCategory.plumbing.value == "plumbing"
        assert MaintenanceCategory.electrical.value == "electrical"
        assert MaintenanceCategory.hvac.value == "hvac"
