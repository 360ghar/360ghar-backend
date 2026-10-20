"""BE-property residual pass: cursor value types, owner null preferences, money round trip.

Each test pins one residual finding (contract-audit/handoffs/wave3-residuals.json, property).
The cursor tests take a real next_cursor, change one key value, and keep the filter binding,
so the request reaches the keyset code with a wrong type.
"""

from __future__ import annotations

import base64
import json
from collections.abc import Callable
from decimal import Decimal

import pytest
from httpx import AsyncClient

from app.models.enums import PropertyPurpose
from tests.fixtures.factories import AmenityFactory, PropertyFactory

pytestmark = pytest.mark.asyncio

MODERATOR_KEYS = {"moderated_by": 99, "moderation_reason": "spam"}


def _decode(cursor: str) -> dict:
    padded = cursor + "=" * (-len(cursor) % 4)
    return json.loads(base64.urlsafe_b64decode(padded))


INF = float("inf")  # json.dumps writes it as Infinity, which json.loads accepts


def _tamper(cursor: str, new_key: Callable[[list], list]) -> str:
    """The cursor with its key replaced. The filter binding (f) is kept."""
    payload = _decode(cursor)
    payload["k"] = new_key(payload["k"])
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _without_key(cursor: str) -> str:
    """The cursor with no key (k). The filter binding (f) is kept."""
    payload = _decode(cursor)
    del payload["k"]
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _assert_invalid_cursor(resp) -> None:
    assert resp.status_code == 400, resp.text
    assert resp.json()["error"]["code"] == "INVALID_CURSOR"


# --- Finding 2: a cursor with a wrong key value type gives 400, not 500 ---------------


async def test_price_cursor_with_text_value_is_400(client, db_session, test_user):
    for price in ("100000.00", "200000.00"):
        await PropertyFactory.create(
            db_session,
            owner=test_user,
            purpose=PropertyPurpose.buy,
            base_price=Decimal(price),
        )
    params = {"purpose": "buy", "sort_by": "price_low", "limit": 1}
    first = await client.get("/api/v1/properties", params=params)
    assert first.status_code == 200, first.text
    cursor = first.json()["next_cursor"]
    assert cursor

    bad = await client.get(
        "/api/v1/properties",
        params={**params, "cursor": _tamper(cursor, lambda k: [["abc"], k[1]])},
    )

    _assert_invalid_cursor(bad)


async def test_my_properties_cursor_with_bad_date_is_400(user_client, db_session, test_user):
    for _ in range(2):
        await PropertyFactory.create(db_session, owner=test_user, purpose=PropertyPurpose.buy)
    first = await user_client.get("/api/v1/properties/me", params={"limit": 1})
    assert first.status_code == 200, first.text
    cursor = first.json()["next_cursor"]
    assert cursor

    bad = await user_client.get(
        "/api/v1/properties/me",
        params={"limit": 1, "cursor": _tamper(cursor, lambda k: ["not-a-date", k[1]])},
    )

    _assert_invalid_cursor(bad)


async def test_recommendation_cursor_with_bad_date_is_400(
    authenticated_client: AsyncClient, db_session, test_user_2
):
    for _ in range(2):
        await PropertyFactory.create(db_session, owner=test_user_2, purpose=PropertyPurpose.buy)
    first = await authenticated_client.get(
        "/api/v1/properties/recommendations", params={"limit": 1}
    )
    assert first.status_code == 200, first.text
    cursor = first.json()["next_cursor"]
    assert cursor

    def bad_created_at(key: list) -> list:
        # Recommendation key: [preference score, likes, views, created_at], id
        return [[*key[0][:3], "not-a-date"], key[1]]

    bad = await authenticated_client.get(
        "/api/v1/properties/recommendations",
        params={"limit": 1, "cursor": _tamper(cursor, bad_created_at)},
    )

    _assert_invalid_cursor(bad)


async def test_amenity_cursor_with_text_id_is_400(client, db_session):
    await AmenityFactory.create(db_session, title="Gym")
    await AmenityFactory.create(db_session, title="Pool")
    first = await client.get("/api/v1/amenities", params={"limit": 1})
    assert first.status_code == 200, first.text
    cursor = first.json()["next_cursor"]
    assert cursor

    # The title of the first row equals the tampered key, so the old comparison of an int id
    # with a str raised a TypeError on that row.
    bad = await client.get(
        "/api/v1/amenities", params={"limit": 1, "cursor": _tamper(cursor, lambda k: [k[0], "x"])}
    )

    _assert_invalid_cursor(bad)


# --- Finding 3: a null listing_preferences from an owner keeps moderator keys ---------


async def test_owner_null_listing_preferences_keeps_stored_keys(user_client, db_session, test_user):
    prop = await PropertyFactory.create(
        db_session,
        owner=test_user,
        purpose=PropertyPurpose.buy,
        listing_preferences={"moderation_status": "live", **MODERATOR_KEYS},
    )

    resp = await user_client.put(
        f"/api/v1/properties/{prop.id}", json={"listing_preferences": None}
    )

    assert resp.status_code == 200, resp.text
    await db_session.refresh(prop)
    assert prop.listing_preferences is not None
    for key, value in MODERATOR_KEYS.items():
        assert prop.listing_preferences[key] == value


