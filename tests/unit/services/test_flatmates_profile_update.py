"""Unit tests for update_flatmates_profile field persistence and age bookkeeping."""

from __future__ import annotations

from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.models.enums import FlatmatesDrinkingType, FlatmatesProfileStatus, FlatmatesSmokingType
from app.schemas.flatmates import FlatmatesProfileUpdate
from app.services.flatmates.profiles import update_flatmates_profile


def _fake_user(**overrides) -> SimpleNamespace:
    defaults = {
        "id": 1,
        "full_name": "Test User",
        "email": "test@example.com",
        "phone": "+919876543210",
        "profile_image_url": None,
        "flatmates_mode": None,
        "flatmates_profile_status": FlatmatesProfileStatus.draft,
        "flatmates_onboarding_completed": False,
        "flatmates_bio": None,
        "flatmates_budget_min": None,
        "flatmates_budget_max": None,
        "flatmates_move_in_timeline": None,
        "flatmates_city": None,
        "flatmates_locality": None,
        "flatmates_sleep_schedule": None,
        "flatmates_cleanliness": None,
        "flatmates_food_habits": None,
        "flatmates_smoking": None,
        "flatmates_drinking": None,
        "native_place": None,
        "linkedin_url": None,
        "flatmates_guests_policy": None,
        "flatmates_work_style": None,
        "flatmates_last_active_at": None,
        "flatmates_age": None,
        "date_of_birth": None,
        "preferences": {},
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _dob_age(born: datetime) -> int:
    today = date.today()
    return today.year - born.year - ((today.month, today.day) < (born.month, born.day))


@pytest.fixture
def db(mock_db_session):
    return mock_db_session


class TestProfileUpdateAgeSync:
    @pytest.mark.asyncio
    async def test_updating_age_writes_flatmates_age(self, db):
        user = _fake_user(flatmates_age=30, date_of_birth=datetime(1990, 1, 1))
        db.get = AsyncMock(return_value=user)

        result = await update_flatmates_profile(db, 1, FlatmatesProfileUpdate(age=32))

        assert user.flatmates_age == 32
        assert user.preferences["flatmates"]["age"] == 32
        assert result["age"] == 32

    @pytest.mark.asyncio
    async def test_clearing_age_falls_back_to_dob(self, db):
        born = datetime(1995, 6, 15)
        user = _fake_user(flatmates_age=32, date_of_birth=born)
        db.get = AsyncMock(return_value=user)

        await update_flatmates_profile(db, 1, FlatmatesProfileUpdate(age=None))

        assert user.flatmates_age == _dob_age(born)
        assert "age" not in user.preferences["flatmates"]

    @pytest.mark.asyncio
    async def test_clearing_age_without_dob_leaves_null(self, db):
        user = _fake_user(flatmates_age=32, date_of_birth=None)
        db.get = AsyncMock(return_value=user)

        await update_flatmates_profile(db, 1, FlatmatesProfileUpdate(age=None))

        assert user.flatmates_age is None

    @pytest.mark.asyncio
    async def test_age_via_preferences_patch_resyncs_column(self, db):
        user = _fake_user(flatmates_age=30)
        db.get = AsyncMock(return_value=user)

        # preferences patch merges directly into the flatmates prefs dict.
        await update_flatmates_profile(
            db, 1, FlatmatesProfileUpdate(preferences={"age": 27})
        )

        assert user.flatmates_age == 27
        assert user.preferences["flatmates"]["age"] == 27


class TestProfileUpdateFieldPersistence:
    @pytest.mark.asyncio
    async def test_new_fields_persist_to_user(self, db):
        user = _fake_user()
        db.get = AsyncMock(return_value=user)

        result = await update_flatmates_profile(
            db,
            1,
            FlatmatesProfileUpdate(
                native_place="Pune",
                linkedin_url="https://linkedin.com/in/test",
                smoking=FlatmatesSmokingType.never,
                drinking=FlatmatesDrinkingType.regularly,
            ),
        )

        assert user.native_place == "Pune"
        assert user.linkedin_url == "https://linkedin.com/in/test"
        assert user.flatmates_smoking == FlatmatesSmokingType.never
        assert user.flatmates_drinking == FlatmatesDrinkingType.regularly
        assert result["native_place"] == "Pune"
        assert result["smoking"] == "never"
        assert result["drinking"] == "regularly"

    @pytest.mark.asyncio
    async def test_clearing_new_fields_sets_none(self, db):
        user = _fake_user(native_place="Pune", linkedin_url="https://linkedin.com/in/x")
        db.get = AsyncMock(return_value=user)

        await update_flatmates_profile(
            db,
            1,
            FlatmatesProfileUpdate(native_place=None, linkedin_url=None),
        )

        assert user.native_place is None
        assert user.linkedin_url is None

    @pytest.mark.asyncio
    async def test_touches_last_active_at_and_commits(self, db):
        user = _fake_user()
        db.get = AsyncMock(return_value=user)

        await update_flatmates_profile(db, 1, FlatmatesProfileUpdate(bio="Hi"))

        assert user.flatmates_last_active_at is not None
        assert user.flatmates_last_active_at.tzinfo == timezone.utc
        db.flush.assert_awaited_once()
        db.refresh.assert_awaited_once_with(user)
        db.commit.assert_awaited_once()
