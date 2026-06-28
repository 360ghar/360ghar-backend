"""
Tests for visit endpoints.

These tests verify the visit-related API endpoints work correctly.
They mock the service layer to isolate endpoint testing.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

from app.models.enums import VisitStatus
from app.schemas.visit import Visit, VisitSlice


def create_mock_visit(
    visit_id: int = 1,
    user_id: int = 1,
    property_id: int = 1,
    status: VisitStatus = VisitStatus.scheduled,
) -> Visit:
    """Create a mock visit schema object."""
    return Visit(
        id=visit_id,
        user_id=user_id,
        property_id=property_id,
        agent_id=1,
        scheduled_date=datetime.now(timezone.utc) + timedelta(days=3),
        actual_date=None,
        status=status,
        visit_notes=None,
        visitor_feedback=None,
        interest_level=None,
        follow_up_required=False,
        follow_up_date=None,
        cancellation_reason=None,
        rescheduled_from=None,
        created_at=datetime.now(timezone.utc),
        updated_at=None,
        property=None,
        special_requirements=None,
    )


def create_mock_visit_slice(visits: list = None) -> VisitSlice:
    """Create a mock visit slice response."""
    if visits is None:
        visits = []
    return VisitSlice(
        visits=visits,
        total=len(visits),
    )


class TestCreateVisitEndpoint:
    """Tests for POST /api/v1/visits/ endpoint."""

    @pytest.mark.asyncio
    async def test_create_visit_success(self, authenticated_client: AsyncClient):
        """Test successful visit creation."""
        scheduled = datetime.now(timezone.utc) + timedelta(days=7)

        with patch(
            "app.api.api_v1.endpoints.visits.create_visit",
            new_callable=AsyncMock,
        ) as mock_create:
            mock_create.return_value = create_mock_visit(
                visit_id=1,
                property_id=123,
                status=VisitStatus.scheduled,
            )

            response = await authenticated_client.post(
                "/api/v1/visits/",
                json={
                    "property_id": 123,
                    "scheduled_date": scheduled.isoformat(),
                },
            )

            assert response.status_code == 200
            data = response.json()
            # VisitStatus.scheduled serializes to its domain value "requested"
            # (the flatmates visit lifecycle initial state; the web client expects this).
            assert data["status"] == "requested"

    @pytest.mark.asyncio
    async def test_create_visit_unauthorized(self, client: AsyncClient):
        """Test visit creation without auth."""
        scheduled = datetime.now(timezone.utc) + timedelta(days=7)

        response = await client.post(
            "/api/v1/visits/",
            json={
                "property_id": 123,
                "scheduled_date": scheduled.isoformat(),
            },
        )

        assert response.status_code == 401


class TestGetVisitEndpoint:
    """Tests for GET /api/v1/visits/{visit_id} endpoint."""

    @pytest.mark.asyncio
    async def test_get_visit_success(self, authenticated_client: AsyncClient, test_user):
        """Test getting visit by ID."""
        mock_visit = create_mock_visit(visit_id=42, user_id=test_user.id)

        with patch(
            "app.api.api_v1.endpoints.visits.get_visit",
            new_callable=AsyncMock,
        ) as mock_get:
            mock_get.return_value = mock_visit

            response = await authenticated_client.get("/api/v1/visits/42")

            assert response.status_code == 200
            data = response.json()
            assert data["id"] == 42

    @pytest.mark.asyncio
    async def test_get_visit_not_found(self, authenticated_client: AsyncClient):
        """Test getting non-existent visit."""
        with patch(
            "app.api.api_v1.endpoints.visits.get_visit",
            new_callable=AsyncMock,
        ) as mock_get:
            mock_get.return_value = None

            response = await authenticated_client.get("/api/v1/visits/99999")

            assert response.status_code == 404


class TestGetUserVisitsEndpoint:
    """Tests for GET /api/v1/visits/ endpoint."""

    @pytest.mark.asyncio
    async def test_get_user_visits(self, authenticated_client: AsyncClient):
        """Test getting user's visits."""
        with patch(
            "app.api.api_v1.endpoints.visits.get_user_visits",
            new_callable=AsyncMock,
        ) as mock_get:
            mock_get.return_value = ([], None, None)

            response = await authenticated_client.get("/api/v1/visits/")

            assert response.status_code == 200
            data = response.json()
            assert "items" in data


class TestGetUpcomingVisitsEndpoint:
    """Tests for GET /api/v1/visits/upcoming/ endpoint."""

    @pytest.mark.asyncio
    async def test_get_upcoming_visits(self, authenticated_client: AsyncClient):
        """Test getting upcoming visits."""
        with patch(
            "app.api.api_v1.endpoints.visits.get_user_upcoming_visits",
            new_callable=AsyncMock,
        ) as mock_get:
            mock_get.return_value = ([], None, None)

            response = await authenticated_client.get("/api/v1/visits/upcoming/")

            assert response.status_code == 200
            data = response.json()
            assert "items" in data


