"""Unit tests for discoverable-profile filters: age range and smoke/drink deal-breakers.

``list_discoverable_profiles`` builds SQLAlchemy conditions inline. These tests
run the function against a mocked session and compile the executed statements
with the PostgreSQL dialect (no DB required), then assert the exact filter
clauses that were appended.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.dialects import postgresql

from app.models.users import User
from app.services.flatmates.profiles import list_discoverable_profiles


class _Scalars:
    def all(self):
        return []


class _EmptyResult:
    def scalars(self):
        return _Scalars()

    def scalar(self):
        return 0

    def scalar_one_or_none(self):
        return None


def _compile(stmt) -> str:
    compiled = stmt.compile(
        dialect=postgresql.dialect(),
        compile_kwargs={"literal_binds": True},
    )
    return " ".join(str(compiled).split())


def _fake_requesting_user(*, phone: str | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        id=1,
        preferences={"flatmates": {"non_negotiables": []}},
        phone=phone,
    )


class _DiscoverHarness:
    """Runs list_discoverable_profiles with a scripted mock session."""

    def __init__(self) -> None:
        self.statements: list = []
        self.db = AsyncMock()
        self.db.get = AsyncMock(return_value=_fake_requesting_user())

        async def _execute(stmt, *args, **kwargs):  # noqa: ANN002, ANN003
            self.statements.append(stmt)
            return _EmptyResult()

        self.db.execute = AsyncMock(side_effect=_execute)

    @property
    def sql(self) -> str:
        return " ".join(_compile(stmt) for stmt in self.statements)

    @property
    def where(self) -> str:
        """WHERE clause of the main users query (SELECT lists every User column,
        so filter assertions must not match the column list)."""
        for stmt in self.statements:
            compiled = _compile(stmt)
            if "FROM users" in compiled:
                start = compiled.find("WHERE")
                end = compiled.find("ORDER BY")
                if start == -1:
                    return ""
                return compiled[start:end] if end != -1 else compiled[start:]
        return ""

    async def run(self, **kwargs) -> None:
        await list_discoverable_profiles(
            self.db,
            user_id=1,
            cursor_payload={},
            limit=20,
            **kwargs,
        )


class TestDiscoverAgeFilter:
    """age_min / age_max append flatmates_age range clauses (NULL passes)."""

    @pytest.mark.asyncio
    async def test_age_min_appends_flatmates_age_ge_or_null(self):
        harness = _DiscoverHarness()
        await harness.run(age_min=25)

        assert "users.flatmates_age >= 25" in harness.where
        assert "users.flatmates_age IS NULL" in harness.where

    @pytest.mark.asyncio
    async def test_age_max_appends_flatmates_age_le_or_null(self):
        harness = _DiscoverHarness()
        await harness.run(age_max=30)

        assert "users.flatmates_age <= 30" in harness.where
        assert "users.flatmates_age IS NULL" in harness.where

    @pytest.mark.asyncio
    async def test_age_min_and_max_combined(self):
        harness = _DiscoverHarness()
        await harness.run(age_min=25, age_max=30)

        assert "users.flatmates_age >= 25" in harness.where
        assert "users.flatmates_age <= 30" in harness.where

    @pytest.mark.asyncio
    async def test_no_age_filters_without_params(self):
        harness = _DiscoverHarness()
        await harness.run()

        assert "flatmates_age" not in harness.where


class TestDealBreakerNonNegotiables:
    """no_smoking / no_drinking exclude occasionally/regularly, NULL passes."""

    @pytest.mark.asyncio
    async def test_no_smoking_filters_never_or_null(self):
        harness = _DiscoverHarness()
        await harness.run(non_negotiables_override=["no_smoking"])

        assert (
            "users.flatmates_smoking IS NULL OR users.flatmates_smoking = 'never'"
            in harness.where
        )
        assert "occasionally" not in harness.where
        assert "regularly" not in harness.where

    @pytest.mark.asyncio
    async def test_no_drinking_filters_never_or_null(self):
        harness = _DiscoverHarness()
        await harness.run(non_negotiables_override=["no_drinking"])

        assert (
            "users.flatmates_drinking IS NULL OR users.flatmates_drinking = 'never'"
            in harness.where
        )
        assert "occasionally" not in harness.where
        assert "regularly" not in harness.where

    @pytest.mark.asyncio
    async def test_both_non_negotiables_applied_together(self):
        harness = _DiscoverHarness()
        await harness.run(
            non_negotiables_override=["no_smoking", "no_drinking"],
        )

        assert (
            "users.flatmates_smoking IS NULL OR users.flatmates_smoking = 'never'"
            in harness.where
        )
        assert (
            "users.flatmates_drinking IS NULL OR users.flatmates_drinking = 'never'"
            in harness.where

        )

    @pytest.mark.asyncio
    async def test_legacy_combined_column_not_used(self):
        """New deal-breakers filter the split columns, never smoking_drinking."""
        harness = _DiscoverHarness()
        await harness.run(
            non_negotiables_override=["no_smoking", "no_drinking"],
        )

        assert "smoking_drinking" not in harness.where
        assert "flatmates_smoking" in harness.where
        assert "flatmates_drinking" in harness.where


class TestDiscoverFilterRegression:
    """Sanity: base discover query still selects active, onboarded users."""

    @pytest.mark.asyncio
    async def test_base_discover_query_shape(self):
        harness = _DiscoverHarness()
        await harness.run()

        assert "FROM users" in harness.sql
        assert "flatmates_onboarding_completed IS true" in harness.sql
        assert "users.id NOT IN (1)" in harness.sql
        assert User.__table__.name == "users"
