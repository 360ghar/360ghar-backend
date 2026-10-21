"""Contract fixes for the users domain, review round 3 (residual pass).

Each test pins one residual item from the wave-3 review. Schema and model
tests need no database. The endpoint tests use the shared client fixtures
and roll back with the test session.
"""

from __future__ import annotations

import uuid
from typing import get_args

import pytest

import app.models.enums as enums
import app.schemas.flatmates as flatmates_schemas
from app.models.enums import TourStatus, TourVisibility
from app.models.tours import Tour, TourAnalyticsEvent
from app.models.users import User
from app.schemas.common import ProfileVisibility

# ── be-user-26: dead onboarding column is unmapped; the column itself is kept ──


def test_ghar360_onboarding_column_is_not_mapped_in_the_orm() -> None:
    """The column stays in the database for the user to drop. No model or schema maps it."""
    assert "ghar360_onboarding_completed" not in User.__table__.c.keys()
    assert "flatmates_onboarding_completed" in User.__table__.c.keys()


# ── be-content-44: legacy combined smoking column and dead flatmates contracts ──


def test_legacy_smoking_drinking_column_and_enum_are_not_mapped() -> None:
    """flatmates_smoking_drinking has no ORM mapping and the combined enum is gone.

    The split columns flatmates_smoking and flatmates_drinking carry the data.
    """
    assert "flatmates_smoking_drinking" not in User.__table__.c.keys()
    assert not hasattr(enums, "SmokingDrinking")


def test_dead_flatmates_schemas_are_removed() -> None:
    assert not hasattr(flatmates_schemas, "DiscoverProfilesQuery")
    assert "age" not in flatmates_schemas.FlatmatesPeer.model_fields


# ── be-user-6: privacy fields, profile_visibility values, and 422 on unknown keys ──


def test_profile_visibility_values_match_the_admin_type() -> None:
    """The admin type declares public, agents_only and private. The backend must accept the same set."""
    assert get_args(ProfileVisibility) == ("public", "agents_only", "private")


@pytest.mark.asyncio
async def test_privacy_put_accepts_the_admin_keys_and_returns_them(authenticated_client) -> None:
    """The admin profile save sends these keys. None may be dropped silently."""
    body = {
        "profile_visibility": "agents_only",
        "show_phone": True,
        "show_email": False,
        "allow_location_tracking": False,
        "data_sharing_consent": True,
    }
    response = await authenticated_client.put("/api/v1/users/privacy-settings", json=body)
    assert response.status_code == 200, response.text
    for key, value in body.items():
        assert response.json()[key] == value

    stored = await authenticated_client.get("/api/v1/users/privacy-settings")
    assert stored.status_code == 200, stored.text
    for key, value in body.items():
        assert stored.json()[key] == value


@pytest.mark.parametrize(
    "body",
    [{"bogus": True}, {"profile_visibility": "nobody"}, {"show_phone": None}],
)
@pytest.mark.asyncio
async def test_privacy_put_rejects_unknown_keys_and_bad_values(authenticated_client, body) -> None:
    response = await authenticated_client.put("/api/v1/users/privacy-settings", json=body)
    assert response.status_code == 422, response.text


# ── Dashboard realtime: recent_views buckets use the timestamp key ──


@pytest.mark.asyncio
async def test_dashboard_realtime_buckets_use_the_timestamp_key(
    authenticated_client, db_session, test_user
) -> None:
    """The tours web chart reads timestamp. A bucket with a date key would lose the x-axis."""
    tour = Tour(
        id=str(uuid.uuid4()),
        user_id=test_user.id,
        title="Realtime Tour",
        status=TourStatus.published,
        is_public=True,
        visibility=TourVisibility.public,
    )
    db_session.add(tour)
    await db_session.flush()
    db_session.add(TourAnalyticsEvent(tour_id=tour.id, event_type="view", session_id="residual-r3"))
    await db_session.flush()

    response = await authenticated_client.get("/api/v1/dashboard/realtime")
    assert response.status_code == 200, response.text
    buckets = response.json()["recent_views"]
    assert len(buckets) == 1
    assert set(buckets[0]) == {"timestamp", "views"}
    assert buckets[0]["views"] == 1