class TestGetPastVisitsEndpoint:
    """Tests for GET /api/v1/visits/past/ endpoint."""

    @pytest.mark.asyncio
    async def test_get_past_visits(self, authenticated_client: AsyncClient):
        """Test getting past visits."""
        with patch(
            "app.api.api_v1.endpoints.visits.get_user_past_visits",
            new_callable=AsyncMock,
        ) as mock_get:
            mock_get.return_value = ([], None, None)

            response = await authenticated_client.get("/api/v1/visits/past/")

            assert response.status_code == 200
            data = response.json()
            assert "items" in data


class TestCancelVisitEndpoint:
    """Tests for POST /api/v1/visits/{visit_id}/cancel endpoint."""

    @pytest.mark.asyncio
    async def test_cancel_visit_success(self, authenticated_client: AsyncClient, test_user):
        """Test successful visit cancellation."""
        mock_visit = create_mock_visit(visit_id=42, user_id=test_user.id)
        cancelled_visit = create_mock_visit(
            visit_id=42,
            user_id=test_user.id,
            status=VisitStatus.cancelled,
        )

        with patch(
            "app.api.api_v1.endpoints.visits.get_visit",
            new_callable=AsyncMock,
        ) as mock_get, patch(
            "app.api.api_v1.endpoints.visits.cancel_visit",
            new_callable=AsyncMock,
        ) as mock_cancel:
            mock_get.return_value = mock_visit
            mock_cancel.return_value = cancelled_visit

            response = await authenticated_client.post(
                "/api/v1/visits/42/cancel",
                json={"reason": "Change of plans"},
            )

            assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_cancel_visit_not_found(self, authenticated_client: AsyncClient):
        """Test cancelling non-existent visit."""
        with patch(
            "app.api.api_v1.endpoints.visits.get_visit",
            new_callable=AsyncMock,
        ) as mock_get:
            mock_get.return_value = None

            response = await authenticated_client.post(
                "/api/v1/visits/99999/cancel",
                json={"reason": "Test"},
            )

            assert response.status_code == 404


class TestRescheduleVisitEndpoint:
    """Tests for POST /api/v1/visits/{visit_id}/reschedule endpoint."""

    @pytest.mark.asyncio
    async def test_reschedule_visit_success(self, authenticated_client: AsyncClient, test_user):
        """Test successful visit reschedule."""
        new_date = datetime.now(timezone.utc) + timedelta(days=14)
        mock_visit = create_mock_visit(visit_id=42, user_id=test_user.id)
        rescheduled_visit = create_mock_visit(
            visit_id=42,
            user_id=test_user.id,
            status=VisitStatus.rescheduled,
        )

        with patch(
            "app.api.api_v1.endpoints.visits.get_visit",
            new_callable=AsyncMock,
        ) as mock_get, patch(
            "app.api.api_v1.endpoints.visits.reschedule_visit",
            new_callable=AsyncMock,
        ) as mock_reschedule:
            mock_get.return_value = mock_visit
            mock_reschedule.return_value = rescheduled_visit

            response = await authenticated_client.post(
                "/api/v1/visits/42/reschedule",
                json={
                    "new_date": new_date.isoformat(),
                    "reason": "Conflict",
                },
            )

            assert response.status_code == 200


class TestMarkVisitCompletedEndpoint:
    """Tests for POST /api/v1/visits/{visit_id}/complete/ endpoint."""

    @pytest.mark.asyncio
    async def test_mark_visit_completed(self, admin_authenticated_client: AsyncClient):
        """Test marking visit as completed (admin only)."""
        mock_visit = create_mock_visit(visit_id=42)
        completed_visit = create_mock_visit(
            visit_id=42,
            status=VisitStatus.completed,
        )

        with patch(
            "app.api.api_v1.endpoints.visits.get_visit",
            new_callable=AsyncMock,
        ) as mock_get, patch(
            "app.api.api_v1.endpoints.visits.mark_visit_completed",
            new_callable=AsyncMock,
        ) as mock_complete:
            # First call returns initial visit, second call returns completed visit
            mock_get.side_effect = [mock_visit, completed_visit]
            mock_complete.return_value = True

            response = await admin_authenticated_client.post(
                "/api/v1/visits/42/complete/",
                json={
                    "notes": "Nice property",
                    "feedback": "Great experience",
                },
            )

            assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_mark_visit_completed_forbidden(self, authenticated_client: AsyncClient):
        """Test regular user cannot complete visits."""
        mock_visit = create_mock_visit(visit_id=42)

        with patch(
            "app.api.api_v1.endpoints.visits.get_visit",
            new_callable=AsyncMock,
        ) as mock_get:
            mock_get.return_value = mock_visit

            response = await authenticated_client.post(
                "/api/v1/visits/42/complete/",
                json={
                    "notes": "Nice property",
                    "feedback": "Great experience",
                },
            )

            # Regular users should get 403
            assert response.status_code == 403
