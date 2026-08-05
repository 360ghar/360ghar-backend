"""Unit tests for flatmates listing enhancement filters in property search.

``get_unified_properties_optimized`` builds SQL conditions inline, so these
tests run it against a scripted mock session, capture the executed statements,
and compile them with the PostgreSQL dialect (no DB required).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.dialects import postgresql

from app.schemas.property import UnifiedPropertyFilter
from app.services.property.search import get_unified_properties_optimized


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


class _LiftResult:
    def scalar_one_or_none(self):
        return 5


def _compile(stmt) -> str:
    compiled = stmt.compile(
        dialect=postgresql.dialect(),
        compile_kwargs={"literal_binds": True},
    )
    return " ".join(str(compiled).split())


class _SearchHarness:
    def __init__(self, db) -> None:
        self.db = db
        self.statements: list = []

        # Plain synchronous recorder: search.py only executes statements through
        # the (patched) execute_with_transient_retry lambdas below, so a real
        # function records the query and never needs awaiting.
        def _execute(stmt, *args, **kwargs):  # noqa: ANN002, ANN003
            self.statements.append(stmt)
            return object()

        db.execute = _execute

        def fake_retry(db_, operation, *, operation_name=None, **kwargs):  # noqa: ANN002
            operation()
            if operation_name == "property_search_lift_lookup":
                return _LiftResult()
            return _EmptyResult()

        self.retry_patch = patch(
            "app.services.property.search.execute_with_transient_retry",
            side_effect=fake_retry,
        )
        self.timeout_patch = patch(
            "app.services.property.search.apply_statement_timeout",
            new_callable=AsyncMock,
        )
        self.cache_get_patch = patch(
            "app.services.property.search.PropertyCacheManager.get_cached_properties",
            new_callable=AsyncMock,
            return_value=None,
        )
        self.cache_set_patch = patch(
            "app.services.property.search.PropertyCacheManager.cache_properties",
            new_callable=AsyncMock,
        )

    def __enter__(self):
        self.retry_patch.start()
        self.timeout_patch.start()
        self.cache_get_patch.start()
        self.cache_set_patch.start()
        return self

    def __exit__(self, *exc):  # noqa: ANN002
        self.cache_set_patch.stop()
        self.cache_get_patch.stop()
        self.timeout_patch.stop()
        self.retry_patch.stop()

    @property
    def sql(self) -> str:
        return " ".join(_compile(stmt) for stmt in self.statements)

    @property
    def where(self) -> str:
        """WHERE clauses only (SELECT lists every Property column)."""
        where_text: list[str] = []
        for stmt in self.statements:
            compiled = _compile(stmt)
            start = compiled.find("WHERE")
            if start != -1:
                where_text.append(compiled[start:])
        return " ".join(where_text)


@pytest.mark.asyncio
async def test_furnishing_filter_uses_furnishing_level_in(mock_db_session):
    filters = UnifiedPropertyFilter(furnishing=["furnished"])
    with _SearchHarness(mock_db_session) as harness:
        rows, _next, _total = await get_unified_properties_optimized(
            harness.db, filters, None, {}, 10
        )

    assert rows == []
    assert "properties.furnishing_level IN ('furnished')" in harness.sql


@pytest.mark.asyncio
async def test_kitchen_type_filter_uses_in_clause(mock_db_session):
    filters = UnifiedPropertyFilter(kitchen_type=["vegetarian", "any"])
    with _SearchHarness(mock_db_session) as harness:
        await get_unified_properties_optimized(harness.db, filters, None, {}, 10)

    # 'any' is a client-side sentinel meaning "no kitchen constraint" and is
    # stripped before building the IN clause, so only real values filter.
    assert "properties.kitchen_type IN ('vegetarian')" in harness.sql
    assert "'any'" not in harness.sql


@pytest.mark.asyncio
async def test_kitchen_type_any_sentinel_alone_yields_no_filter(mock_db_session):
    filters = UnifiedPropertyFilter(kitchen_type=["any"])
    with _SearchHarness(mock_db_session) as harness:
        await get_unified_properties_optimized(harness.db, filters, None, {}, 10)

    assert "kitchen_type" not in harness.where


@pytest.mark.asyncio
async def test_ventilation_type_filter_uses_in_clause(mock_db_session):
    filters = UnifiedPropertyFilter(ventilation_type=["good"])
    with _SearchHarness(mock_db_session) as harness:
        await get_unified_properties_optimized(harness.db, filters, None, {}, 10)

    assert "properties.ventilation_type IN ('good')" in harness.sql


@pytest.mark.asyncio
async def test_windows_min_filter_appends_windows_count_ge(mock_db_session):
    filters = UnifiedPropertyFilter(windows_min=3)
    with _SearchHarness(mock_db_session) as harness:
        await get_unified_properties_optimized(harness.db, filters, None, {}, 10)

    assert "properties.windows_count >= 3" in harness.sql


@pytest.mark.asyncio
async def test_has_lift_looks_up_lift_amenity_and_filters_by_id(mock_db_session):
    filters = UnifiedPropertyFilter(has_lift=True)
    with _SearchHarness(mock_db_session) as harness:
        await get_unified_properties_optimized(harness.db, filters, None, {}, 10)

    # Amenity lookup resolves 'Lift'/'Elevator' case-insensitively (the seed
    # ships both rows with the same icon).
    assert "lower(amenities.title) IN ('lift', 'elevator')" in harness.sql
    # Properties are then restricted to those linked to the lift amenity.
    assert "properties.id IN (SELECT property_amenities.property_id" in harness.sql
    assert "property_amenities.amenity_id = 5" in harness.sql


@pytest.mark.asyncio
async def test_all_flatmates_filters_combine(mock_db_session):
    filters = UnifiedPropertyFilter(
        furnishing=["furnished", "semi_furnished"],
        kitchen_type=["any"],
        ventilation_type=["good"],
        windows_min=2,
        has_lift=True,
    )
    with _SearchHarness(mock_db_session) as harness:
        await get_unified_properties_optimized(harness.db, filters, None, {}, 10)

    assert "properties.furnishing_level IN ('furnished', 'semi_furnished')" in harness.sql
    # 'any' kitchen sentinel is stripped, so no kitchen clause is emitted.
    assert "kitchen_type" not in harness.where
    assert "properties.ventilation_type IN ('good')" in harness.sql
    assert "properties.windows_count >= 2" in harness.sql
    assert "lower(amenities.title) IN ('lift', 'elevator')" in harness.sql


@pytest.mark.asyncio
async def test_no_flatmates_filters_applied_when_unset(mock_db_session):
    filters = UnifiedPropertyFilter()
    with _SearchHarness(mock_db_session) as harness:
        await get_unified_properties_optimized(harness.db, filters, None, {}, 10)

    assert "furnishing_level" not in harness.where
    assert "kitchen_type" not in harness.where
    assert "ventilation_type" not in harness.where
    assert "windows_count" not in harness.where
    assert "lower(amenities.title) = 'lift'" not in harness.where