# --- Finding 1 (be-property-13): money and coordinates keep their precision -----------
# This test reads the ORM on the test schema (create_all). The database guard for these columns is
# the CI drift gate, scripts/verify_schema_drift.py, run against a migrated database.


async def test_money_and_coordinates_round_trip_exactly(db_session, test_user):
    # 123456789.12 does not fit NUMERIC(10,2); a REAL column loses the paise.
    prop = await PropertyFactory.create(
        db_session,
        owner=test_user,
        purpose=PropertyPurpose.buy,
        base_price=Decimal("123456789.12"),
        latitude=19.07601234567,
        longitude=72.87761234567,
    )

    await db_session.refresh(prop)

    assert prop.base_price == Decimal("123456789.12")
    assert prop.latitude == 19.07601234567
    assert prop.longitude == 72.87761234567


# --- Residual round 2, reviewer 1: numbers outside the SQL range, or not finite ---------
# Each case used to raise DataError (HTTP 500) at the CAST to the sort key's SQL type.


async def test_popular_cursor_like_count_above_int4_is_400(client, db_session, test_user):
    for _ in range(2):
        await PropertyFactory.create(db_session, owner=test_user, purpose=PropertyPurpose.buy)
    params = {"sort_by": "popular", "limit": 1}
    first = await client.get("/api/v1/properties", params=params)
    assert first.status_code == 200, first.text
    cursor = first.json()["next_cursor"]
    assert cursor

    bad = await client.get(
        "/api/v1/properties",
        params={**params, "cursor": _tamper(cursor, lambda k: [[3_000_000_000, k[0][1]], k[1]])},
    )

    _assert_invalid_cursor(bad)


async def test_popular_cursor_infinity_is_400(client, db_session, test_user):
    for _ in range(2):
        await PropertyFactory.create(db_session, owner=test_user, purpose=PropertyPurpose.buy)
    params = {"sort_by": "popular", "limit": 1}
    first = await client.get("/api/v1/properties", params=params)
    assert first.status_code == 200, first.text
    cursor = first.json()["next_cursor"]
    assert cursor

    bad = await client.get(
        "/api/v1/properties",
        params={**params, "cursor": _tamper(cursor, lambda k: [[INF, k[0][1]], k[1]])},
    )

    _assert_invalid_cursor(bad)


async def test_price_cursor_infinity_is_400(client, db_session, test_user):
    for price in ("100000.00", "200000.00"):
        await PropertyFactory.create(
            db_session,
            owner=test_user,
            purpose=PropertyPurpose.buy,
            base_price=Decimal(price),
        )
    params = {"purpose": "buy", "sort_by": "price_low", "limit": 1}
    first = await client.get("/api/v1/properties", params=params)
    assert first.status_code == 200, first.text
    cursor = first.json()["next_cursor"]
    assert cursor

    bad = await client.get(
        "/api/v1/properties",
        params={**params, "cursor": _tamper(cursor, lambda k: [[INF], k[1]])},
    )

    _assert_invalid_cursor(bad)


async def test_recommendation_cursor_score_above_int4_is_400(
    authenticated_client: AsyncClient, db_session, test_user_2
):
    for _ in range(2):
        await PropertyFactory.create(db_session, owner=test_user_2, purpose=PropertyPurpose.buy)
    first = await authenticated_client.get(
        "/api/v1/properties/recommendations", params={"limit": 1}
    )
    assert first.status_code == 200, first.text
    cursor = first.json()["next_cursor"]
    assert cursor

    # Recommendation key: [preference score, likes, views, created_at], id
    bad = await authenticated_client.get(
        "/api/v1/properties/recommendations",
        params={
            "limit": 1,
            "cursor": _tamper(cursor, lambda k: [[3_000_000_000, *k[0][1:]], k[1]]),
        },
    )

    _assert_invalid_cursor(bad)


# --- Residual round 2, reviewer 2: the cursor id is bigint (properties.id) ---------------


async def test_my_properties_cursor_id_above_int4_is_not_a_500(user_client, db_session, test_user):
    for _ in range(2):
        await PropertyFactory.create(db_session, owner=test_user, purpose=PropertyPurpose.buy)
    first = await user_client.get("/api/v1/properties/me", params={"limit": 1})
    assert first.status_code == 200, first.text
    cursor = first.json()["next_cursor"]
    assert cursor

    # properties.id is bigint, so 3000000000 is a valid position: the page is served.
    resp = await user_client.get(
        "/api/v1/properties/me",
        params={"limit": 1, "cursor": _tamper(cursor, lambda k: [k[0], 3_000_000_000])},
    )

    assert resp.status_code == 200, resp.text


