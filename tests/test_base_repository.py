"""
Tests for base repository pattern.

Tests cover:
- CRUD operations (create, read, update, delete)
- Repository interface
- Edge cases and error handling
"""
import pytest
from unittest.mock import AsyncMock, MagicMock
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.base import BaseRepository


class TestBaseRepositoryGet:
    """Tests for BaseRepository.get method."""

    @pytest.mark.asyncio
    async def test_get_existing_entity(self) -> None:
        """Should return entity when found."""
        mock_session = AsyncMock(spec=AsyncSession)
        mock_entity = MagicMock(id=1, name="Test")
        mock_session.get.return_value = mock_entity

        # Use MagicMock as model class
        MockModel = MagicMock()
        repo = BaseRepository(MockModel, mock_session)
        result = await repo.get(1)

        assert result == mock_entity
        mock_session.get.assert_called_once_with(MockModel, 1)

    @pytest.mark.asyncio
    async def test_get_non_existing_entity(self) -> None:
        """Should return None when entity not found."""
        mock_session = AsyncMock(spec=AsyncSession)
        mock_session.get.return_value = None

        MockModel = MagicMock()
        repo = BaseRepository(MockModel, mock_session)
        result = await repo.get(999)

        assert result is None


class TestBaseRepositoryCreate:
    """Tests for BaseRepository.create method."""

    @pytest.mark.asyncio
    async def test_create_entity(self) -> None:
        """Should add entity to session and return it."""
        mock_session = AsyncMock(spec=AsyncSession)
        mock_entity = MagicMock(id=1, name="New Entity")

        MockModel = MagicMock()
        repo = BaseRepository(MockModel, mock_session)
        result = await repo.create(mock_entity)

        assert result == mock_entity
        mock_session.add.assert_called_once_with(mock_entity)
        mock_session.flush.assert_called_once()
        mock_session.refresh.assert_called_once_with(mock_entity)


class TestBaseRepositoryDelete:
    """Tests for BaseRepository.delete method."""

    @pytest.mark.asyncio
    async def test_delete_existing_entity(self) -> None:
        """Should delete entity and return True."""
        mock_session = AsyncMock(spec=AsyncSession)
        mock_entity = MagicMock(id=1)
        mock_session.get.return_value = mock_entity

        MockModel = MagicMock()
        repo = BaseRepository(MockModel, mock_session)
        result = await repo.delete(1)

        assert result is True
        mock_session.delete.assert_called_once_with(mock_entity)
        mock_session.flush.assert_called_once()

    @pytest.mark.asyncio
    async def test_delete_non_existing_entity(self) -> None:
        """Should return False when entity not found."""
        mock_session = AsyncMock(spec=AsyncSession)
        mock_session.get.return_value = None

        MockModel = MagicMock()
        repo = BaseRepository(MockModel, mock_session)
        result = await repo.delete(999)

        assert result is False
        mock_session.delete.assert_not_called()


class TestBaseRepositoryInterface:
    """Tests for BaseRepository interface and initialization."""

    def test_repository_stores_model_and_session(self) -> None:
        """Repository should store model and session references."""
        mock_session = AsyncMock(spec=AsyncSession)
        MockModel = MagicMock()

        repo = BaseRepository(MockModel, mock_session)

        assert repo.model == MockModel
        assert repo.session == mock_session

    @pytest.mark.asyncio
    async def test_get_calls_session_get(self) -> None:
        """get() should delegate to session.get()."""
        mock_session = AsyncMock(spec=AsyncSession)
        mock_session.get.return_value = MagicMock(id=5)

        MockModel = MagicMock()
        repo = BaseRepository(MockModel, mock_session)

        await repo.get(5)

        mock_session.get.assert_called_once_with(MockModel, 5)

    @pytest.mark.asyncio
    async def test_create_adds_and_flushes(self) -> None:
        """create() should add entity, flush, and refresh."""
        mock_session = AsyncMock(spec=AsyncSession)
        mock_entity = MagicMock()

        MockModel = MagicMock()
        repo = BaseRepository(MockModel, mock_session)

        await repo.create(mock_entity)

        mock_session.add.assert_called_once()
        mock_session.flush.assert_called_once()
        mock_session.refresh.assert_called_once()
