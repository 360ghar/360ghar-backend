"""
Tests for property service module.
"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import (
    ListingGenderPreference,
    ListingSharingType,
    PropertyPurpose,
    PropertyType,
)


class TestCreateProperty:
    """Tests for create_property function."""

    @pytest.mark.asyncio
    async def test_create_property_success(
        self,
        db_session: AsyncSession,
        test_user,
    ):
        """Test successful property creation."""
        from app.schemas.property import PropertyCreate
        from app.services.property import create_property

        property_data = PropertyCreate(
            title="New Test Property",
            description="A beautiful test property",
            property_type=PropertyType.apartment,
            purpose=PropertyPurpose.rent,
            base_price=Decimal("5000000"),
            monthly_rent=Decimal("50000"),
            city="Mumbai",
            locality="Andheri",
            full_address="123 Test Street, Andheri, Mumbai",
            pincode="400069",
            state="Maharashtra",
            country="India",
            latitude=19.1136,
            longitude=72.8697,
            bedrooms=2,
            bathrooms=2,
            area_sqft=Decimal("1000"),
        )

        # Create mock property result
        mock_result = MagicMock()
        mock_result.id = 1
        mock_result.title = "New Test Property"
        mock_result.owner_id = test_user.id
        mock_result.property_type = PropertyType.apartment

        with patch("app.services.property.crud.PropertyRepository") as mock_repo_class:
            mock_repo = MagicMock()
            mock_property = MagicMock()
            mock_repo.create = AsyncMock(return_value=mock_property)
            mock_repo.get_property_with_owner = AsyncMock(return_value=mock_property)
            mock_repo_class.return_value = mock_repo

            with patch("app.services.property.crud.PropertyCacheManager.invalidate_property_caches", new_callable=AsyncMock):
                with patch("app.services.property.crud.PropertySchema.model_validate", return_value=mock_result):
                    result = await create_property(db_session, property_data, test_user.id, test_user)

                    assert result is not None
                    assert result.title == "New Test Property"
                    assert result.owner_id == test_user.id
                    assert result.property_type == PropertyType.apartment

    @pytest.mark.asyncio
    async def test_create_property_rejects_pg_with_non_rent_purpose(self):
        """Test PG listings are restricted to rent purpose."""
        from app.schemas.property import PropertyCreate

        with pytest.raises(ValidationError):
            PropertyCreate(
                title="Invalid PG",
                property_type=PropertyType.pg,
                purpose=PropertyPurpose.buy,
                base_price=Decimal("18000"),
            )

    @pytest.mark.asyncio
    async def test_create_property_rejects_flatmate_without_monthly_rent(self):
        """Flatmate listings must have a positive monthly_rent at the schema layer."""
        from app.schemas.property import PropertyCreate

        with pytest.raises(ValidationError):
            PropertyCreate(
                title="Flatmate No Rent",
                property_type=PropertyType.flatmate,
                purpose=PropertyPurpose.rent,
                base_price=Decimal("22000"),
            )

    @pytest.mark.asyncio
    async def test_create_property_rejects_pg_with_zero_monthly_rent(self):
        """PG listings with monthly_rent=0 must be rejected at the schema layer."""
        from app.schemas.property import PropertyCreate

        with pytest.raises(ValidationError):
            PropertyCreate(
                title="PG Zero Rent",
                property_type=PropertyType.pg,
                purpose=PropertyPurpose.rent,
                base_price=Decimal("18000"),
                monthly_rent=Decimal("0"),
            )

    @pytest.mark.asyncio
    async def test_create_property_accepts_buy_without_monthly_rent(self):
        """Buy-purpose listings do not require monthly_rent."""
        from app.schemas.property import PropertyCreate

        data = PropertyCreate(
            title="Buy House",
            property_type=PropertyType.house,
            purpose=PropertyPurpose.buy,
            base_price=Decimal("5000000"),
        )
        assert data.monthly_rent is None

    @pytest.mark.asyncio
    async def test_create_property_accepts_short_stay_without_monthly_rent(self):
        """Short-stay listings use daily_rate, not monthly_rent."""
        from app.schemas.property import PropertyCreate

        data = PropertyCreate(
            title="Stay",
            property_type=PropertyType.studio,
            purpose=PropertyPurpose.short_stay,
            base_price=Decimal("3000"),
            daily_rate=Decimal("3000"),
        )
        assert data.monthly_rent is None

    @pytest.mark.asyncio
    async def test_create_property_drops_phantom_cloudinary_url(self):
        """Regression: a phantom hc_properties URL (HTTP 404) is dropped on
        the sync verification path, never persisted to property_images."""
        from app.schemas.property import PropertyCreate
        from app.services.property import create_property
        from app.services.property import crud as crud_mod

        phantom = (
            "https://res.cloudinary.com/ddbhzlzy1/image/upload/360ghar/"
            "hc_properties/00171-ompee-drona-floors-palam-vihar-3bhk-builder-floor/"
            "listing_images/master_bedroom.webp"
        )
        working = (
            "https://res.cloudinary.com/ddbhzlzy1/image/upload/v1781553648/"
            "360ghar/properties/1531/entrance.webp"
        )

        property_data = PropertyCreate(
            title="Phantom Drop Test",
            property_type=PropertyType.apartment,
            purpose=PropertyPurpose.buy,
            base_price=Decimal("5000000"),
            city="Gurugram",
            latitude=28.51,
            longitude=77.03,
            image_urls=[phantom, working],
        )

        actor = MagicMock()
        actor.id = 1
        actor.role = "admin"
        actor.agent_id = None
        owner = MagicMock()
        owner.id = 1
        owner.full_name = "Owner"

        captured_image_urls: list[list[str]] = []

        async def _capture_replace(db, *, property_id, image_urls):
            captured_image_urls.append(image_urls)

        # _verify_and_clean_image_urls drops the phantom, keeps the working URL.
        async def _fake_verify(urls):
            return [u for u in urls if "hc_properties" not in u]

        db_session = AsyncMock(spec=AsyncSession)
        db_session.flush = AsyncMock()

        with (
            patch.object(crud_mod, "PropertyRepository") as mock_repo_class,
            patch.object(crud_mod, "geocode_listing", new=AsyncMock()),
            patch.object(
                crud_mod.PropertyCacheManager,
                "invalidate_property_caches",
                new=AsyncMock(),
            ),
            patch.object(
                crud_mod, "_replace_property_images", side_effect=_capture_replace
            ),
            patch.object(
                crud_mod, "_verify_and_clean_image_urls", side_effect=_fake_verify
            ),
            patch.object(crud_mod, "_schedule_async_image_verification"),
            patch.object(crud_mod, "UserModel", MagicMock(return_value=owner)),
            patch.object(crud_mod.PropertySchema, "model_validate", return_value=MagicMock()),
        ):
            mock_repo = MagicMock()
            mock_property = MagicMock()
            mock_property.id = 999
            mock_property.property_type = PropertyType.apartment
            mock_property.purpose = PropertyPurpose.buy
            mock_property.listing_preferences = {}
            mock_repo.create = AsyncMock(return_value=mock_property)
            mock_repo.get_property_with_owner = AsyncMock(return_value=mock_property)
            mock_repo_class.return_value = mock_repo

            await create_property(db_session, property_data, owner.id, actor)

        # The phantom URL must NOT have been passed to _replace_property_images.
        assert captured_image_urls, "_replace_property_images was never called"
        assert phantom not in captured_image_urls[0]
        assert working in captured_image_urls[0]


class TestGetProperty:
    """Tests for get_property function."""

    @pytest.mark.asyncio
    async def test_get_property_success(
        self,
        db_session: AsyncSession,
        test_property,
    ):
        """Test getting property by ID."""
        from app.services.property import get_property

        result = await get_property(db_session, test_property.id)

        assert result is not None
        assert result.id == test_property.id
        assert result.title == test_property.title

    @pytest.mark.asyncio
    async def test_get_property_not_found(self, db_session: AsyncSession):
        """Test getting non-existent property."""
        from app.core.exceptions import PropertyNotFoundException
        from app.services.property import get_property

        with pytest.raises(PropertyNotFoundException):
            await get_property(db_session, 99999)


class TestUpdateProperty:
    """Tests for update_property function."""

    @pytest.mark.asyncio
    async def test_update_property_success(
        self,
        db_session: AsyncSession,
        test_property,
        test_user,
    ):
        """Test successful property update."""
        from app.schemas.property import PropertyUpdate
        from app.services.property import update_property

        update_data = PropertyUpdate(title="Updated Title")

        # Create mock result
        mock_result = MagicMock()
        mock_result.id = test_property.id
        mock_result.title = "Updated Title"

        with patch("app.services.property.crud.PropertyRepository") as mock_repo_class:
            mock_repo = MagicMock()
            mock_property = MagicMock()
            mock_property.owner_id = test_user.id
            mock_property.owner = None
            mock_repo.get_property_with_owner = AsyncMock(return_value=mock_property)
            mock_repo_class.return_value = mock_repo

            # Mock the db session operations
            with patch.object(db_session, "flush", new_callable=AsyncMock):
                with patch.object(db_session, "refresh", new_callable=AsyncMock):
                    with patch("app.services.property.crud.PropertyCacheManager.invalidate_property_caches", new_callable=AsyncMock):
                        with patch("app.services.property.crud.PropertyCacheManager.invalidate_property_detail_cache", new_callable=AsyncMock):
                            with patch("app.services.property.crud.PropertySchema.model_validate", return_value=mock_result):
                                result = await update_property(
                                    db_session, test_property.id, update_data, test_user
                                )

                                assert result is not None
                                assert result.title == "Updated Title"

    @pytest.mark.asyncio
    async def test_update_property_rejects_pg_with_non_rent_purpose(
        self,
        db_session: AsyncSession,
        test_property,
        test_user,
    ):
        """Test updates cannot move PG listings outside the rent purpose."""
        from app.core.exceptions import BadRequestException
        from app.schemas.property import PropertyUpdate
        from app.services.property import update_property

        update_data = PropertyUpdate(
            property_type=PropertyType.pg,
            purpose=PropertyPurpose.buy,
        )

        with pytest.raises(BadRequestException):
            await update_property(db_session, test_property.id, update_data, test_user)

    @pytest.mark.asyncio
    async def test_update_property_not_found(
        self,
        db_session: AsyncSession,
        test_user,
    ):
        """Test updating non-existent property."""
        from fastapi import HTTPException

        from app.schemas.property import PropertyUpdate
        from app.services.property import update_property

        update_data = PropertyUpdate(title="Updated Title")

        with pytest.raises(HTTPException) as exc_info:
            await update_property(db_session, 99999, update_data, test_user)

        assert exc_info.value.status_code == 404


class TestDeleteProperty:
    """Tests for delete_property function."""

    @pytest.mark.asyncio
    async def test_delete_property_success(
        self,
        db_session: AsyncSession,
        test_property,
        test_user,
    ):
        """Test successful property deletion."""
        from app.core.exceptions import PropertyNotFoundException
        from app.services.property import delete_property, get_property

        property_id = test_property.id

        # Mock the cache invalidation to avoid MagicMock await issues
        with patch("app.services.property.crud.PropertyCacheManager.invalidate_property_caches", new_callable=AsyncMock):
            with patch("app.services.property.crud.PropertyCacheManager.invalidate_property_detail_cache", new_callable=AsyncMock):
                result = await delete_property(db_session, property_id, test_user)

        assert result is True

        # Verify deleted - should raise exception
        with pytest.raises(PropertyNotFoundException):
            await get_property(db_session, property_id)


class TestListUserProperties:
    """Tests for list_user_properties function."""

    @pytest.mark.asyncio
    async def test_list_user_properties(
        self,
        db_session: AsyncSession,
        test_user,
        test_properties,
    ):
        """Test listing properties for a user."""
        from app.services.property import list_user_properties

        rows, _next, _total = await list_user_properties(
            db_session, test_user.id, cursor_payload={}, limit=20
        )

        assert len(rows) == len(test_properties)


class TestPropertyFiltering:
    """Tests for property filtering."""

    @pytest.mark.asyncio
    async def test_filter_by_city(
        self,
        db_session: AsyncSession,
        test_properties,
        test_user,
    ):
        """Test filtering properties by city."""
        from app.schemas.property import UnifiedPropertyFilter
        from app.services.property import get_unified_properties_optimized

        filters = UnifiedPropertyFilter(city="Mumbai")

        rows, _next, _total = await get_unified_properties_optimized(
            db_session, filters, user_id=test_user.id, cursor_payload={}, limit=10
        )

        assert isinstance(rows, list)
        for prop in rows:
            assert prop.city == "Mumbai"

    @pytest.mark.asyncio
    async def test_filter_by_purpose(
        self,
        db_session: AsyncSession,
        test_properties,
        test_user,
    ):
        """Test filtering properties by purpose."""
        from app.schemas.property import UnifiedPropertyFilter
        from app.services.property import get_unified_properties_optimized

        filters = UnifiedPropertyFilter(purpose=PropertyPurpose.rent)

        rows, _next, _total = await get_unified_properties_optimized(
            db_session, filters, user_id=test_user.id, cursor_payload={}, limit=10
        )

        assert isinstance(rows, list)
        for prop in rows:
            assert prop.purpose == PropertyPurpose.rent

    @pytest.mark.asyncio
    async def test_filter_by_property_type(
        self,
        db_session: AsyncSession,
        test_properties,
        test_user,
    ):
        """Test filtering properties by type."""
        from app.schemas.property import UnifiedPropertyFilter
        from app.services.property import get_unified_properties_optimized

        filters = UnifiedPropertyFilter(property_type=[PropertyType.apartment])

        rows, _next, _total = await get_unified_properties_optimized(
            db_session, filters, user_id=test_user.id, cursor_payload={}, limit=10
        )

        assert isinstance(rows, list)
        for prop in rows:
            assert prop.property_type == PropertyType.apartment

    @pytest.mark.asyncio
    async def test_filter_by_gender_preference(
        self,
        db_session: AsyncSession,
        test_special_listing_properties,
        test_user,
    ):
        """Test filtering specialized listings by gender preference."""
        from app.schemas.property import UnifiedPropertyFilter
        from app.services.property import get_unified_properties_optimized

        filters = UnifiedPropertyFilter(
            gender_preference=ListingGenderPreference.female,
        )

        rows, _next, _total = await get_unified_properties_optimized(
            db_session, filters, user_id=test_user.id, cursor_payload={}, limit=10
        )

        assert isinstance(rows, list)
        assert any(prop.property_type == PropertyType.pg for prop in rows)
        for prop in rows:
            assert prop.listing_preferences is not None
            assert prop.listing_preferences.gender_preference == ListingGenderPreference.female

    @pytest.mark.asyncio
    async def test_filter_by_sharing_type(
        self,
        db_session: AsyncSession,
        test_special_listing_properties,
        test_user,
    ):
        """Test filtering specialized listings by sharing type."""
        from app.schemas.property import UnifiedPropertyFilter
        from app.services.property import get_unified_properties_optimized

        filters = UnifiedPropertyFilter(
            property_type=[PropertyType.flatmate],
            sharing_type=ListingSharingType.private_room,
        )

        rows, _next, _total = await get_unified_properties_optimized(
            db_session, filters, user_id=test_user.id, cursor_payload={}, limit=10
        )

        assert isinstance(rows, list)
        assert len(rows) == 1
        assert rows[0].property_type == PropertyType.flatmate
        assert rows[0].listing_preferences is not None
        assert (
            rows[0].listing_preferences.sharing_type
            == ListingSharingType.private_room
        )


class TestPropertyViewCount:
    """Tests for property view count functionality."""

    @pytest.mark.asyncio
    async def test_increment_view_count(
        self,
        db_session: AsyncSession,
        test_property,
    ):
        """Test incrementing property view count."""
        from app.services.property import increment_property_view_count

        initial_views = test_property.view_count or 0

        await increment_property_view_count(db_session, test_property.id)

        await db_session.refresh(test_property)
        assert test_property.view_count == initial_views + 1


class TestPropertyRecommendations:
    """Tests for property recommendations."""

    @pytest.mark.asyncio
    async def test_get_recommendations(
        self,
        db_session: AsyncSession,
        test_user,
        test_properties,
    ):
        """Test getting property recommendations."""
        from app.services.property import get_property_recommendations

        result, _next, _total = await get_property_recommendations(
            db_session,
            user_id=test_user.id,
            cursor_payload={},
            limit=5,
        )

        assert isinstance(result, list)
