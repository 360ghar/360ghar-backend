"""
Tests for app.repositories.property_query_builder module.

These tests require a real database with PostGIS extension.
Marked with @pytest.mark.postgis.
"""


import pytest

from app.models.enums import PropertyPurpose, PropertyType
from app.repositories.property_query_builder import PropertyQueryBuilder
from app.schemas.property import UnifiedPropertyFilter


class TestPropertyQueryBuilderInit:
    """Tests for PropertyQueryBuilder initialization (no DB needed)."""

    def test_stores_filters(self):
        filters = UnifiedPropertyFilter(city="Mumbai")
        builder = PropertyQueryBuilder(filters)
        assert builder.filters is filters


@pytest.mark.postgis
class TestPropertyQueryBuilderConditions:
    """Tests for filter condition building (requires PostGIS)."""

    @pytest.mark.asyncio
    async def test_city_filter(self, db_session):
        filters = UnifiedPropertyFilter(city="Mumbai")
        builder = PropertyQueryBuilder(filters)
        conditions, _, _ = await builder.build(db_session)
        assert len(conditions) >= 1

    @pytest.mark.asyncio
    async def test_purpose_filter(self, db_session):
        filters = UnifiedPropertyFilter(purpose=PropertyPurpose.rent)
        builder = PropertyQueryBuilder(filters)
        conditions, _, _ = await builder.build(db_session)
        assert len(conditions) >= 1

    @pytest.mark.asyncio
    async def test_property_type_filter(self, db_session):
        filters = UnifiedPropertyFilter(property_type=[PropertyType.apartment])
        builder = PropertyQueryBuilder(filters)
        conditions, _, _ = await builder.build(db_session)
        assert len(conditions) >= 1

    @pytest.mark.asyncio
    async def test_empty_filters(self, db_session):
        filters = UnifiedPropertyFilter()
        builder = PropertyQueryBuilder(filters)
        conditions, _, _ = await builder.build(db_session)
        # Should at least have availability filter
        assert len(conditions) >= 1

    @pytest.mark.asyncio
    async def test_include_unavailable(self, db_session):
        filters = UnifiedPropertyFilter()
        builder = PropertyQueryBuilder(filters)
        conditions_with, _, _ = await builder.build(db_session, include_unavailable=True)
        conditions_without, _, _ = await builder.build(db_session, include_unavailable=False)
        # include_unavailable=True should have fewer conditions
        assert len(conditions_with) <= len(conditions_without)

    @pytest.mark.asyncio
    async def test_property_ids_filter(self, db_session):
        filters = UnifiedPropertyFilter(property_ids=[1, 2, 3])
        builder = PropertyQueryBuilder(filters)
        conditions, _, _ = await builder.build(db_session)
        assert len(conditions) >= 1

    @pytest.mark.asyncio
    async def test_combined_filters(self, db_session):
        filters = UnifiedPropertyFilter(
            city="Mumbai",
            purpose=PropertyPurpose.rent,
            property_type=[PropertyType.apartment],
        )
        builder = PropertyQueryBuilder(filters)
        conditions, _, _ = await builder.build(db_session)
        # Should have availability + city + purpose + type = at least 4
        assert len(conditions) >= 4

    @pytest.mark.asyncio
    async def test_price_range_filters(self, db_session):
        filters = UnifiedPropertyFilter(price_min=10000, price_max=100000)
        builder = PropertyQueryBuilder(filters)
        conditions, _, _ = await builder.build(db_session)
        assert len(conditions) >= 2

    @pytest.mark.asyncio
    async def test_search_meta_returned(self, db_session):
        filters = UnifiedPropertyFilter()
        builder = PropertyQueryBuilder(filters)
        _, _, search_meta = await builder.build(db_session)
        assert isinstance(search_meta, dict)
        assert "search_query_obj" in search_meta
        assert "search_vector" in search_meta
        assert "text_rank_expr" in search_meta
