"""
Tests for base repository pattern.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.users import User  # Use a real model for testing
from app.repositories.base import BaseRepository


class TestBaseRepository:
    """Tests for BaseRepository class."""

    @pytest.fixture
    def mock_session(self):
        """Create a mock async session."""
        session = AsyncMock(spec=AsyncSession)
        return session

    @pytest.fixture
    def repository(self, mock_session):
        """Create a base repository instance."""
        return BaseRepository(User, mock_session)

    @pytest.mark.asyncio
    async def test_get_by_id(self, repository, mock_session):
        """Test getting entity by ID."""
        mock_entity = MagicMock()
        mock_entity.id = 1
        mock_session.get.return_value = mock_entity

        result = await repository.get(1)

        assert result == mock_entity
        mock_session.get.assert_called_once_with(User, 1)

    @pytest.mark.asyncio
    async def test_get_by_id_not_found(self, repository, mock_session):
        """Test getting non-existent entity."""
        mock_session.get.return_value = None

        result = await repository.get(999)

        assert result is None

    @pytest.mark.asyncio
    async def test_get_with_relations(self, repository, mock_session):
        """Test getting entity with relationships."""
        mock_entity = MagicMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_entity
        mock_session.execute.return_value = mock_result

        result = await repository.get_with_relations(1, ["agent"])

        assert result == mock_entity

    @pytest.mark.asyncio
    async def test_list_entities(self, repository, mock_session):
        """Test listing entities."""
        mock_entities = [MagicMock(), MagicMock()]
        mock_result = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = mock_entities
        mock_result.scalars.return_value = mock_scalars
        mock_session.execute.return_value = mock_result

        result = await repository.list()

        assert result == mock_entities

    @pytest.mark.asyncio
    async def test_list_with_filters(self, repository, mock_session):
        """Test listing entities with filters."""
        mock_entities = [MagicMock()]
        mock_result = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = mock_entities
        mock_result.scalars.return_value = mock_scalars
        mock_session.execute.return_value = mock_result

        result = await repository.list(filters={"is_active": True})

        assert result == mock_entities

    @pytest.mark.asyncio
    async def test_list_with_pagination(self, repository, mock_session):
        """Test listing entities with pagination."""
        mock_entities = [MagicMock()]
        mock_result = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = mock_entities
        mock_result.scalars.return_value = mock_scalars
        mock_session.execute.return_value = mock_result

        result = await repository.list(skip=10, limit=20)

        assert result == mock_entities

    @pytest.mark.asyncio
    async def test_list_with_order_by_ascending(self, repository, mock_session):
        """Test listing entities with ascending order."""
        mock_entities = []
        mock_result = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = mock_entities
        mock_result.scalars.return_value = mock_scalars
        mock_session.execute.return_value = mock_result

        result = await repository.list(order_by="full_name")

        assert result == mock_entities

    @pytest.mark.asyncio
    async def test_list_with_order_by_descending(self, repository, mock_session):
        """Test listing entities with descending order."""
        mock_entities = []
        mock_result = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = mock_entities
        mock_result.scalars.return_value = mock_scalars
        mock_session.execute.return_value = mock_result

        result = await repository.list(order_by="-created_at")

        assert result == mock_entities

    @pytest.mark.asyncio
    async def test_count_entities(self, repository, mock_session):
        """Test counting entities."""
        mock_result = MagicMock()
        mock_result.scalar_one.return_value = 42
        mock_session.execute.return_value = mock_result

        result = await repository.count()

        assert result == 42

    @pytest.mark.asyncio
    async def test_count_with_filters(self, repository, mock_session):
        """Test counting entities with filters."""
        mock_result = MagicMock()
        mock_result.scalar_one.return_value = 10
        mock_session.execute.return_value = mock_result

        result = await repository.count(filters={"is_active": True})

        assert result == 10

    @pytest.mark.asyncio
    async def test_create_entity(self, repository, mock_session):
        """Test creating an entity."""
        mock_entity = MagicMock()
        mock_entity.id = 1

        result = await repository.create(mock_entity)

        mock_session.add.assert_called_once_with(mock_entity)
        mock_session.flush.assert_called_once()
        mock_session.refresh.assert_called_once_with(mock_entity)
        assert result == mock_entity

    @pytest.mark.asyncio
    async def test_update_entity(self, repository, mock_session):
        """Test updating an entity."""
        mock_entity = MagicMock()
        mock_entity.id = 1
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_entity
        mock_session.execute.return_value = mock_result

        result = await repository.update(1, {"full_name": "updated"})

        assert result == mock_entity

    @pytest.mark.asyncio
    async def test_update_entity_not_found(self, repository, mock_session):
        """Test updating non-existent entity."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        result = await repository.update(999, {"full_name": "updated"})

        assert result is None

    @pytest.mark.asyncio
    async def test_delete_entity(self, repository, mock_session):
        """Test deleting an entity."""
        mock_entity = MagicMock()
        mock_session.get.return_value = mock_entity

        result = await repository.delete(1)

        assert result is True
        mock_session.delete.assert_called_once_with(mock_entity)
        mock_session.flush.assert_called_once()

    @pytest.mark.asyncio
    async def test_delete_entity_not_found(self, repository, mock_session):
        """Test deleting non-existent entity."""
        mock_session.get.return_value = None

        result = await repository.delete(999)

        assert result is False
        mock_session.delete.assert_not_called()

    @pytest.mark.asyncio
    async def test_exists_true(self, repository, mock_session):
        """Test checking entity exists."""
        mock_result = MagicMock()
        mock_result.scalar_one.return_value = 1
        mock_session.execute.return_value = mock_result

        result = await repository.exists(1)

        assert result is True

    @pytest.mark.asyncio
    async def test_exists_false(self, repository, mock_session):
        """Test checking entity does not exist."""
        mock_result = MagicMock()
        mock_result.scalar_one.return_value = 0
        mock_session.execute.return_value = mock_result

        result = await repository.exists(999)

        assert result is False
