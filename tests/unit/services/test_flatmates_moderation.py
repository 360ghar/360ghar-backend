"""Tests for moderation logic."""

from __future__ import annotations

import pytest
from sqlalchemy.exc import IntegrityError

from app.core.exceptions import BadRequestException
from app.models.social import UserReport
from app.models.enums import UserReportReason
from app.schemas.flatmates import ReportCreate
from app.services.flatmates.moderation import create_report

class TestCreateReport:
    @pytest.mark.asyncio
    async def test_duplicate_report_lookup_returns_existing(
        self, db_session, test_user, test_user_2
    ):
        """Test that legacy duplicate lookup works and returns the existing open report."""
        payload = ReportCreate(
            reported_user_id=test_user_2.id,
            reason=UserReportReason.spam,
            notes="He is spamming",
        )
        
        # Create first report
        report1 = await create_report(db_session, test_user.id, payload)
        
        # Call again; it should return the exact same report instead of raising
        report2 = await create_report(db_session, test_user.id, payload)
        
        assert report1.id == report2.id