async def test_my_properties_cursor_id_beyond_int8_is_400(user_client, db_session, test_user):
    for _ in range(2):
        await PropertyFactory.create(db_session, owner=test_user, purpose=PropertyPurpose.buy)
    first = await user_client.get("/api/v1/properties/me", params={"limit": 1})
    assert first.status_code == 200, first.text
    cursor = first.json()["next_cursor"]
    assert cursor

    bad = await user_client.get(
        "/api/v1/properties/me",
        params={"limit": 1, "cursor": _tamper(cursor, lambda k: [k[0], 2**63])},
    )

    _assert_invalid_cursor(bad)


# --- Residual round 2, reviewer 3: ISO week dates and out-of-range datetimes ------------
# Python accepts 2024-W01-1. Postgres rejects it (InvalidDatetimeFormat, HTTP 500).


async def test_newest_cursor_with_week_date_is_400(client, db_session, test_user):
    for _ in range(2):
        await PropertyFactory.create(db_session, owner=test_user, purpose=PropertyPurpose.buy)
    first = await client.get("/api/v1/properties", params={"limit": 1})
    assert first.status_code == 200, first.text
    cursor = first.json()["next_cursor"]
    assert cursor

    bad = await client.get(
        "/api/v1/properties",
        params={"limit": 1, "cursor": _tamper(cursor, lambda k: [["2024-W01-1"], k[1]])},
    )

    _assert_invalid_cursor(bad)


async def test_newest_cursor_datetime_outside_utc_range_is_400(client, db_session, test_user):
    for _ in range(2):
        await PropertyFactory.create(db_session, owner=test_user, purpose=PropertyPurpose.buy)
    first = await client.get("/api/v1/properties", params={"limit": 1})
    assert first.status_code == 200, first.text
    cursor = first.json()["next_cursor"]
    assert cursor

    # Python reads this as a valid time. In UTC it is year 10000, which Postgres cannot hold.
    bad = await client.get(
        "/api/v1/properties",
        params={
            "limit": 1,
            "cursor": _tamper(cursor, lambda k: [["9999-12-31T23:59:59-05:00"], k[1]]),
        },
    )

    _assert_invalid_cursor(bad)


async def test_my_properties_cursor_with_week_date_is_400(user_client, db_session, test_user):
    for _ in range(2):
        await PropertyFactory.create(db_session, owner=test_user, purpose=PropertyPurpose.buy)
    first = await user_client.get("/api/v1/properties/me", params={"limit": 1})
    assert first.status_code == 200, first.text
    cursor = first.json()["next_cursor"]
    assert cursor

    # The owner cursor is single-key: [created_at, id].
    bad = await user_client.get(
        "/api/v1/properties/me",
        params={"limit": 1, "cursor": _tamper(cursor, lambda k: ["2024-W01-1", k[1]])},
    )

    _assert_invalid_cursor(bad)


async def test_recommendation_cursor_with_week_date_is_400(
    authenticated_client: AsyncClient, db_session, test_user_2
):
    for _ in range(2):
        await PropertyFactory.create(db_session, owner=test_user_2, purpose=PropertyPurpose.buy)
    first = await authenticated_client.get(
        "/api/v1/properties/recommendations", params={"limit": 1}
    )
    assert first.status_code == 200, first.text
    cursor = first.json()["next_cursor"]
    assert cursor

    bad = await authenticated_client.get(
        "/api/v1/properties/recommendations",
        params={
            "limit": 1,
            "cursor": _tamper(cursor, lambda k: [[*k[0][:3], "2024-W01-1"], k[1]]),
        },
    )

    _assert_invalid_cursor(bad)


# --- Residual round 2, reviewer 5: a cursor with no key is malformed, not a first page ---


async def test_newest_cursor_without_key_is_400(client, db_session, test_user):
    for _ in range(2):
        await PropertyFactory.create(db_session, owner=test_user, purpose=PropertyPurpose.buy)
    first = await client.get("/api/v1/properties", params={"limit": 1})
    assert first.status_code == 200, first.text
    cursor = first.json()["next_cursor"]
    assert cursor

    _assert_invalid_cursor(
        await client.get("/api/v1/properties", params={"limit": 1, "cursor": _without_key(cursor)})
    )


async def test_my_properties_cursor_without_key_is_400(user_client, db_session, test_user):
    for _ in range(2):
        await PropertyFactory.create(db_session, owner=test_user, purpose=PropertyPurpose.buy)
    first = await user_client.get("/api/v1/properties/me", params={"limit": 1})
    assert first.status_code == 200, first.text
    cursor = first.json()["next_cursor"]
    assert cursor

    _assert_invalid_cursor(
        await user_client.get(
            "/api/v1/properties/me", params={"limit": 1, "cursor": _without_key(cursor)}
        )
    )


async def test_amenity_cursor_without_key_is_400(client, db_session):
    await AmenityFactory.create(db_session, title="Gym")
    await AmenityFactory.create(db_session, title="Pool")
    first = await client.get("/api/v1/amenities", params={"limit": 1})
    assert first.status_code == 200, first.text
    cursor = first.json()["next_cursor"]
    assert cursor

    _assert_invalid_cursor(
        await client.get("/api/v1/amenities", params={"limit": 1, "cursor": _without_key(cursor)})
    )
