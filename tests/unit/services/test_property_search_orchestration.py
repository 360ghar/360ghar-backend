"""Tests for shared property search orchestration."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.exc import SQLAlchemyError

from app.core.exceptions import BadRequestException, ServiceUnavailableException
from app.models.enums import PropertyPurpose, PropertyType
from app.schemas.property import SortBy, UnifiedPropertyFilter
from app.services.property.search_orchestration import (
    build_property_search_filters,
    run_property_search,
)


def test_build_property_search_filters_maps_shared_inputs():
    filters = build_property_search_filters(
        latitude=28.45,
        longitude=77.02,
        radius_km=12,
        search_query="near metro",
        semantic_search=True,
        property_ids=[1, 2, 3],
        property_type=[PropertyType.apartment],
        purpose=PropertyPurpose.rent,
        city="Gurugram",
        check_in_date="2026-08-01",
        check_out_date="2026-08-03",
        guests=2,
        exclude_swiped=True,
    )

    assert filters.latitude == 28.45
    assert filters.longitude == 77.02
    assert filters.radius_km == 12
    assert filters.search_query == "near metro"
    assert filters.semantic_search is True
    assert filters.property_ids == [1, 2, 3]
    assert filters.property_type == [PropertyType.apartment]
    assert filters.purpose == PropertyPurpose.rent
    assert filters.city == "Gurugram"
    assert filters.check_in_date == "2026-08-01"
    assert filters.check_out_date == "2026-08-03"
    assert filters.guests == 2
    assert filters.exclude_swiped is True


@pytest.mark.asyncio
async def test_run_property_search_applies_timeout_cleanup_and_delegates(mock_db_session):
    filters = UnifiedPropertyFilter(search_query="apartment")
    cursor_payload = {"o": 20}

    with (
        patch(
            "app.services.property.search_orchestration.apply_statement_timeout",
            new_callable=AsyncMock,
        ) as mock_timeout,
        patch(
            "app.services.property.search_orchestration.pause_stale_flatmate_listings",
            new_callable=AsyncMock,
        ) as mock_pause,
        patch(
            "app.services.property.search_orchestration.get_unified_properties_optimized",
            new_callable=AsyncMock,
        ) as mock_search,
    ):
        mock_search.return_value = (["row"], {"o": 30}, 41)

        result = await run_property_search(
            mock_db_session,
            filters,
            7,
            cursor_payload,
            10,
            with_total=True,
        )

    assert result == (["row"], {"o": 30}, 41)
    mock_timeout.assert_awaited_once()
    mock_pause.assert_awaited_once_with(mock_db_session)
    mock_search.assert_awaited_once()
    assert mock_search.await_args.args == (mock_db_session, filters, 7, cursor_payload, 10)
    assert mock_search.await_args.kwargs == {"with_total": True}


@pytest.mark.asyncio
async def test_run_property_search_rolls_back_failed_stale_pause(mock_db_session):
    filters = UnifiedPropertyFilter()

    with (
        patch(
            "app.services.property.search_orchestration.apply_statement_timeout",
            new_callable=AsyncMock,
        ) as mock_timeout,
        patch(
            "app.services.property.search_orchestration.pause_stale_flatmate_listings",
            new_callable=AsyncMock,
            side_effect=RuntimeError("cleanup failed"),
        ),
        patch(
            "app.services.property.search_orchestration.get_unified_properties_optimized",
            new_callable=AsyncMock,
        ) as mock_search,
    ):
        mock_search.return_value = ([], None, None)

        await run_property_search(mock_db_session, filters, None, {}, 20)

    mock_db_session.rollback.assert_awaited_once()
    assert mock_timeout.await_count == 2
    mock_search.assert_awaited_once()


@pytest.mark.asyncio
async def test_run_property_search_requires_query_for_semantic_search(mock_db_session):
    filters = UnifiedPropertyFilter(semantic_search=True)

    with (
        patch(
            "app.services.property.search_orchestration.apply_statement_timeout",
            new_callable=AsyncMock,
        ) as mock_timeout,
        pytest.raises(BadRequestException, match="semantic_search requires a search query"),
    ):
        await run_property_search(mock_db_session, filters, None, {}, 20)

    mock_timeout.assert_not_awaited()


@pytest.mark.asyncio
async def test_run_property_search_forces_semantic_relevance_without_mutating_input(
    mock_db_session,
):
    filters = UnifiedPropertyFilter(search_query="sunny balcony", sort_by=SortBy.newest)

    with (
        patch(
            "app.services.property.search_orchestration.apply_statement_timeout",
            new_callable=AsyncMock,
        ),
        patch(
            "app.services.property.search_orchestration.pause_stale_flatmate_listings",
            new_callable=AsyncMock,
        ),
        patch(
            "app.services.property.search_orchestration.get_unified_properties_optimized",
            new_callable=AsyncMock,
        ) as mock_search,
    ):
        mock_search.return_value = ([], None, None)

        await run_property_search(
            mock_db_session,
            filters,
            None,
            {},
            20,
            semantic_required=True,
            force_semantic_relevance=True,
        )

    passed_filters = mock_search.await_args.args[1]
    assert passed_filters is not filters
    assert passed_filters.semantic_search is True
    assert passed_filters.sort_by == SortBy.relevance
    assert filters.semantic_search is False
    assert filters.sort_by == SortBy.newest


@pytest.mark.asyncio
async def test_run_property_search_maps_transient_db_errors_to_503(mock_db_session):
    filters = UnifiedPropertyFilter()

    with (
        patch(
            "app.services.property.search_orchestration.apply_statement_timeout",
            new_callable=AsyncMock,
        ),
        patch(
            "app.services.property.search_orchestration.pause_stale_flatmate_listings",
            new_callable=AsyncMock,
        ),
        patch(
            "app.services.property.search_orchestration.get_unified_properties_optimized",
            new_callable=AsyncMock,
            side_effect=SQLAlchemyError(
                "(ECHECKOUTTIMEOUT) unable to check out connection from the pool"
            ),
        ),
        pytest.raises(ServiceUnavailableException) as exc_info,
    ):
        await run_property_search(
            mock_db_session,
            filters,
            11,
            {},
            20,
            endpoint_name="get_properties_list",
        )

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail == (
        "Property search is temporarily unavailable. Please retry shortly."
    )
    assert exc_info.value.details == {
        "error_code": "ECHECKOUTTIMEOUT",
        "endpoint": "get_properties_list",
    }


@pytest.mark.asyncio
async def test_run_property_search_cache_hit_uses_no_db(mock_db_session):
    """A cached anonymous first page returns before any statement, so it holds no pool connection."""
    cached = (["row"], None, 3)
    with (
        patch(
            "app.services.property.search_orchestration.cached_first_page",
            new_callable=AsyncMock,
            return_value=cached,
        ) as mock_cached,
        patch(
            "app.services.property.search_orchestration.apply_statement_timeout",
            new_callable=AsyncMock,
        ) as mock_timeout,
        patch(
            "app.services.property.search_orchestration.pause_stale_flatmate_listings",
            new_callable=AsyncMock,
        ) as mock_pause,
        patch(
            "app.services.property.search_orchestration.get_unified_properties_optimized",
            new_callable=AsyncMock,
        ) as mock_search,
    ):
        result = await run_property_search(mock_db_session, UnifiedPropertyFilter(), None, {}, 100, with_total=True)

    assert result == cached
    mock_cached.assert_awaited_once_with(UnifiedPropertyFilter(), None, {}, 100, with_total=True)
    mock_timeout.assert_not_awaited()
    mock_pause.assert_not_awaited()
    mock_search.assert_not_awaited()
    mock_db_session.execute.assert_not_called()


@pytest.mark.asyncio
async def test_cached_first_page_skips_signed_in_and_later_pages():
    from app.services.property.search import cached_first_page

    with patch(
        "app.services.property.search.PropertyCacheManager.get_cached_properties",
        new_callable=AsyncMock,
        return_value={"items": [], "has_more": False, "next": None, "total": 0},
    ) as mock_get:
        assert await cached_first_page(UnifiedPropertyFilter(), 7, {}, 10) is None
        assert await cached_first_page(UnifiedPropertyFilter(), None, {"o": 10}, 10) is None
        mock_get.assert_not_awaited()
        assert await cached_first_page(UnifiedPropertyFilter(), None, {}, 10, with_total=True) == ([], None, 0)
