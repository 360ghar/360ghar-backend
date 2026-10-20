"""
Tests for property repository.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.property_repository import PropertyRepository


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
