"""
Tests for swipe service module.
"""


import pytest
from sqlalchemy.ext.asyncio import AsyncSession


class TestRecordSwipe:
    """Tests for record_swipe function."""

    @pytest.mark.asyncio
    async def test_record_swipe_like(
        self,
        db_session: AsyncSession,
        test_user_2,
        test_property,
    ):
        """Test recording a like swipe (test_property is owned by test_user)."""
        from app.schemas.property import PropertySwipe
        from app.services.swipe import record_swipe

        swipe_data = PropertySwipe(
            property_id=test_property.id,
            is_liked=True,
        )

        result = await record_swipe(db_session, test_user_2.id, swipe_data)

        assert result is True

    @pytest.mark.asyncio
    async def test_record_swipe_dislike(
        self,
        db_session: AsyncSession,
        test_user_2,
        test_property,
    ):
        """Test recording a dislike swipe (test_property is owned by test_user)."""
        from app.schemas.property import PropertySwipe
        from app.services.swipe import record_swipe

        swipe_data = PropertySwipe(
            property_id=test_property.id,
            is_liked=False,
        )

        result = await record_swipe(db_session, test_user_2.id, swipe_data)

        assert result is True

    @pytest.mark.asyncio
    async def test_record_swipe_own_property_blocked(
        self,
        db_session: AsyncSession,
        test_user,
        test_property,
    ):
        """A user cannot swipe their own property."""
        from app.schemas.property import PropertySwipe
        from app.services.swipe import record_swipe

        swipe_data = PropertySwipe(
            property_id=test_property.id,
            is_liked=True,
        )

        result = await record_swipe(db_session, test_user.id, swipe_data)

        assert result is False

    @pytest.mark.asyncio
    async def test_record_swipe_nonexistent_property(
        self,
        db_session: AsyncSession,
        test_user,
    ):
        """Test recording swipe for non-existent property."""
        from app.schemas.property import PropertySwipe
        from app.services.swipe import record_swipe

        swipe_data = PropertySwipe(
            property_id=99999,
            is_liked=True,
        )

        result = await record_swipe(db_session, test_user.id, swipe_data)

        assert result is False

    @pytest.mark.asyncio
    async def test_record_swipe_update_existing(
        self,
        db_session: AsyncSession,
        test_user_2,
        test_property,
    ):
        """Test updating existing swipe (test_property is owned by test_user)."""
        from app.schemas.property import PropertySwipe
        from app.services.swipe import record_swipe
        from tests.fixtures.factories import SwipeFactory

        # Create an initial swipe by a different user than the owner
        existing = await SwipeFactory.create(
            db_session,
            user=test_user_2,
            property_obj=test_property,
            is_liked=True,
        )

        # Toggle from like to dislike
        swipe_data = PropertySwipe(
            property_id=test_property.id,
            is_liked=not existing.is_liked,
        )

        result = await record_swipe(db_session, test_user_2.id, swipe_data)

        assert result is True


class TestGetSwipeHistory:
    """Tests for get_swipe_history function."""

    @pytest.mark.asyncio
    async def test_get_swipe_history(
        self,
        db_session: AsyncSession,
        test_user,
        test_swipes,
    ):
        """Test getting user's swipe history."""
        from app.schemas.property import UnifiedPropertyFilter
        from app.services.swipe import get_swipe_history

        filters = UnifiedPropertyFilter()
        swipes, next_payload, total = await get_swipe_history(
            db_session,
            test_user.id,
            filters,
            cursor_payload={},
            limit=10,
            is_liked=None,
            with_total=True,
        )

        assert isinstance(swipes, list)
        assert total == len(test_swipes)

    @pytest.mark.asyncio
    async def test_get_swipe_history_liked_only(
        self,
        db_session: AsyncSession,
        test_user,
        test_swipes,
    ):
        """Test getting only liked swipes."""
        from app.schemas.property import UnifiedPropertyFilter
        from app.services.swipe import get_swipe_history

        filters = UnifiedPropertyFilter()
        swipes, _next, _total = await get_swipe_history(
            db_session,
            test_user.id,
            filters,
            cursor_payload={},
            limit=10,
            is_liked=True,
        )

        assert isinstance(swipes, list)
        for swipe in swipes:
            assert swipe.is_liked is True


class TestUndoLastSwipe:
    """Tests for undo_last_swipe function."""

    @pytest.mark.asyncio
    async def test_undo_last_swipe(
        self,
        db_session: AsyncSession,
        test_user,
        test_swipe,
    ):
        """Test undoing last swipe."""
        from app.services.swipe import undo_last_swipe

        result = await undo_last_swipe(db_session, test_user.id)

        assert result is not None
        assert result.user_id == test_user.id

    @pytest.mark.asyncio
    async def test_undo_last_swipe_no_swipes(
        self,
        db_session: AsyncSession,
        test_user_2,
    ):
        """Test undoing swipe when none exist."""
        from app.services.swipe import undo_last_swipe

        result = await undo_last_swipe(db_session, test_user_2.id)

        assert result is None


class TestToggleSwipe:
    """Tests for toggle_swipe function."""

    @pytest.mark.asyncio
    async def test_toggle_swipe_success(
        self,
        db_session: AsyncSession,
        test_user,
        test_swipe,
    ):
        """Test toggling swipe status."""
        from app.services.swipe import toggle_swipe

        original_status = test_swipe.is_liked
        result = await toggle_swipe(db_session, test_swipe.id, test_user.id)

        assert result is not None
        assert result["new_status"] == (not original_status)

    @pytest.mark.asyncio
    async def test_toggle_swipe_wrong_user(
        self,
        db_session: AsyncSession,
        test_user_2,
        test_swipe,
    ):
        """Test toggling swipe for different user fails."""
        from app.services.swipe import toggle_swipe

        result = await toggle_swipe(db_session, test_swipe.id, test_user_2.id)

        assert result is None


class TestGetSwipeStats:
    """Tests for get_swipe_stats function."""

    @pytest.mark.asyncio
    async def test_get_swipe_stats(
        self,
        db_session: AsyncSession,
        test_user,
        test_swipes,
    ):
        """Test getting swipe statistics."""
        from app.services.swipe import get_swipe_stats

        result = await get_swipe_stats(db_session, test_user.id)

        assert "total_swipes" in result
        assert "liked_count" in result
        assert "disliked_count" in result
        assert "like_percentage" in result
        assert result["total_swipes"] == len(test_swipes)

    @pytest.mark.asyncio
    async def test_get_swipe_stats_no_swipes(
        self,
        db_session: AsyncSession,
        test_user_2,
    ):
        """Test getting stats with no swipes."""
        from app.services.swipe import get_swipe_stats

        result = await get_swipe_stats(db_session, test_user_2.id)

        assert result["total_swipes"] == 0
        assert result["like_percentage"] == 0


class TestGetUserLikeForProperty:
    """Tests for get_user_like_for_property function."""

    @pytest.mark.asyncio
    async def test_get_user_like_exists(
        self,
        db_session: AsyncSession,
        test_user,
        test_property,
        test_swipe,
    ):
        """Test getting like status for swiped property."""
        from app.services.swipe import get_user_like_for_property

        result = await get_user_like_for_property(
            db_session,
            test_user.id,
            test_property.id,
        )

        assert result == test_swipe.is_liked

    @pytest.mark.asyncio
    async def test_get_user_like_not_swiped(
        self,
        db_session: AsyncSession,
        test_user,
    ):
        """Test getting like status for unswiped property."""
        from app.services.swipe import get_user_like_for_property

        result = await get_user_like_for_property(
            db_session,
            test_user.id,
            99999,
        )

        assert result is None
