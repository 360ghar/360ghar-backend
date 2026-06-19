"""
Tests for visit service module.
"""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BadRequestException


class TestCreateVisit:
    """Tests for create_visit function."""

    @pytest.mark.asyncio
    async def test_create_visit_success(
        self,
        db_session: AsyncSession,
        test_user,
        test_property,
    ):
        """Test successful visit creation."""
        from app.schemas.visit import VisitCreate
        from app.services.visit import create_visit

        scheduled = datetime.now(timezone.utc) + timedelta(days=7)
        visit_data = VisitCreate(
            property_id=test_property.id,
            scheduled_date=scheduled,
            notes="I want to see the property",
        )

        result = await create_visit(db_session, test_user.id, visit_data)

        assert result is not None
        assert result.user_id == test_user.id
        assert result.property_id == test_property.id
        assert result.status == "scheduled"

    @pytest.mark.asyncio
    async def test_create_visit_past_date_fails(
        self,
        db_session: AsyncSession,
        test_user,
        test_property,
    ):
        """Test visit creation fails with past date."""
        from app.schemas.visit import VisitCreate
        from app.services.visit import create_visit

        past_date = datetime.now(timezone.utc) - timedelta(days=1)
        visit_data = VisitCreate(
            property_id=test_property.id,
            scheduled_date=past_date,
        )

        with pytest.raises(BadRequestException) as exc_info:
            await create_visit(db_session, test_user.id, visit_data)

        assert exc_info.value.status_code == 400
        assert "future" in str(exc_info.value).lower()


class TestGetVisit:
    """Tests for get_visit function."""

    @pytest.mark.asyncio
    async def test_get_visit_success(
        self,
        db_session: AsyncSession,
        test_visit,
    ):
        """Test getting visit by ID."""
        from app.services.visit import get_visit

        result = await get_visit(db_session, test_visit.id)

        assert result is not None
        assert result.id == test_visit.id

    @pytest.mark.asyncio
    async def test_get_visit_not_found(self, db_session: AsyncSession):
        """Test getting non-existent visit."""
        from app.services.visit import get_visit

        result = await get_visit(db_session, 99999)

        assert result is None


class TestGetUserVisits:
    """Tests for get_user_visits function."""

    @pytest.mark.asyncio
    async def test_get_user_visits(
        self,
        db_session: AsyncSession,
        test_user,
        test_visits,
    ):
        """Test getting all visits for a user."""
        from app.services.visit import get_user_visits

        rows, next_payload, count_total = await get_user_visits(db_session, test_user.id, cursor_payload={}, limit=100)

        assert isinstance(rows, list)
        assert len(rows) == len(test_visits)


class TestGetUserUpcomingVisits:
    """Tests for get_user_upcoming_visits function."""

    @pytest.mark.asyncio
    async def test_get_upcoming_visits(
        self,
        db_session: AsyncSession,
        test_user,
        test_visits,
    ):
        """Test getting upcoming visits."""
        from app.services.visit import get_user_upcoming_visits

        rows, _next, _total = await get_user_upcoming_visits(db_session, test_user.id, cursor_payload={}, limit=100)
        assert isinstance(rows, list)


class TestGetUserPastVisits:
    """Tests for get_user_past_visits function."""

    @pytest.mark.asyncio
    async def test_get_past_visits(
        self,
        db_session: AsyncSession,
        test_user,
        test_visits,
    ):
        """Test getting past visits."""
        from app.services.visit import get_user_past_visits

        rows, _next, _total = await get_user_past_visits(db_session, test_user.id, cursor_payload={}, limit=100)
        assert isinstance(rows, list)


class TestCancelVisit:
    """Tests for cancel_visit function."""

    @pytest.mark.asyncio
    async def test_cancel_visit_success(
        self,
        db_session: AsyncSession,
        test_visit,
    ):
        """Test successful visit cancellation."""
        from app.services.visit import cancel_visit

        result = await cancel_visit(db_session, test_visit.id, "Changed my mind")

        assert result is not None
        assert result.status == "cancelled"
        assert result.cancellation_reason == "Changed my mind"

    @pytest.mark.asyncio
    async def test_cancel_visit_not_found(self, db_session: AsyncSession):
        """Test cancelling non-existent visit."""
        from app.services.visit import cancel_visit

        result = await cancel_visit(db_session, 99999, "Reason")

        assert result is None

    @pytest.mark.asyncio
    async def test_cancel_already_cancelled_visit(
        self,
        db_session: AsyncSession,
        cancelled_visit,
    ):
        """Test cancelling already cancelled visit."""
        from app.services.visit import cancel_visit

        result = await cancel_visit(db_session, cancelled_visit.id, "Another reason")

        assert result is None


class TestRescheduleVisit:
    """Tests for reschedule_visit function."""

    @pytest.mark.asyncio
    async def test_reschedule_visit_success(
        self,
        db_session: AsyncSession,
        test_visit,
    ):
        """Test successful visit reschedule."""
        from app.services.visit import reschedule_visit

        new_date = datetime.now(timezone.utc) + timedelta(days=14)
        result = await reschedule_visit(db_session, test_visit.id, new_date, "New schedule")

        assert result is not None
        assert result.status == "rescheduled"

    @pytest.mark.asyncio
    async def test_reschedule_visit_past_date_fails(
        self,
        db_session: AsyncSession,
        test_visit,
    ):
        """Test rescheduling to past date fails."""
        from app.services.visit import reschedule_visit

        past_date = datetime.now(timezone.utc) - timedelta(days=1)
        result = await reschedule_visit(db_session, test_visit.id, past_date)

        assert result is None


class TestMarkVisitCompleted:
    """Tests for mark_visit_completed function."""

    @pytest.mark.asyncio
    async def test_mark_visit_completed(
        self,
        db_session: AsyncSession,
        test_visit,
    ):
        """Test marking visit as completed."""
        from app.services.visit import mark_visit_completed

        result = await mark_visit_completed(
            db_session,
            test_visit.id,
            notes="Nice property",
            feedback="Great experience",
        )

        assert result is True

    @pytest.mark.asyncio
    async def test_mark_visit_completed_not_found(self, db_session: AsyncSession):
        """Test marking non-existent visit as completed."""
        from app.services.visit import mark_visit_completed

        result = await mark_visit_completed(db_session, 99999)

        assert result is False


class TestGetAgentVisits:
    """Tests for get_agent_visits function."""

    @pytest.mark.asyncio
    async def test_get_agent_visits_paginated(
        self,
        db_session: AsyncSession,
        test_agent,
    ):
        """Test getting paginated agent visits."""
        from app.services.visit import get_agent_visits

        result_items, result_next, result_total = await get_agent_visits(
            db_session, test_agent.id, cursor_payload={}, limit=10
        )

        assert isinstance(result_items, list)
        assert result_next is None or isinstance(result_next, dict)
        assert result_total is None


class TestGetAllVisits:
    """Tests for get_all_visits function."""

    @pytest.mark.asyncio
    async def test_get_all_visits_no_filters(self, db_session: AsyncSession, test_visits):
        """Test getting all visits without filters."""
        from app.services.visit import get_all_visits

        rows, _next, _total = await get_all_visits(db_session, cursor_payload={}, limit=20)

        assert isinstance(rows, list)

    @pytest.mark.asyncio
    async def test_get_all_visits_with_status_filter(
        self,
        db_session: AsyncSession,
        test_visits,
    ):
        """Test getting visits filtered by status."""
        from app.services.visit import get_all_visits

        rows, _next, _total = await get_all_visits(db_session, cursor_payload={}, limit=20, status="scheduled")

        assert isinstance(rows, list)
