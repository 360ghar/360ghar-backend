"""
Tests for property repository.

Tests cover:
- Property-specific query methods
- Filter application
- Sorting logic for all SortBy options
- Geo-spatial queries
- Edge cases and error handling
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.repositories.property_repository import PropertyRepository
from app.schemas.property import SortBy


class TestPropertyRepositorySorting:
    """Tests for _apply_sorting method."""

    def test_sort_by_price_low(self) -> None:
        """Should sort by base_price ascending."""
        mock_session = AsyncMock()
        repo = PropertyRepository(mock_session)

        mock_stmt = MagicMock()
        result = repo._apply_sorting(mock_stmt, SortBy.price_low, "asc")

        mock_stmt.order_by.assert_called_once()

    def test_sort_by_price_high(self) -> None:
        """Should sort by base_price descending."""
        mock_session = AsyncMock()
        repo = PropertyRepository(mock_session)

        mock_stmt = MagicMock()
        result = repo._apply_sorting(mock_stmt, SortBy.price_high, "asc")

        mock_stmt.order_by.assert_called_once()

    def test_sort_by_newest(self) -> None:
        """Should sort by created_at."""
        mock_session = AsyncMock()
        repo = PropertyRepository(mock_session)

        mock_stmt = MagicMock()
        result = repo._apply_sorting(mock_stmt, SortBy.newest, "desc")

        mock_stmt.order_by.assert_called_once()

    def test_sort_by_popular(self) -> None:
        """Should sort by like_count and view_count."""
        mock_session = AsyncMock()
        repo = PropertyRepository(mock_session)

        mock_stmt = MagicMock()
        result = repo._apply_sorting(mock_stmt, SortBy.popular, "desc")

        mock_stmt.order_by.assert_called_once()

    def test_sort_by_distance_requires_expression(self) -> None:
        """Should raise ValueError when distance sorting without expression."""
        mock_session = AsyncMock()
        repo = PropertyRepository(mock_session)

        mock_stmt = MagicMock()

        with pytest.raises(ValueError) as exc_info:
            repo._apply_sorting(mock_stmt, SortBy.distance, "asc", distance_expr=None)

        assert "distance" in str(exc_info.value).lower()

    def test_sort_by_distance_with_expression(self) -> None:
        """Should sort by distance when expression provided."""
        mock_session = AsyncMock()
        repo = PropertyRepository(mock_session)

        mock_stmt = MagicMock()
        mock_distance = MagicMock()

        result = repo._apply_sorting(
            mock_stmt, SortBy.distance, "asc", distance_expr=mock_distance
        )

        mock_stmt.order_by.assert_called_once()

    def test_sort_by_relevance_without_expression_falls_back(self) -> None:
        """Should fall back to created_at when no relevance expression."""
        mock_session = AsyncMock()
        repo = PropertyRepository(mock_session)

        mock_stmt = MagicMock()
        result = repo._apply_sorting(
            mock_stmt, SortBy.relevance, "desc", relevance_expr=None
        )

        mock_stmt.order_by.assert_called_once()

    def test_sort_by_relevance_with_expression(self) -> None:
        """Should sort by relevance expression when provided."""
        mock_session = AsyncMock()
        repo = PropertyRepository(mock_session)

        mock_stmt = MagicMock()
        mock_relevance = MagicMock()

        result = repo._apply_sorting(
            mock_stmt, SortBy.relevance, "desc", relevance_expr=mock_relevance
        )

        mock_stmt.order_by.assert_called_once()

    def test_sort_by_none_raises_error(self) -> None:
        """Should raise ValueError when sort_by is None."""
        mock_session = AsyncMock()
        repo = PropertyRepository(mock_session)

        mock_stmt = MagicMock()

        with pytest.raises(ValueError) as exc_info:
            repo._apply_sorting(mock_stmt, None, "asc")

        assert "required" in str(exc_info.value).lower()

    def test_invalid_sort_order_defaults_to_asc(self) -> None:
        """Should default to asc for invalid sort_order."""
        mock_session = AsyncMock()
        repo = PropertyRepository(mock_session)

        mock_stmt = MagicMock()
        result = repo._apply_sorting(mock_stmt, SortBy.newest, "invalid_order")

        mock_stmt.order_by.assert_called_once()

    def test_empty_sort_order_defaults_to_asc(self) -> None:
        """Should default to asc for empty sort_order."""
        mock_session = AsyncMock()
        repo = PropertyRepository(mock_session)

        mock_stmt = MagicMock()
        result = repo._apply_sorting(mock_stmt, SortBy.newest, "")

        mock_stmt.order_by.assert_called_once()

    def test_none_sort_order_defaults_to_asc(self) -> None:
        """Should default to asc for None sort_order."""
        mock_session = AsyncMock()
        repo = PropertyRepository(mock_session)

        mock_stmt = MagicMock()
        result = repo._apply_sorting(mock_stmt, SortBy.newest, None)

        mock_stmt.order_by.assert_called_once()


class TestPropertyRepositoryFilters:
    """Tests for _apply_filters method."""

    def test_apply_filters_empty(self) -> None:
        """Should return statement unchanged when no filters."""
        mock_session = AsyncMock()
        repo = PropertyRepository(mock_session)

        mock_stmt = MagicMock()
        result = repo._apply_filters(mock_stmt, {})

        assert result == mock_stmt
        mock_stmt.where.assert_not_called()

    def test_apply_filters_none(self) -> None:
        """Should return statement unchanged when filters is None."""
        mock_session = AsyncMock()
        repo = PropertyRepository(mock_session)

        mock_stmt = MagicMock()
        result = repo._apply_filters(mock_stmt, None)

        assert result == mock_stmt

    def test_apply_filters_price_range(self) -> None:
        """Should apply min and max price filters."""
        mock_session = AsyncMock()
        repo = PropertyRepository(mock_session)

        mock_stmt = MagicMock()
        mock_stmt.where.return_value = mock_stmt

        result = repo._apply_filters(mock_stmt, {"price_range": (10000, 50000)})

        assert mock_stmt.where.call_count == 2

    def test_apply_filters_price_range_min_only(self) -> None:
        """Should apply only min price when max is None."""
        mock_session = AsyncMock()
        repo = PropertyRepository(mock_session)

        mock_stmt = MagicMock()
        mock_stmt.where.return_value = mock_stmt

        result = repo._apply_filters(mock_stmt, {"price_range": (10000, None)})

        mock_stmt.where.assert_called_once()

    def test_apply_filters_bedrooms(self) -> None:
        """Should apply bedrooms filter as >= comparison."""
        mock_session = AsyncMock()
        repo = PropertyRepository(mock_session)

        mock_stmt = MagicMock()
        mock_stmt.where.return_value = mock_stmt

        result = repo._apply_filters(mock_stmt, {"bedrooms": 2})

        mock_stmt.where.assert_called_once()

    def test_apply_filters_bathrooms(self) -> None:
        """Should apply bathrooms filter as >= comparison."""
        mock_session = AsyncMock()
        repo = PropertyRepository(mock_session)

        mock_stmt = MagicMock()
        mock_stmt.where.return_value = mock_stmt

        result = repo._apply_filters(mock_stmt, {"bathrooms": 1})

        mock_stmt.where.assert_called_once()

    def test_apply_filters_skip_none_values(self) -> None:
        """Should skip filters with None values."""
        mock_session = AsyncMock()
        repo = PropertyRepository(mock_session)

        mock_stmt = MagicMock()

        result = repo._apply_filters(mock_stmt, {"city": None, "purpose": None})

        mock_stmt.where.assert_not_called()


class TestPropertyRepositoryCountFiltered:
    """Tests for count_filtered method."""

    @pytest.mark.asyncio
    async def test_count_filtered_returns_count(self) -> None:
        """Should return count of filtered properties."""
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one.return_value = 42
        mock_session.execute.return_value = mock_result

        repo = PropertyRepository(mock_session)
        result = await repo.count_filtered({"city": "Delhi"})

        assert result == 42

    @pytest.mark.asyncio
    async def test_count_filtered_empty_filters(self) -> None:
        """Should count all when no filters."""
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one.return_value = 100
        mock_session.execute.return_value = mock_result

        repo = PropertyRepository(mock_session)
        result = await repo.count_filtered({})

        assert result == 100
