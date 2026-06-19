"""Tests for visit overlap/conflict detection in create_visit.

These tests exercise the application-level conflict check added to
``app.services.visit.create_visit``. They use real database rows
(transactional rollback per test) and the factory fixtures.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictException
from app.models.enums import VisitStatus
from app.schemas.visit import VisitCreate
from app.services.visit import create_visit
from tests.fixtures.factories import PropertyFactory, UserFactory

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def user_and_property(db_session: AsyncSession):
    user = await UserFactory.create(db_session)
    prop = await PropertyFactory.create(db_session, owner=user)
    return user, prop


async def _create_visit(db_session, user, prop, when):
    return await create_visit(
        db_session,
        user.id,
        VisitCreate(property_id=prop.id, scheduled_date=when),
    )


async def test_overlapping_visit_raises_conflict(db_session: AsyncSession, user_and_property):
    """A second visit overlapping an existing active visit raises 409 conflict."""
    user, prop = user_and_property
    base = datetime.now(timezone.utc) + timedelta(days=2)

    first = await _create_visit(db_session, user, prop, base)
    assert first.status == VisitStatus.scheduled

    with pytest.raises(ConflictException) as exc_info:
        await _create_visit(db_session, user, prop, base)

    assert exc_info.value.status_code == 409
    assert exc_info.value.error_code == "VISIT_CONFLICT"


async def test_non_overlapping_visit_succeeds(db_session: AsyncSession, user_and_property):
    """Visits far enough apart do not conflict."""
    user, prop = user_and_property
    base = datetime.now(timezone.utc) + timedelta(days=2)

    # Default duration is 60 minutes; 3 hours apart is safely non-overlapping.
    first = await _create_visit(db_session, user, prop, base)
    second = await _create_visit(db_session, user, prop, base + timedelta(hours=3))

    assert first.id != second.id
    assert second.status == VisitStatus.scheduled


async def test_cancelled_visit_does_not_conflict(db_session: AsyncSession, user_and_property):
    """A cancelled visit must not block a new overlapping visit."""
    user, prop = user_and_property
    base = datetime.now(timezone.utc) + timedelta(days=2)

    first = await _create_visit(db_session, user, prop, base)
    # Mark the existing visit as cancelled directly.
    first.status = VisitStatus.cancelled
    await db_session.flush()

    # An overlapping visit should now be allowed.
    second = await _create_visit(db_session, user, prop, base)
    assert second.status == VisitStatus.scheduled


async def test_completed_visit_does_not_conflict(db_session: AsyncSession, user_and_property):
    """A completed visit must not block a new overlapping visit."""
    user, prop = user_and_property
    base = datetime.now(timezone.utc) + timedelta(days=2)

    first = await _create_visit(db_session, user, prop, base)
    first.status = VisitStatus.completed
    await db_session.flush()

    second = await _create_visit(db_session, user, prop, base)
    assert second.status == VisitStatus.scheduled


async def test_conflict_buffer_applies(db_session: AsyncSession, user_and_property, monkeypatch):
    """When a buffer is configured, back-to-back visits conflict."""
    from app.config import settings

    monkeypatch.setattr(settings, "VISIT_CONFLICT_BUFFER_MINUTES", 30)

    user, prop = user_and_property
    base = datetime.now(timezone.utc) + timedelta(days=2)

    await _create_visit(db_session, user, prop, base)

    # 60-minute duration + 30-minute buffer on each side: a visit starting 80
    # minutes after the first starts is still within the buffered overlap window
    # (existing_end + buffer = base+90 > base+80 = new_start).
    with pytest.raises(ConflictException):
        await _create_visit(db_session, user, prop, base + timedelta(minutes=80))


async def test_same_user_different_properties_allowed(db_session: AsyncSession, user_and_property):
    """A user may have concurrent visits for different properties."""
    user, _ = user_and_property
    prop2 = await PropertyFactory.create(db_session, owner=user)
    base = datetime.now(timezone.utc) + timedelta(days=2)

    first = await _create_visit(db_session, user, user_and_property[1], base)
    second = await _create_visit(db_session, user, prop2, base)

    assert first.id != second.id
    assert second.status == VisitStatus.scheduled


async def test_different_users_same_property_allowed(db_session: AsyncSession, user_and_property):
    """An agent may show the same property to multiple users at the same time."""
    _, prop = user_and_property
    user2 = await UserFactory.create(db_session)
    base = datetime.now(timezone.utc) + timedelta(days=2)

    first = await _create_visit(db_session, user_and_property[0], prop, base)
    second = await _create_visit(db_session, user2, prop, base)

    assert first.id != second.id
    assert second.status == VisitStatus.scheduled
