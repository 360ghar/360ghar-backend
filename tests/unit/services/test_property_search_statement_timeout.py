"""Statement-timeout placement in the unified property search.

The connection-level libpq ``options`` timeout is not reliably honoured through
the Supavisor transaction pooler, so an uncached search must apply
``DB_READ_STATEMENT_TIMEOUT_MS`` inside its own transaction (``SET LOCAL`` via
``apply_statement_timeout``) — after the cache check (cache hits must not open
a transaction) and before the search queries run. These tests script the search
the same way ``test_property_flatmates_filters`` does and assert on event
ordering rather than SQL text.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.schemas.property import UnifiedPropertyFilter
from app.services.property.search import get_unified_properties_optimized


class _EmptyResult:
    def all(self):
        return []

    def scalars(self):
        return self

    def scalar(self):
        return 0

    def scalar_one_or_none(self):
        return None


class _LiftResult:
    def scalar_one_or_none(self):
        return 5


class _SearchEvents:
    """Runs the real search with the DB scripted; records ordered events."""

    def __init__(self, db, *, cached=None) -> None:
        self.events: list[str] = []

        def _execute(_stmt, *args, **kwargs):  # noqa: ANN002, ANN003
            self.events.append("query")
            return object()

        db.execute = _execute

        def _record_timeout(_session, _timeout_ms):  # noqa: ANN001
            self.events.append("timeout")

        def fake_retry(_db, operation, *, operation_name=None, **kwargs):  # noqa: ANN001, ANN003
            self.events.append("query")
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
            new=AsyncMock(side_effect=_record_timeout),
        )
        self.cache_get_patch = patch(
            "app.services.property.search.PropertyCacheManager.get_cached_properties",
            new_callable=AsyncMock,
            return_value=cached,
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


@pytest.mark.asyncio
async def test_uncached_search_applies_timeout_before_queries(mock_db_session):
    filters = UnifiedPropertyFilter()
    with _SearchEvents(mock_db_session, cached=None) as events:
        await get_unified_properties_optimized(mock_db_session, filters, None, {}, 10)

    assert events.events, "expected the search to run queries on a cache miss"
    assert events.events.count("timeout") == 1
    assert events.events[0] == "timeout"
    assert events.events[1] == "query"


@pytest.mark.asyncio
async def test_cached_hit_never_opens_a_timeout_transaction(mock_db_session):
    filters = UnifiedPropertyFilter()
    cached = {"items": [], "has_more": False}
    with _SearchEvents(mock_db_session, cached=cached) as events:
        items, _next, _total = await get_unified_properties_optimized(
            mock_db_session, filters, None, {}, 10
        )

    assert items == []
    assert events.events == []
