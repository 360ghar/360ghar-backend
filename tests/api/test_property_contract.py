"""Property wire contract: viewer masking, PATCH nulls, price cap, pagination, toggles.

Each test pins one ledger item from the BE-property slice (see contract-audit).
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import delete

from app.config import settings
from app.models.enums import ImageCategory, PropertyPurpose, PropertyType
from app.models.properties import Property, PropertyAmenity, PropertyImage
from tests.fixtures.factories import AmenityFactory, PropertyFactory

pytestmark = pytest.mark.asyncio

COMPANY = "+918000000000"
OWNER_PHONE = "+919000000000"
MODERATOR_KEYS = {"moderated_by": 99, "moderation_reason": "spam", "ai_prescreen_flags": ["x"]}


@pytest.fixture(autouse=True)
def _isolated_state(monkeypatch):
    """Company number set, and a fresh in-memory cache for each test (the default is disk)."""
    import app.core.cache as cache_pkg

    monkeypatch.setattr(settings, "COMPANY_CONTACT_NUMBER", COMPANY)
    monkeypatch.setattr(settings, "CACHE_BACKEND", "memory")
    monkeypatch.setattr(cache_pkg, "_cache_manager", None)
    yield
    monkeypatch.setattr(cache_pkg, "_cache_manager", None)


def _create_body(**overrides) -> dict:
    body = {
        "title": "Test flat",
        "property_type": "apartment",
        "purpose": "buy",
        "base_price": 5_000_000,
        "city": "Mumbai",
        "locality": "Andheri",
        "area_sqft": 1000,
    }
    body.update(overrides)
    return body


async def _pg_listing(db_session, owner, **kwargs) -> Property:
    prefs = kwargs.pop("listing_preferences", {"moderation_status": "live"})
    kwargs.setdefault("is_available", True)
    return await PropertyFactory.create(
        db_session,
        owner=owner,
        property_type=PropertyType.pg,
        purpose=PropertyPurpose.rent,
        monthly_rent=Decimal("12000"),
        listing_preferences=prefs,
        **kwargs,
    )


# --- Owner contact and listing preferences by viewer -------------------------------


async def test_anonymous_detail_masks_owner_contact_and_moderator_keys(
    client: AsyncClient, db_session, test_user
):
    prop = await PropertyFactory.create(
        db_session,
        owner=test_user,
        owner_contact=OWNER_PHONE,
        listing_preferences={
            "moderation_status": "live",
            "video_tour_url": "https://v.example/t",
            **MODERATOR_KEYS,
        },
    )

    resp = await client.get(f"/api/v1/properties/{prop.id}")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["owner_contact"] == COMPANY
    assert body["listing_preferences"]["video_tour_url"] == "https://v.example/t"
    assert set(MODERATOR_KEYS).isdisjoint(body["listing_preferences"])


async def test_anonymous_list_and_recommendations_mask_the_same_fields(
    client: AsyncClient, db_session, test_user
):
    prop = await PropertyFactory.create(
        db_session,
        owner=test_user,
        purpose=PropertyPurpose.buy,
        owner_contact=OWNER_PHONE,
        listing_preferences={"moderation_status": "live", **MODERATOR_KEYS},
    )

    listed = await client.get("/api/v1/properties", params={"purpose": "buy"})
    recs = await client.get("/api/v1/properties/recommendations")

    for resp in (listed, recs):
        assert resp.status_code == 200, resp.text
        row = next(item for item in resp.json()["items"] if item["id"] == prop.id)
        assert row["owner_contact"] == COMPANY
        assert set(MODERATOR_KEYS).isdisjoint(row["listing_preferences"] or {})


async def test_owner_sees_own_contact_but_not_moderator_keys(
    authenticated_client: AsyncClient, db_session, test_user
):
    prop = await PropertyFactory.create(
        db_session,
        owner=test_user,
        owner_contact=OWNER_PHONE,
        listing_preferences={"moderation_status": "live", **MODERATOR_KEYS},
    )

    resp = await authenticated_client.get(f"/api/v1/properties/{prop.id}")

    assert resp.status_code == 200, resp.text
    assert resp.json()["owner_contact"] == OWNER_PHONE
    assert set(MODERATOR_KEYS).isdisjoint(resp.json()["listing_preferences"])


async def test_admin_sees_owner_contact_and_moderator_keys(
    admin_authenticated_client: AsyncClient, db_session, test_user
):
    prop = await PropertyFactory.create(
        db_session,
        owner=test_user,
        owner_contact=OWNER_PHONE,
        listing_preferences={"moderation_status": "live", **MODERATOR_KEYS},
    )

    resp = await admin_authenticated_client.get(f"/api/v1/properties/{prop.id}")

    assert resp.status_code == 200, resp.text
    assert resp.json()["owner_contact"] == OWNER_PHONE
    assert resp.json()["listing_preferences"]["moderated_by"] == 99


async def test_owner_create_response_shows_own_contact(authenticated_client: AsyncClient):
    resp = await authenticated_client.post(
        "/api/v1/properties",
        json=_create_body(owner_contact=OWNER_PHONE),
    )

    assert resp.status_code == 201, resp.text
    assert resp.json()["owner_contact"] == OWNER_PHONE


# --- PATCH semantics and the shared field set --------------------------------------


async def test_put_null_on_required_field_is_422(
    authenticated_client: AsyncClient, db_session, test_user
):
    prop = await PropertyFactory.create(db_session, owner=test_user, purpose=PropertyPurpose.buy)

    resp = await authenticated_client.put(f"/api/v1/properties/{prop.id}", json={"title": None})

    assert resp.status_code == 422, resp.text
    fields = resp.json()["error"]["details"]["fields"]
    assert any(item["field"] == "body.title" for item in fields)


async def test_put_rejects_unknown_keys(authenticated_client: AsyncClient, db_session, test_user):
    prop = await PropertyFactory.create(db_session, owner=test_user, purpose=PropertyPurpose.buy)

    resp = await authenticated_client.put(
        f"/api/v1/properties/{prop.id}", json={"no_such_field": 1}
    )

    assert resp.status_code == 422, resp.text


async def test_put_can_set_and_clear_an_optional_field(
    authenticated_client: AsyncClient, db_session, test_user
):
    prop = await PropertyFactory.create(
        db_session, owner=test_user, purpose=PropertyPurpose.buy, owner_contact=OWNER_PHONE
    )

    resp = await authenticated_client.put(
        f"/api/v1/properties/{prop.id}", json={"owner_contact": None, "builder_name": "Acme"}
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["builder_name"] == "Acme"
    assert resp.json()["owner_contact"] is None


async def test_base_price_cap_is_the_same_on_create_and_update(
    authenticated_client: AsyncClient, db_session, test_user
):
    created = await authenticated_client.post(
        "/api/v1/properties", json=_create_body(base_price=10_000_000_000)
    )
    prop = await PropertyFactory.create(db_session, owner=test_user, purpose=PropertyPurpose.buy)
    updated = await authenticated_client.put(
        f"/api/v1/properties/{prop.id}", json={"base_price": 10_000_000_000}
    )
    at_cap = await authenticated_client.put(
        f"/api/v1/properties/{prop.id}", json={"base_price": 9_999_999_999.99}
    )

    assert created.status_code == 422, created.text
    assert updated.status_code == 422, updated.text
    assert at_cap.status_code == 200, at_cap.text
    assert at_cap.json()["base_price"] == 9_999_999_999.99


async def test_update_cannot_clear_monthly_rent_on_a_rent_listing(
    authenticated_client: AsyncClient, db_session, test_user
):
    prop = await PropertyFactory.create(
        db_session,
        owner=test_user,
        purpose=PropertyPurpose.rent,
        monthly_rent=Decimal("20000"),
    )

    resp = await authenticated_client.put(
        f"/api/v1/properties/{prop.id}", json={"monthly_rent": None}
    )

    assert resp.status_code == 422, resp.text


async def test_coordinates_are_bounded_on_create_and_filter(
    client: AsyncClient, authenticated_client: AsyncClient
):
    created = await authenticated_client.post(
        "/api/v1/properties", json=_create_body(latitude=91.0, longitude=0.0)
    )
    filtered = await client.get("/api/v1/properties", params={"lat": 91, "lng": 0})

    assert created.status_code == 422, created.text
    assert filtered.status_code == 422, filtered.text


async def test_available_from_is_a_date(authenticated_client: AsyncClient):
    ok = await authenticated_client.post(
        "/api/v1/properties", json=_create_body(available_from="2026-11-01")
    )
    bad = await authenticated_client.post(
        "/api/v1/properties", json=_create_body(available_from="next week")
    )

    assert ok.status_code == 201, ok.text
    assert ok.json()["available_from"] == "2026-11-01"
    assert bad.status_code == 422, bad.text


async def test_price_fields_follow_the_purpose(authenticated_client: AsyncClient):
    rent = await authenticated_client.post(
        "/api/v1/properties",
        json=_create_body(purpose="rent", base_price=25000, monthly_rent=25000),
    )
    short = await authenticated_client.post(
        "/api/v1/properties",
        json=_create_body(purpose="short_stay", base_price=4000, daily_rate=4000),
    )
    buy = await authenticated_client.post(
        "/api/v1/properties", json=_create_body(purpose="buy", base_price=5_000_000)
    )

    assert rent.status_code == 201, rent.text
    assert rent.json()["monthly_rent"] == 25000
    assert rent.json()["price_per_sqft"] == 25.0
    assert rent.json()["nightly_rate"] is None
    assert short.json()["nightly_rate"] == 4000
    assert short.json()["price_per_sqft"] == 4.0
    assert buy.json()["price_per_sqft"] == 5000.0


async def test_price_per_sqft_is_not_accepted_on_write(authenticated_client: AsyncClient):
    resp = await authenticated_client.post(
        "/api/v1/properties", json=_create_body(price_per_sqft=10)
    )

    assert resp.status_code == 422, resp.text


async def test_delete_returns_204_without_body(
    authenticated_client: AsyncClient, db_session, test_user
):
    prop = await PropertyFactory.create(db_session, owner=test_user)

    resp = await authenticated_client.delete(f"/api/v1/properties/{prop.id}")

    assert resp.status_code == 204, resp.text
    assert resp.content == b""


# --- Amenities ---------------------------------------------------------------------


async def test_amenity_ids_round_trip_keeps_the_set(
    authenticated_client: AsyncClient, db_session, test_user
):
    gym = await AmenityFactory.create(db_session, title="Gym")
    pool = await AmenityFactory.create(db_session, title="Pool")
    prop = await PropertyFactory.create(db_session, owner=test_user, purpose=PropertyPurpose.buy)
    prop_id = prop.id
    put = await authenticated_client.put(
        f"/api/v1/properties/{prop_id}", json={"amenity_ids": [gym.id, pool.id]}
    )
    assert put.status_code == 200, put.text
    # The test client shares one session across requests. Expire it, as a new request would.
    db_session.expire_all()

    detail = await authenticated_client.get(f"/api/v1/properties/{prop_id}")
    ids = sorted(item["id"] for item in detail.json()["amenities"])
    again = await authenticated_client.put(
        f"/api/v1/properties/{prop_id}", json={"amenity_ids": ids}
    )

    assert ids == sorted([gym.id, pool.id])
    assert sorted(item["id"] for item in again.json()["amenities"]) == ids


async def test_unknown_amenity_id_is_422(authenticated_client: AsyncClient, db_session, test_user):
    prop = await PropertyFactory.create(db_session, owner=test_user, purpose=PropertyPurpose.buy)

    resp = await authenticated_client.put(
        f"/api/v1/properties/{prop.id}", json={"amenity_ids": [987654]}
    )

    assert resp.status_code == 422, resp.text


# --- Filters -----------------------------------------------------------------------


async def test_has_lift_matches_a_listing_tagged_elevator(
    client: AsyncClient, db_session, test_user
):
    elevator = await AmenityFactory.create(db_session, title="Elevator")
    lifted = await PropertyFactory.create(db_session, owner=test_user, purpose=PropertyPurpose.buy)
    plain = await PropertyFactory.create(db_session, owner=test_user, purpose=PropertyPurpose.buy)
    db_session.add(PropertyAmenity(property_id=lifted.id, amenity_id=elevator.id))
    await db_session.flush()

    resp = await client.get("/api/v1/properties", params={"has_lift": "true"})

    ids = [item["id"] for item in resp.json()["items"]]
    assert resp.status_code == 200, resp.text
    assert lifted.id in ids
    assert plain.id not in ids


async def test_locality_filter_matches_the_exact_name(client: AsyncClient, db_session, test_user):
    exact = await PropertyFactory.create(
        db_session, owner=test_user, purpose=PropertyPurpose.buy, locality="Sector 8"
    )
    other = await PropertyFactory.create(
        db_session, owner=test_user, purpose=PropertyPurpose.buy, locality="Sector 81"
    )

    resp = await client.get("/api/v1/properties", params={"locality": "Sector 8"})

    ids = [item["id"] for item in resp.json()["items"]]
    assert resp.status_code == 200, resp.text
    assert exact.id in ids
    assert other.id not in ids


async def test_enum_query_params_reject_unknown_values(client: AsyncClient):
    kitchen = await client.get("/api/v1/properties", params={"kitchen_type": "kosher"})
    ventilation = await client.get("/api/v1/properties", params={"ventilation_type": "loud"})
    furnishing = await client.get("/api/v1/properties", params={"furnishing": "fully-furnished"})

    assert kitchen.status_code == 422, kitchen.text
    assert ventilation.status_code == 422, ventilation.text
    assert furnishing.status_code == 422, furnishing.text


async def test_status_filter_applies_to_the_listing_status(
    client: AsyncClient, db_session, test_user
):
    from app.models.enums import PropertyStatus

    sold = await PropertyFactory.create(
        db_session,
        owner=test_user,
        purpose=PropertyPurpose.buy,
        status=PropertyStatus.sold,
        is_available=True,
    )
    avail = await PropertyFactory.create(
        db_session, owner=test_user, purpose=PropertyPurpose.buy, is_available=True
    )

    resp = await client.get("/api/v1/properties", params={"status": "sold"})

    ids = [item["id"] for item in resp.json()["items"]]
    assert resp.status_code == 200, resp.text
    assert sold.id in ids
    assert avail.id not in ids


# --- Pagination --------------------------------------------------------------------


async def test_pages_do_not_skip_rows_removed_between_requests(
    client: AsyncClient, db_session, test_user
):
    for index in range(5):
        await PropertyFactory.create(
            db_session,
            owner=test_user,
            purpose=PropertyPurpose.buy,
            title=f"Listing {index}",
            locality="Keyset Lane",
        )
    full = await client.get(
        "/api/v1/properties",
        params={"purpose": "buy", "locality": "Keyset Lane", "sort_by": "newest", "limit": 100},
    )
    order = [item["id"] for item in full.json()["items"]]
    assert len(order) == 5

    first = await client.get(
        "/api/v1/properties",
        params={"purpose": "buy", "locality": "Keyset Lane", "sort_by": "newest", "limit": 2},
    )
    cursor = first.json()["next_cursor"]
    assert [item["id"] for item in first.json()["items"]] == order[:2]

    # A listing that the client has not read yet is removed (for example, swiped away).
    # Offset paging would then start one row too late and skip a listing.
    await db_session.execute(delete(Property).where(Property.id == order[2]))
    await db_session.flush()

    second = await client.get(
        "/api/v1/properties",
        params={
            "purpose": "buy",
            "locality": "Keyset Lane",
            "sort_by": "newest",
            "limit": 2,
            "cursor": cursor,
        },
    )

    assert second.status_code == 200, second.text
    assert [item["id"] for item in second.json()["items"]] == [order[3], order[4]]


async def test_cursor_is_bound_to_the_filters(client: AsyncClient, db_session, test_user):
    for _ in range(2):
        await PropertyFactory.create(db_session, owner=test_user, purpose=PropertyPurpose.buy)
    first = await client.get("/api/v1/properties", params={"purpose": "buy", "limit": 1})
    cursor = first.json()["next_cursor"]
    assert cursor

    other = await client.get(
        "/api/v1/properties", params={"purpose": "rent", "limit": 1, "cursor": cursor}
    )

    assert other.status_code == 422, other.text
    assert other.json()["error"]["code"] == "INVALID_CURSOR"


async def test_total_is_null_unless_requested(client: AsyncClient, db_session, test_user):
    await PropertyFactory.create(db_session, owner=test_user, purpose=PropertyPurpose.buy)

    plain = await client.get("/api/v1/properties", params={"purpose": "buy"})
    counted = await client.get(
        "/api/v1/properties", params={"purpose": "buy", "include_total": "true"}
    )

    assert plain.json()["total"] is None
    assert counted.json()["total"] >= 1


# --- Owner status toggles and review -----------------------------------------------


async def test_owner_cannot_resume_a_listing_pending_review(
    authenticated_client: AsyncClient, db_session, test_user
):
    prop = await _pg_listing(
        db_session,
        test_user,
        listing_preferences={"moderation_status": "pending_review"},
        is_available=False,
    )

    resp = await authenticated_client.put(
        f"/api/v1/properties/{prop.id}",
        json={"listing_preferences": {"moderation_status": "live"}},
    )

    assert resp.status_code == 409, resp.text
    assert resp.json()["error"]["code"] == "LISTING_STATUS_CONFLICT"


async def test_owner_cannot_pause_a_listing_pending_review(
    authenticated_client: AsyncClient, db_session, test_user
):
    prop = await _pg_listing(
        db_session,
        test_user,
        listing_preferences={"moderation_status": "pending_review"},
        is_available=False,
    )

    resp = await authenticated_client.put(
        f"/api/v1/properties/{prop.id}",
        json={"listing_preferences": {"moderation_status": "paused"}},
    )

    assert resp.status_code == 409, resp.text


async def test_owner_pauses_then_resumes_a_live_listing(
    authenticated_client: AsyncClient, db_session, test_user
):
    prop = await _pg_listing(db_session, test_user)

    paused = await authenticated_client.put(
        f"/api/v1/properties/{prop.id}",
        json={"listing_preferences": {"moderation_status": "paused"}},
    )
    resumed = await authenticated_client.put(
        f"/api/v1/properties/{prop.id}",
        json={"listing_preferences": {"moderation_status": "live"}},
    )

    assert paused.status_code == 200, paused.text
    assert paused.json()["listing_preferences"]["moderation_status"] == "paused"
    assert paused.json()["is_available"] is False
    assert resumed.status_code == 200, resumed.text
    assert resumed.json()["listing_preferences"]["moderation_status"] == "live"
    assert resumed.json()["is_available"] is True


async def test_content_edit_sends_a_live_listing_to_review_availability_does_not(
    authenticated_client: AsyncClient, db_session, test_user
):
    prop = await _pg_listing(db_session, test_user)

    availability = await authenticated_client.put(
        f"/api/v1/properties/{prop.id}", json={"is_available": False}
    )
    content = await authenticated_client.put(
        f"/api/v1/properties/{prop.id}", json={"title": "Renamed room"}
    )

    assert availability.status_code == 200, availability.text
    assert availability.json()["listing_preferences"]["moderation_status"] == "live"
    assert availability.json()["is_available"] is False
    assert content.status_code == 200, content.text
    assert content.json()["listing_preferences"]["moderation_status"] == "pending_review"


# --- Floor plans -------------------------------------------------------------------


async def test_floor_plans_are_listed_apart_from_photos(client: AsyncClient, db_session, test_user):
    prop = await PropertyFactory.create(db_session, owner=test_user, purpose=PropertyPurpose.buy)
    db_session.add_all(
        [
            PropertyImage(
                property_id=prop.id,
                image_url="https://img.example/room.jpg",
                image_category=ImageCategory.room,
            ),
            PropertyImage(
                property_id=prop.id,
                image_url="https://img.example/plan.png",
                image_category=ImageCategory.floor_plan,
            ),
        ]
    )
    await db_session.flush()

    resp = await client.get(f"/api/v1/properties/{prop.id}")

    assert resp.status_code == 200, resp.text
    assert [item["image_url"] for item in resp.json()["images"]] == ["https://img.example/room.jpg"]
    assert [item["image_url"] for item in resp.json()["floor_plans"]] == [
        "https://img.example/plan.png"
    ]


# --- Leads -------------------------------------------------------------------------


async def test_lead_rejects_unknown_keys(client: AsyncClient):
    resp = await client.post("/api/v1/leads", json={"phone": "9812345601", "unexpected": 1})

    assert resp.status_code == 422, resp.text


async def test_lead_is_accepted_with_a_valid_body(client: AsyncClient):
    resp = await client.post("/api/v1/leads", json={"phone": "9812345602", "note": "Call me"})

    assert resp.status_code == 201, resp.text
    assert isinstance(resp.json()["id"], int)
    assert "received" not in resp.json()


# --- Cache round trip and owner writes ---------------------------------------------


async def test_cached_detail_and_list_keep_amenities(client: AsyncClient, db_session, test_user):
    from app.models.properties import PropertyAmenity

    gym = await AmenityFactory.create(db_session, title="Gym")
    prop = await PropertyFactory.create(db_session, owner=test_user, purpose=PropertyPurpose.buy)
    prop_id = prop.id
    db_session.add(PropertyAmenity(property_id=prop_id, amenity_id=gym.id))
    await db_session.flush()

    first = await client.get(f"/api/v1/properties/{prop_id}")
    second = await client.get(f"/api/v1/properties/{prop_id}")
    listed = await client.get("/api/v1/properties", params={"purpose": "buy", "limit": 100})
    listed_again = await client.get("/api/v1/properties", params={"purpose": "buy", "limit": 100})

    assert [item["id"] for item in first.json()["amenities"]] == [gym.id]
    assert [item["id"] for item in second.json()["amenities"]] == [gym.id]
    for resp in (listed, listed_again):
        row = next(item for item in resp.json()["items"] if item["id"] == prop_id)
        assert [item["id"] for item in row["amenities"]] == [gym.id]


async def test_owner_cannot_write_moderator_keys(
    authenticated_client: AsyncClient, db_session, test_user
):
    prop = await PropertyFactory.create(
        db_session,
        owner=test_user,
        purpose=PropertyPurpose.buy,
        listing_preferences={"moderation_status": "live", "moderated_by": 9},
    )
    prop_id = prop.id

    resp = await authenticated_client.put(
        f"/api/v1/properties/{prop_id}",
        json={"listing_preferences": {"moderated_by": 1, "pets": "no"}},
    )

    assert resp.status_code == 200, resp.text
    db_session.expire_all()
    stored = await db_session.get(Property, prop_id)
    await db_session.refresh(stored)
    assert stored.listing_preferences["moderated_by"] == 9
    assert stored.listing_preferences["pets"] == "no"


async def test_stay_dates_are_dates(client: AsyncClient):
    bad = await client.get(
        "/api/v1/properties", params={"check_in": "next week", "check_out": "2026-11-05"}
    )
    ok = await client.get(
        "/api/v1/properties", params={"check_in": "2026-11-01", "check_out": "2026-11-05"}
    )

    assert bad.status_code == 422, bad.text
    assert ok.status_code == 200, ok.text


async def test_numeric_list_filters_are_bounded(client: AsyncClient):
    too_big = await client.get("/api/v1/properties", params={"price_max": "100000000000"})
    negative_area = await client.get("/api/v1/properties", params={"area_min": -1})
    too_many_bedrooms = await client.get("/api/v1/properties", params={"bedrooms_min": 500})

    assert too_big.status_code == 422, too_big.text
    assert negative_area.status_code == 422, negative_area.text
    assert too_many_bedrooms.status_code == 422, too_many_bedrooms.text
