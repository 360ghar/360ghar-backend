"""
Tests for tour short share codes.

Covers short-code generation (alphabet, length, collision retry, exhaustion)
and assignment on publish (set once, idempotent on republish).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import TourStatus
from app.models.tours import Scene, Tour
from app.services.tour.tours import (
    _SHORT_ALPHABET,
    generate_short_code,
    publish_tour,
)


def _db_returning(scalars: list) -> MagicMock:
    """Mock AsyncSession whose execute() yields scalar_one_or_none() values in order."""
    db = MagicMock(spec=AsyncSession)
    results = []
    for value in scalars:
        result = MagicMock()
        result.scalar_one_or_none.return_value = value
        results.append(result)
    db.execute = AsyncMock(side_effect=results)
    return db


def _publishable_tour(short_code: str | None = None) -> Tour:
    tour = Tour(
        id="tour-id",
        user_id=123,
        title="Test Tour",
        status=TourStatus.draft,
        is_public=False,
    )
    tour.short_code = short_code
    tour.scenes = [
        Scene(id="scene-1", tour_id="tour-id", image_url="https://cdn.example.com/pano.jpg")
    ]
    return tour


class TestGenerateShortCode:
    @pytest.mark.asyncio
    async def test_code_uses_alphabet_and_length(self):
        db = _db_returning([None])

        code = await generate_short_code(db)

        assert len(code) == 6
        assert all(char in _SHORT_ALPHABET for char in code)

    @pytest.mark.asyncio
    async def test_retries_on_collision(self):
        db = _db_returning(["existing-tour-id", "existing-tour-id", None])

        code = await generate_short_code(db)

        assert len(code) == 6
        assert db.execute.await_count == 3

    @pytest.mark.asyncio
    async def test_raises_after_exhausting_retries(self):
        db = _db_returning(["existing-tour-id"] * 5)

        with pytest.raises(RuntimeError, match="short code"):
            await generate_short_code(db)

        assert db.execute.await_count == 5


class TestPublishAssignsShortCode:
    @pytest.mark.asyncio
    async def test_publish_assigns_short_code_when_missing(self):
        db = MagicMock(spec=AsyncSession)
        db.commit = AsyncMock()
        db.rollback = AsyncMock()
        tour = _publishable_tour(short_code=None)

        with (
            patch("app.services.tour.tours.get_tour", new_callable=AsyncMock) as mock_get_tour,
            patch(
                "app.services.tour.tours.generate_short_code", new_callable=AsyncMock
            ) as mock_generate,
        ):
            mock_get_tour.return_value = tour
            mock_generate.return_value = "abc234"

            await publish_tour(db=db, tour_id="tour-id", user_id=123)

        assert tour.short_code == "abc234"
        mock_generate.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_republish_keeps_existing_short_code(self):
        db = MagicMock(spec=AsyncSession)
        db.commit = AsyncMock()
        tour = _publishable_tour(short_code="kept99")

        with (
            patch("app.services.tour.tours.get_tour", new_callable=AsyncMock) as mock_get_tour,
            patch(
                "app.services.tour.tours.generate_short_code", new_callable=AsyncMock
            ) as mock_generate,
        ):
            mock_get_tour.return_value = tour

            await publish_tour(db=db, tour_id="tour-id", user_id=123)

        assert tour.short_code == "kept99"
        mock_generate.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_publish_retries_short_code_on_integrity_error(self):
        db = MagicMock(spec=AsyncSession)
        db.commit = AsyncMock(
            side_effect=[IntegrityError("stmt", "params", Exception("dup")), None]
        )
        db.rollback = AsyncMock()
        tour = _publishable_tour(short_code=None)

        with (
            patch("app.services.tour.tours.get_tour", new_callable=AsyncMock) as mock_get_tour,
            patch(
                "app.services.tour.tours.generate_short_code", new_callable=AsyncMock
            ) as mock_generate,
        ):
            mock_get_tour.return_value = tour
            mock_generate.side_effect = ["first1", "retry2"]

            await publish_tour(db=db, tour_id="tour-id", user_id=123)

        assert tour.short_code == "retry2"
        assert mock_generate.await_count == 2
        db.rollback.assert_awaited_once()
        assert db.commit.await_count == 2
