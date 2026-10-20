"""Cursor values checked inside keyset_filter and read_keyset (contract-audit foundations).

Each test takes a real next_cursor, changes one key value, and keeps the filter binding, so the
request reaches the keyset code with a bad value. The answer must be 400 INVALID_CURSOR.
The five endpoints that had their own checks get the UTC offset rule. A blog list, which has no
check of its own, proves that keyset_filter covers a domain by itself.
"""

from __future__ import annotations

import base64
import json
from collections.abc import Callable
from decimal import Decimal

import pytest
from httpx import AsyncClient

from app.models.blogs import BlogCategory
from app.models.enums import PropertyPurpose
from app.models.leads import Lead
from tests.fixtures.factories import AmenityFactory, PropertyFactory

pytestmark = pytest.mark.asyncio

OFFSET_16H = "2026-01-01T00:00:00+16:00"


def _tamper(cursor: str, new_key: Callable[[list], list]) -> str:
    """The cursor with its key replaced. The filter binding (f) is kept."""
    padded = cursor + "=" * (-len(cursor) % 4)
    payload = json.loads(base64.urlsafe_b64decode(padded))
    payload["k"] = new_key(payload["k"])
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _assert_invalid_cursor(resp) -> None:
    assert resp.status_code == 400, resp.text
    assert resp.json()["error"]["code"] == "INVALID_CURSOR"


async def test_properties_cursor_with_16_hour_offset_is_400(client, db_session, test_user):
    for _ in range(2):
        await PropertyFactory.create(
            db_session, owner=test_user, purpose=PropertyPurpose.buy, base_price=Decimal("100000")
        )
    params = {"purpose": "buy", "limit": 1}
    first = await client.get("/api/v1/properties", params=params)
    assert first.status_code == 200, first.text
    cursor = first.json()["next_cursor"]
    assert cursor

    bad = await client.get(
        "/api/v1/properties",
        params={**params, "cursor": _tamper(cursor, lambda k: [[OFFSET_16H], k[1]])},
    )

    _assert_invalid_cursor(bad)


async def test_my_properties_cursor_with_16_hour_offset_is_400(user_client, db_session, test_user):
    for _ in range(2):
        await PropertyFactory.create(db_session, owner=test_user, purpose=PropertyPurpose.buy)
    first = await user_client.get("/api/v1/properties/me", params={"limit": 1})
    assert first.status_code == 200, first.text
    cursor = first.json()["next_cursor"]
    assert cursor

    bad = await user_client.get(
        "/api/v1/properties/me",
        params={"limit": 1, "cursor": _tamper(cursor, lambda k: [OFFSET_16H, k[1]])},
    )

    _assert_invalid_cursor(bad)


async def test_recommendations_cursor_with_16_hour_offset_is_400(
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
            "cursor": _tamper(cursor, lambda k: [[*k[0][:3], OFFSET_16H], k[1]]),
        },
    )

    _assert_invalid_cursor(bad)


@pytest.mark.parametrize("bad_key", [lambda k: [123, k[1]], lambda k: [k[0], {"a": 1}]])
async def test_amenities_cursor_with_wrong_types_is_400(client, db_session, bad_key):
    await AmenityFactory.create(db_session, title="Gym")
    await AmenityFactory.create(db_session, title="Pool")
    first = await client.get("/api/v1/amenities", params={"limit": 1})
    assert first.status_code == 200, first.text
    cursor = first.json()["next_cursor"]
    assert cursor

    bad = await client.get(
        "/api/v1/amenities", params={"limit": 1, "cursor": _tamper(cursor, bad_key)}
    )

    _assert_invalid_cursor(bad)


async def test_leads_cursor_with_16_hour_offset_is_400(admin_client, db_session):
    for number in range(2):
        db_session.add(Lead(phone=f"98765001{number:02d}", name="Visitor", source="property_page"))
    await db_session.flush()
    first = await admin_client.get("/api/v1/leads", params={"limit": 1})
    assert first.status_code == 200, first.text
    cursor = first.json()["next_cursor"]
    assert cursor

    bad = await admin_client.get(
        "/api/v1/leads",
        params={"limit": 1, "cursor": _tamper(cursor, lambda k: [OFFSET_16H, k[1]])},
    )

    _assert_invalid_cursor(bad)


@pytest.mark.parametrize(
    "bad_key",
    [
        lambda k: [123, k[1]],  # the name is text
        lambda k: [["a"], k[1]],
        lambda k: [k[0], "x"],  # the id is an integer
        lambda k: [k[0], {"a": 1}],
        lambda k: [k[0], 2**63],  # above the bigint range
        lambda k: [k[0], None],
    ],
)
async def test_blog_categories_cursor_is_checked_by_keyset_filter(client, db_session, bad_key):
    """The blog list has no check of its own: keyset_filter alone gives 400, not a 500."""
    for name in ("Alpha Cursor", "Beta Cursor"):
        db_session.add(BlogCategory(name=name, slug=name.lower().replace(" ", "-")))
    await db_session.flush()
    first = await client.get("/api/v1/blog/categories", params={"limit": 1})
    assert first.status_code == 200, first.text
    cursor = first.json()["next_cursor"]
    assert cursor

    bad = await client.get(
        "/api/v1/blog/categories", params={"limit": 1, "cursor": _tamper(cursor, bad_key)}
    )

    _assert_invalid_cursor(bad)


async def test_blog_categories_valid_cursor_still_pages(client, db_session):
    for name in ("Alpha Page", "Beta Page", "Gamma Page"):
        db_session.add(BlogCategory(name=name, slug=name.lower().replace(" ", "-")))
    await db_session.flush()
    first = await client.get("/api/v1/blog/categories", params={"limit": 2})
    second = await client.get(
        "/api/v1/blog/categories",
        params={"limit": 2, "cursor": first.json()["next_cursor"]},
    )
    assert second.status_code == 200, second.text
    first_ids = {item["id"] for item in first.json()["items"]}
    assert first_ids.isdisjoint({item["id"] for item in second.json()["items"]})


async def test_cursor_page_always_sends_every_field(client, db_session):
    """The spec marks next_cursor, has_more, limit and total required, so the wire sends them all."""
    await AmenityFactory.create(db_session, title="Lift")
    resp = await client.get("/api/v1/amenities", params={"limit": 1})
    assert resp.status_code == 200, resp.text
    assert set(resp.json()) == {"items", "next_cursor", "has_more", "limit", "total"}
    assert resp.json()["total"] is None
