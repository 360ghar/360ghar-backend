"""Pass B contract tests for the property domain.

Covers the wire rules changed in pass B: detail-only agent and visit fields, the move-in
enum, date and society filters, the builder filter set, amenity paging, and field-level
errors for the PG and flatmate purpose rule.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from pydantic import ValidationError
from sqlalchemy import and_, select
from sqlalchemy.dialects import postgresql

import app.schemas as schemas_pkg
from app.core.exceptions import ValidationException
from app.models.enums import PropertyPurpose, PropertyStatus, PropertyType
from app.models.properties import Property
from app.repositories.property_query_builder import PropertyQueryBuilder
from app.schemas.amenity import Amenity
from app.schemas.property import (
    Property as PropertySchema,
)
from app.schemas.property import (
    PropertyDetail,
    PropertyImage,
    UnifiedPropertyFilter,
)
from app.services.visibility import public_listing_preferences

NOW = datetime(2026, 10, 1, tzinfo=UTC)


def _listing(**overrides) -> dict:
    data = {
        "id": 1,
        "owner_id": 2,
        "title": "Flat",
        "property_type": PropertyType.apartment,
        "purpose": PropertyPurpose.rent,
        "status": PropertyStatus.available,
        "base_price": 50000,
        "monthly_rent": 25000,
        "is_available": True,
        "view_count": 0,
        "like_count": 0,
        "interest_count": 0,
        "created_at": NOW,
        "updated_at": NOW,
    }
    data.update(overrides)
    return data


def _compiled(conditions) -> str:
    stmt = select(Property).where(and_(*conditions))
    return str(stmt.compile(dialect=postgresql.dialect()))


# ---------------------------------------------------------------- filter builder (be-property-20)


@pytest.mark.asyncio
async def test_builder_applies_every_listing_filter():
    filters = UnifiedPropertyFilter(
        status=PropertyStatus.available,
        furnishing=["furnished"],
        kitchen_type=["vegetarian", "any"],
        ventilation_type=["good"],
        windows_min=2,
        has_lift=True,
        sub_locality="HSR Layout",
        society_type="gated",
        society_vibe_tags=["quiet"],
        move_in="within_1_week",
        available_from=date(2026, 11, 1),
    )
    conditions, _distance, _meta = await PropertyQueryBuilder(filters).build(AsyncMock())
    sql = _compiled(conditions)

    assert "properties.status" in sql
    assert "furnishing_level IN" in sql
    assert "kitchen_type IN" in sql  # the 'any' sentinel is dropped before the IN list
    assert "ventilation_type IN" in sql
    assert "windows_count >=" in sql
    assert "lower(amenities.title) IN" in sql
    assert "sub_locality" in sql
    assert "listing_preferences" in sql
    assert sql.count("listing_preferences") >= 2
    assert "available_from" in sql


@pytest.mark.asyncio
async def test_builder_booking_overlap_needs_both_dates():
    lone = UnifiedPropertyFilter(check_in_date="2026-11-10")
    with pytest.raises(ValidationException):
        await PropertyQueryBuilder(lone).build(AsyncMock())

    bad = UnifiedPropertyFilter(check_in_date="10/11/2026", check_out_date="2026-11-12")
    with pytest.raises(ValidationException):
        await PropertyQueryBuilder(bad).build(AsyncMock())

    reversed_dates = UnifiedPropertyFilter(check_in_date="2026-11-12", check_out_date="2026-11-10")
    with pytest.raises(ValidationException):
        await PropertyQueryBuilder(reversed_dates).build(AsyncMock())

    ok = UnifiedPropertyFilter(check_in_date="2026-11-10", check_out_date="2026-11-12")
    conditions, _d, _m = await PropertyQueryBuilder(ok).build(AsyncMock())
    assert "bookings" in _compiled(conditions)


@pytest.mark.asyncio
async def test_exclude_swiped_applies_only_with_a_viewer():
    filters = UnifiedPropertyFilter(exclude_swiped=True)
    without_viewer, _d, _m = await PropertyQueryBuilder(filters).build(AsyncMock())
    with_viewer, _d, _m = await PropertyQueryBuilder(filters).build(AsyncMock(), viewer_id=7)

    assert "user_swipes" not in _compiled(without_viewer)
    assert "user_swipes" in _compiled(with_viewer)


# ---------------------------------------------------------------- query validation (be-property-32/34/21)


@pytest.mark.asyncio
async def test_retired_move_in_alias_is_422(client: AsyncClient):
    response = await client.get("/api/v1/properties", params={"move_in": "within_a_week"})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


@pytest.mark.asyncio
async def test_canonical_move_in_value_reaches_the_search(client: AsyncClient):
    with patch(
        "app.api.api_v1.endpoints.properties.run_property_search",
        new_callable=AsyncMock,
        return_value=([], None, None),
    ) as search:
        response = await client.get("/api/v1/properties", params={"move_in": "within_1_week"})

    assert response.status_code == 200
    assert search.call_args.args[1].move_in.value == "within_1_week"


@pytest.mark.asyncio
async def test_unknown_furnishing_and_kitchen_values_are_422(client: AsyncClient):
    for params in (
        {"furnishing": "fully-furnished"},
        {"kitchen_type": "spicy"},
        {"ventilation_type": "great"},
    ):
        response = await client.get("/api/v1/properties", params=params)
        assert response.status_code == 422, params


@pytest.mark.asyncio
async def test_repeated_property_type_keys_are_read_as_a_list(client: AsyncClient):
    with patch(
        "app.api.api_v1.endpoints.properties.run_property_search",
        new_callable=AsyncMock,
        return_value=([], None, None),
    ) as search:
        response = await client.get(
            "/api/v1/properties?property_type=apartment&property_type=villa"
        )

    assert response.status_code == 200
    assert search.call_args.args[1].property_type == [
        PropertyType.apartment,
        PropertyType.villa,
    ]


# ---------------------------------------------------------------- detail-only fields (be-property-31, be-property-15)


@pytest.mark.asyncio
async def test_detail_carries_agent_and_visit_fields_and_list_does_not(client: AsyncClient):
    detail = PropertyDetail.model_validate(
        _listing(
            agent={"id": 9, "name": "Asha", "contact_number": "9876543210"},
            user_has_scheduled_visit=True,
            user_scheduled_visit_count=2,
            user_next_visit_date=NOW,
        )
    )
    with (
        patch(
            "app.api.api_v1.endpoints.properties.get_property",
            new_callable=AsyncMock,
            return_value=detail,
        ),
        patch(
            "app.api.api_v1.endpoints.properties.increment_property_view_count",
            new_callable=AsyncMock,
        ),
    ):
        body = (await client.get("/api/v1/properties/1")).json()
    assert body["agent"]["name"] == "Asha"
    assert body["user_scheduled_visit_count"] == 2
    assert "vector_distance" not in body

    listing = PropertySchema.model_validate(_listing(vector_distance=0.2, relevance_score=0.9))
    with patch(
        "app.api.api_v1.endpoints.properties.run_property_search",
        new_callable=AsyncMock,
        return_value=([listing], None, None),
    ):
        row = (await client.get("/api/v1/properties")).json()["items"][0]
    for key in (
        "user_has_scheduled_visit",
        "user_scheduled_visit_count",
        "user_next_visit_date",
        "vector_distance",
        "relevance_score",
    ):
        assert key not in row, key
    # Only the detail screen reads the agent. List rows carry the masked owner_contact only.
    assert "agent" not in row
    assert "compatibility_score" in row


# ---------------------------------------------------------------- field-level errors (admin-pm-17)


@pytest.mark.asyncio
async def test_pg_listing_with_non_rent_purpose_is_a_field_error(authenticated_client: AsyncClient):
    response = await authenticated_client.post(
        "/api/v1/properties",
        json={
            "title": "PG",
            "property_type": "pg",
            "purpose": "buy",
            "base_price": 1000,
            "monthly_rent": 1000,
        },
    )

    assert response.status_code == 422
    fields = response.json()["error"]["details"]["fields"]
    purpose = [f for f in fields if f["field"] == "body.purpose"]
    assert purpose, fields
    assert purpose[0]["msg"] == "PG and flatmate listings must use purpose 'rent'"


# ---------------------------------------------------------------- amenity paging (conventions-6)


@pytest.mark.asyncio
async def test_amenities_are_a_cursor_page(client: AsyncClient):
    rows = [
        Amenity(id=i, title=title, created_at=NOW, updated_at=NOW)
        for i, title in enumerate(["Gym", "Lift", "Pool"], start=1)
    ]
    with patch(
        "app.api.api_v1.endpoints.amenities.get_amenities_cached",
        new_callable=AsyncMock,
        return_value=rows,
    ):
        first = (await client.get("/api/v1/amenities", params={"limit": 2})).json()
        assert [a["title"] for a in first["items"]] == ["Gym", "Lift"]
        assert first["has_more"] is True
        assert first["next_cursor"]

        second = (
            await client.get(
                "/api/v1/amenities", params={"limit": 2, "cursor": first["next_cursor"]}
            )
        ).json()
        assert [a["title"] for a in second["items"]] == ["Pool"]
        assert second["has_more"] is False


# ---------------------------------------------------------------- schema shape (conventions-26, app-property-10/be-property-28)


def test_display_order_is_a_required_integer_on_the_response():
    with pytest.raises(ValidationError):
        PropertyImage(
            id=1, property_id=1, image_url="https://cdn.example/a.jpg", display_order=None
        )


def test_retired_schema_names_are_not_exported():
    for name in (
        "PropertyInterest",
        "PropertyImageCreate",
        "AmenityCreate",
        "AmenityUpdate",
        "PropertyAmenityCreate",
        "UnifiedPropertyResponse",
        "PropertyFilter",
    ):
        assert not hasattr(schemas_pkg, name), name


def test_owner_listing_preferences_keep_only_public_keys():
    raw = {
        "gender_preference": "any",
        "moderation_status": "live",
        "approval_boost_granted_at": "2026-10-01T00:00:00Z",
        "auto_paused_reason": "stale",
        "ai_prescreen_result": "pass",
    }
    kept = public_listing_preferences(raw)

    assert set(kept) == {"gender_preference", "moderation_status"}
