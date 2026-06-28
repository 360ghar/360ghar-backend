"""
Integration tests for property search with all filter combinations.

Tests real database queries with PostGIS geospatial, full-text search,
and combined filter scenarios. Requires PostGIS extension.
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import PropertyPurpose, PropertyType
from app.schemas.property import UnifiedPropertyFilter
from app.services.property import get_unified_properties_optimized


@pytest.mark.postgis
class TestPropertySearchCombinations:
    """Integration tests for property search with combined filters."""

    @pytest.mark.asyncio
    async def test_city_and_purpose_filter(
        self,
        db_session: AsyncSession,
        test_properties,
        test_user,
    ):
        filters = UnifiedPropertyFilter(
            city="Mumbai",
            purpose=PropertyPurpose.rent,
        )
        rows, _next, _total = await get_unified_properties_optimized(
            db_session, filters, user_id=test_user.id, cursor_payload={}, limit=10,
        )
        for item in rows:
            assert item.city == "Mumbai"
            assert item.purpose == PropertyPurpose.rent

    @pytest.mark.asyncio
    async def test_city_and_type_filter(
        self,
        db_session: AsyncSession,
        test_properties,
        test_user,
    ):
        filters = UnifiedPropertyFilter(
            city="Mumbai",
            property_type=[PropertyType.apartment],
        )
        rows, _next, _total = await get_unified_properties_optimized(
            db_session, filters, user_id=test_user.id, cursor_payload={}, limit=10,
        )
        for item in rows:
            assert item.property_type == PropertyType.apartment

    @pytest.mark.asyncio
    async def test_purpose_and_type_filter(
        self,
        db_session: AsyncSession,
        test_properties,
        test_user,
    ):
        filters = UnifiedPropertyFilter(
            purpose=PropertyPurpose.buy,
            property_type=[PropertyType.house],
        )
        rows, _next, _total = await get_unified_properties_optimized(
            db_session, filters, user_id=test_user.id, cursor_payload={}, limit=10,
        )
        for item in rows:
            assert item.purpose == PropertyPurpose.buy

    @pytest.mark.asyncio
    async def test_price_range_filter(
        self,
        db_session: AsyncSession,
        test_properties,
        test_user,
    ):
        filters = UnifiedPropertyFilter(price_min=10000, price_max=100000)
        rows, _next, _total = await get_unified_properties_optimized(
            db_session, filters, user_id=test_user.id, cursor_payload={}, limit=10,
        )
        assert isinstance(rows, list)

    @pytest.mark.asyncio
    async def test_bedroom_filter(
        self,
        db_session: AsyncSession,
        test_properties,
        test_user,
    ):
        filters = UnifiedPropertyFilter(bedrooms_min=2, bedrooms_max=3)
        rows, _next, _total = await get_unified_properties_optimized(
            db_session, filters, user_id=test_user.id, cursor_payload={}, limit=10,
        )
        for item in rows:
            assert item.bedrooms is not None
            assert 2 <= item.bedrooms <= 3

    @pytest.mark.asyncio
    async def test_empty_results(self, db_session: AsyncSession, test_user):
        filters = UnifiedPropertyFilter(city="NonExistentCity")
        rows, _next, _total = await get_unified_properties_optimized(
            db_session, filters, user_id=test_user.id, cursor_payload={}, limit=10,
        )
        assert rows == []

    @pytest.mark.asyncio
    async def test_pagination(
        self,
        db_session: AsyncSession,
        test_properties,
        test_user,
    ):
        filters = UnifiedPropertyFilter()
        rows1, next1, _ = await get_unified_properties_optimized(
            db_session, filters, user_id=test_user.id, cursor_payload={}, limit=2,
        )
        assert len(rows1) <= 2
        # Walk to page 2 using next cursor payload
        if next1 is not None:
            rows2, _next2, _ = await get_unified_properties_optimized(
                db_session, filters, user_id=test_user.id, cursor_payload=next1, limit=2,
            )
            # No ID overlap
            ids1 = {p.id for p in rows1}
            ids2 = {p.id for p in rows2}
            assert ids1.isdisjoint(ids2)

    @pytest.mark.asyncio
    async def test_special_listing_filters(
        self,
        db_session: AsyncSession,
        test_special_listing_properties,
        test_user,
    ):
        filters = UnifiedPropertyFilter(
            property_type=[PropertyType.pg, PropertyType.flatmate],
        )
        rows, _next, _total = await get_unified_properties_optimized(
            db_session, filters, user_id=test_user.id, cursor_payload={}, limit=10,
        )
        for item in rows:
            assert item.property_type in (PropertyType.pg, PropertyType.flatmate)
