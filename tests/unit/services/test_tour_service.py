"""
Tests for tour service response loading.

These tests ensure service methods return fully-loaded ORM entities suitable
for FastAPI response serialization (avoid async lazy-loading at response time).
"""

from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException, status
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import TourStatus
from app.models.tours import Tour
from app.schemas.tour import TourCreate, TourUpdate


class TestTourServiceResponseLoading:
    """Tests for ensuring tour services return eagerly-loaded entities."""

    @pytest.mark.asyncio
    async def test_create_tour_returns_loaded_tour(self):
        """create_tour returns the reloaded tour with scenes/hotspots eager-loaded."""
        from app.services.tour import create_tour

        db = MagicMock(spec=AsyncSession)
        db.add = MagicMock()
        db.commit = AsyncMock()

        tour_data = TourCreate(title="Test Tour")
        expected = Tour(
            id="tour-id",
            user_id=123,
            title="Test Tour",
            description=None,
            status=TourStatus.draft,
            is_public=False,
        )

        with patch("app.services.tour.get_tour", new_callable=AsyncMock) as mock_get_tour:
            mock_get_tour.return_value = expected

            result = await create_tour(db=db, user_id=123, data=tour_data)

        added_tour = db.add.call_args[0][0]
        assert isinstance(added_tour, Tour)
        assert mock_get_tour.await_count == 1
        assert mock_get_tour.await_args.kwargs["tour_id"] == added_tour.id
        assert mock_get_tour.await_args.kwargs["include_scenes"] is True
        assert result is expected

    @pytest.mark.asyncio
    async def test_update_tour_returns_loaded_tour(self):
        """update_tour returns the reloaded tour with scenes/hotspots eager-loaded."""
        from app.services.tour import update_tour

        db = MagicMock(spec=AsyncSession)
        db.commit = AsyncMock()

        initial = Tour(
            id="tour-id",
            user_id=123,
            title="Old Title",
            description=None,
            status=TourStatus.draft,
            is_public=False,
        )
        expected = Tour(
            id="tour-id",
            user_id=123,
            title="New Title",
            description=None,
            status=TourStatus.draft,
            is_public=False,
        )

        tour_update = TourUpdate(title="New Title")

        with patch("app.services.tour.get_tour", new_callable=AsyncMock) as mock_get_tour:
            mock_get_tour.side_effect = [initial, expected]

            result = await update_tour(
                db=db,
                tour_id="tour-id",
                user_id=123,
                data=tour_update,
            )

        assert mock_get_tour.await_count == 2
        assert mock_get_tour.await_args_list[0].kwargs["include_scenes"] is False
        assert mock_get_tour.await_args_list[1].kwargs["include_scenes"] is True
        assert result is expected


class TestTourServiceAccessControl:
    """Tests for tour access control behavior in service layer."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("tour_status", "is_public", "tour_owner_id", "request_user_id", "expected_error"),
        [
            (TourStatus.draft, False, 123, None, status.HTTP_404_NOT_FOUND),
            (TourStatus.draft, False, 123, 999, status.HTTP_403_FORBIDDEN),
            (TourStatus.draft, False, 123, 123, None),
            (TourStatus.published, True, 123, None, None),
            (TourStatus.published, True, 123, 999, None),
            (TourStatus.published, False, 123, None, status.HTTP_404_NOT_FOUND),
        ],
    )
    async def test_get_tour_enforces_public_or_owner_access(
        self,
        tour_status: TourStatus,
        is_public: bool,
        tour_owner_id: int,
        request_user_id: int | None,
        expected_error: int | None,
    ) -> None:
        from app.services.tour import get_tour

        db = MagicMock(spec=AsyncSession)
        db.execute = AsyncMock()

        expected_tour = Tour(
            id="tour-id",
            user_id=tour_owner_id,
            title="Test Tour",
            description=None,
            status=tour_status,
            is_public=is_public,
        )

        result = MagicMock()
        result.scalar_one_or_none.return_value = expected_tour
        db.execute.return_value = result

        if expected_error is not None:
            with pytest.raises(HTTPException) as exc:
                await get_tour(
                    db=db,
                    tour_id="tour-id",
                    user_id=request_user_id,
                    include_scenes=False,
                )
            assert exc.value.status_code == expected_error
            return

        tour = await get_tour(
            db=db,
            tour_id="tour-id",
            user_id=request_user_id,
            include_scenes=False,
        )
        assert tour is expected_tour
