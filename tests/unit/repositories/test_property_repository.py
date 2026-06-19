"""
Tests for property repository.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.property_repository import PropertyRepository
from app.schemas.property import SortBy


class TestPropertyRepository:
    """Tests for PropertyRepository class."""

    @pytest.fixture
    def mock_session(self):
        """Create a mock async session."""
        session = AsyncMock(spec=AsyncSession)
        return session

    @pytest.fixture
    def repository(self, mock_session):
        """Create a property repository instance."""
        return PropertyRepository(mock_session)

    @pytest.mark.asyncio
    async def test_get_property_with_owner(self, repository, mock_session):
        """Test getting property with owner."""
        mock_property = MagicMock()
        mock_property.id = 1
        mock_property.title = "Test Property"
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_property
        mock_session.execute.return_value = mock_result

        result = await repository.get_property_with_owner(1)

        assert result == mock_property
        stmt = mock_session.execute.await_args.args[0]
        option_paths = [str(option.path) for option in stmt._with_options]
        assert any("Property.property_amenities" in path for path in option_paths)
        assert any("PropertyAmenity.amenity" in path for path in option_paths)

    @pytest.mark.asyncio
    async def test_get_property_with_owner_not_found(self, repository, mock_session):
        """Test getting non-existent property."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        result = await repository.get_property_with_owner(999)

        assert result is None

    @pytest.mark.asyncio
    async def test_get_properties_filtered_basic(self, repository, mock_session):
        """Test getting filtered properties."""
        mock_properties = [MagicMock(), MagicMock()]
        mock_result = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = mock_properties
        mock_result.scalars.return_value = mock_scalars
        mock_session.execute.return_value = mock_result

        result = await repository.get_properties_filtered(
            filters={"city": "Mumbai"},
            skip=0,
            limit=20,
            sort_by=SortBy.newest,
            sort_order="desc",
        )

        assert result == mock_properties

    @pytest.mark.asyncio
    async def test_get_properties_filtered_with_owner(self, repository, mock_session):
        """Test getting properties with owner loaded."""
        mock_properties = [MagicMock()]
        mock_result = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = mock_properties
        mock_result.scalars.return_value = mock_scalars
        mock_session.execute.return_value = mock_result

        result = await repository.get_properties_filtered(
            filters={},
            skip=0,
            limit=10,
            sort_by=SortBy.price_low,
            sort_order="asc",
            include_owner=True,
        )

        assert result == mock_properties

    @pytest.mark.asyncio
    async def test_get_properties_filtered_with_images(self, repository, mock_session):
        """Test getting properties with images loaded."""
        mock_properties = [MagicMock()]
        mock_result = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = mock_properties
        mock_result.scalars.return_value = mock_scalars
        mock_session.execute.return_value = mock_result

        result = await repository.get_properties_filtered(
            filters={},
            skip=0,
            limit=10,
            sort_by=SortBy.price_high,
            sort_order="desc",
            include_images=True,
        )

        assert result == mock_properties

    @pytest.mark.asyncio
    async def test_get_properties_filtered_with_location(self, repository, mock_session):
        """Test getting properties with location filters."""
        mock_properties = [MagicMock()]
        mock_result = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = mock_properties
        mock_result.scalars.return_value = mock_scalars
        mock_session.execute.return_value = mock_result

        result = await repository.get_properties_filtered(
            filters={
                "latitude": 19.0760,
                "longitude": 72.8777,
                "radius_km": 10,
            },
            skip=0,
            limit=20,
            sort_by=SortBy.distance,
            sort_order="asc",
        )

        assert result == mock_properties

    @pytest.mark.asyncio
    async def test_get_properties_within_radius(self, repository, mock_session):
        """Test getting properties within radius."""
        mock_properties = [MagicMock()]
        mock_result = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = mock_properties
        mock_result.scalars.return_value = mock_scalars
        mock_session.execute.return_value = mock_result

        result = await repository.get_properties_within_radius(
            latitude=19.0760,
            longitude=72.8777,
            radius_km=5,
            filters={"purpose": "rent"},
            skip=0,
            limit=10,
        )

        assert result == mock_properties

    @pytest.mark.asyncio
    async def test_count_filtered(self, repository, mock_session):
        """Test counting filtered properties."""
        mock_result = MagicMock()
        mock_result.scalar_one.return_value = 25
        mock_session.execute.return_value = mock_result

        result = await repository.count_filtered({"city": "Mumbai"})

        assert result == 25

    def test_apply_filters_price_range(self, repository):
        """Test applying price range filter."""
        mock_stmt = MagicMock()
        mock_stmt.where.return_value = mock_stmt

        result = repository._apply_filters(mock_stmt, {"price_range": (50000, 100000)})

        assert result is not None

    def test_apply_filters_bedrooms(self, repository):
        """Test applying bedrooms filter."""
        mock_stmt = MagicMock()
        mock_stmt.where.return_value = mock_stmt

        result = repository._apply_filters(mock_stmt, {"bedrooms": 2})

        assert result is not None

    def test_apply_filters_empty(self, repository):
        """Test applying no filters."""
        mock_stmt = MagicMock()

        result = repository._apply_filters(mock_stmt, None)

        assert result == mock_stmt

    def test_apply_filters_none_value(self, repository):
        """Test applying filter with None value."""
        mock_stmt = MagicMock()

        result = repository._apply_filters(mock_stmt, {"city": None})

        assert result == mock_stmt

    def test_apply_sorting_price_low(self, repository):
        """Test sorting by price low."""
        mock_stmt = MagicMock()
        mock_stmt.order_by.return_value = mock_stmt

        result = repository._apply_sorting(mock_stmt, SortBy.price_low, "asc")

        mock_stmt.order_by.assert_called_once()

    def test_apply_sorting_price_high(self, repository):
        """Test sorting by price high."""
        mock_stmt = MagicMock()
        mock_stmt.order_by.return_value = mock_stmt

        result = repository._apply_sorting(mock_stmt, SortBy.price_high, "desc")

        mock_stmt.order_by.assert_called_once()

    def test_apply_sorting_newest(self, repository):
        """Test sorting by newest."""
        mock_stmt = MagicMock()
        mock_stmt.order_by.return_value = mock_stmt

        result = repository._apply_sorting(mock_stmt, SortBy.newest, "desc")

        mock_stmt.order_by.assert_called_once()

    def test_apply_sorting_popular(self, repository):
        """Test sorting by popularity."""
        mock_stmt = MagicMock()
        mock_stmt.order_by.return_value = mock_stmt

        result = repository._apply_sorting(mock_stmt, SortBy.popular, "desc")

        mock_stmt.order_by.assert_called_once()

    def test_apply_sorting_distance_requires_expr(self, repository):
        """Test that distance sorting requires distance expression."""
        mock_stmt = MagicMock()

        with pytest.raises(ValueError, match="distance expression"):
            repository._apply_sorting(mock_stmt, SortBy.distance, "asc")

    def test_apply_sorting_distance_with_expr(self, repository):
        """Test sorting by distance with expression."""
        mock_stmt = MagicMock()
        mock_stmt.order_by.return_value = mock_stmt
        mock_distance_expr = MagicMock()
        mock_distance_expr.asc.return_value = mock_distance_expr

        result = repository._apply_sorting(
            mock_stmt, SortBy.distance, "asc", distance_expr=mock_distance_expr
        )

        mock_stmt.order_by.assert_called_once()

    def test_apply_sorting_relevance_fallback(self, repository):
        """Test relevance sorting falls back to created_at."""
        mock_stmt = MagicMock()
        mock_stmt.order_by.return_value = mock_stmt

        result = repository._apply_sorting(mock_stmt, SortBy.relevance, "desc")

        mock_stmt.order_by.assert_called_once()

    def test_apply_sorting_none_raises(self, repository):
        """Test that None sort_by raises error."""
        mock_stmt = MagicMock()

        with pytest.raises(ValueError, match="Sort option is required"):
            repository._apply_sorting(mock_stmt, None, "asc")

    def test_apply_sorting_invalid_order_defaults_to_asc(self, repository):
        """Test invalid sort order defaults to ascending."""
        mock_stmt = MagicMock()
        mock_stmt.order_by.return_value = mock_stmt

        result = repository._apply_sorting(mock_stmt, SortBy.price_low, "invalid")

        mock_stmt.order_by.assert_called_once()
