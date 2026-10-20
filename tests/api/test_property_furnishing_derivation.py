"""furnishing_level is derived from room-level furnishing (decisions.md, Wave 3d).

A listing that carries rooms (listing_preferences.rooms[].furnishing_level) gets the highest
room level on create and update. The client's furnishing_level is ignored for such a listing.
A listing without rooms keeps the client value.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from httpx import AsyncClient

from app.config import settings
from app.core.exceptions import ValidationException
from app.models.enums import PropertyPurpose, PropertyType
from app.services.property.helpers import derive_furnishing_level
from tests.fixtures.factories import PropertyFactory

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _isolated_cache(monkeypatch):
    """A fresh in-memory cache for each test (the default is disk)."""
    import app.core.cache as cache_pkg

    monkeypatch.setattr(settings, "CACHE_BACKEND", "memory")
    monkeypatch.setattr(cache_pkg, "_cache_manager", None)
    yield
    monkeypatch.setattr(cache_pkg, "_cache_manager", None)


def _rooms(*levels: str | None) -> list[dict]:
    return [
        {"name": f"Room {i}", **({"furnishing_level": level} if level else {})}
        for i, level in enumerate(levels, start=1)
    ]


def _body(property_type: str = "flatmate", **overrides) -> dict:
    body = {
        "title": "Room in Indiranagar",
        "property_type": property_type,
        "purpose": "rent",
        "base_price": 15000,
        "monthly_rent": 15000,
        "city": "Bengaluru",
        "locality": "Indiranagar",
    }
    body.update(overrides)
    return body


async def _stored(db_session, owner, rooms, level=None):
    return await PropertyFactory.create(
        db_session,
        owner=owner,
        property_type=PropertyType.pg,
        purpose=PropertyPurpose.rent,
        monthly_rent=Decimal("12000"),
        furnishing_level=level,
        is_available=True,
        listing_preferences={"moderation_status": "live", "rooms": rooms},
    )


# --- The rule on its own -----------------------------------------------------------


def test_derive_takes_the_highest_room_level():
    prefs = {"rooms": _rooms("unfurnished", "furnished", "semi_furnished")}
    assert derive_furnishing_level(prefs) == "furnished"
    assert derive_furnishing_level({"rooms": _rooms("unfurnished", "semi_furnished")}) == (
        "semi_furnished"
    )
    assert derive_furnishing_level({"rooms": _rooms("unfurnished")}) == "unfurnished"


@pytest.mark.parametrize(
    "prefs",
    [None, {}, {"rooms": None}, {"rooms": []}, {"rooms": _rooms(None, None)}, {"rooms": "x"}],
)
def test_derive_is_none_without_room_levels(prefs):
    assert derive_furnishing_level(prefs) is None


def test_derive_ignores_rooms_without_a_level():
    assert derive_furnishing_level({"rooms": _rooms(None, "semi_furnished", None)}) == (
        "semi_furnished"
    )


def test_derive_rejects_an_unknown_level():
    with pytest.raises(ValidationException):
        derive_furnishing_level({"rooms": _rooms("furnished", "lavish")})


# --- Create ------------------------------------------------------------------------


@pytest.mark.parametrize("property_type", ["flatmate", "pg"])
async def test_create_derives_the_level_and_ignores_the_client_value(
    authenticated_client: AsyncClient, property_type: str
):
    resp = await authenticated_client.post(
        "/api/v1/properties",
        json=_body(
            property_type,
            furnishing_level="unfurnished",
            listing_preferences={"rooms": _rooms("semi_furnished", "furnished")},
        ),
    )

    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["furnishing_level"] == "furnished"
    assert [room["furnishing_level"] for room in body["listing_preferences"]["rooms"]] == [
        "semi_furnished",
        "furnished",
    ]


async def test_create_without_rooms_keeps_the_client_value(authenticated_client: AsyncClient):
    kept = await authenticated_client.post(
        "/api/v1/properties", json=_body(furnishing_level="semi_furnished")
    )
    unset = await authenticated_client.post("/api/v1/properties", json=_body())
    no_levels = await authenticated_client.post(
        "/api/v1/properties",
        json=_body(furnishing_level="unfurnished", listing_preferences={"rooms": _rooms(None)}),
    )

    assert kept.status_code == 201, kept.text
    assert kept.json()["furnishing_level"] == "semi_furnished"
    assert unset.status_code == 201, unset.text
    assert unset.json()["furnishing_level"] is None
    assert no_levels.status_code == 201, no_levels.text
    assert no_levels.json()["furnishing_level"] == "unfurnished"


async def test_create_with_an_unknown_room_level_is_422(authenticated_client: AsyncClient):
    resp = await authenticated_client.post(
        "/api/v1/properties",
        json=_body(listing_preferences={"rooms": _rooms("lavish")}),
    )

    assert resp.status_code == 422, resp.text


# --- Update ------------------------------------------------------------------------


async def test_update_derives_the_level_from_new_rooms(
    authenticated_client: AsyncClient, db_session, test_user
):
    prop = await _stored(db_session, test_user, rooms=_rooms("furnished"), level="furnished")

    resp = await authenticated_client.put(
        f"/api/v1/properties/{prop.id}",
        json={"listing_preferences": {"rooms": _rooms("unfurnished", "semi_furnished")}},
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["furnishing_level"] == "semi_furnished"


async def test_update_ignores_the_client_value_when_rooms_are_stored(
    authenticated_client: AsyncClient, db_session, test_user
):
    prop = await _stored(db_session, test_user, rooms=_rooms("furnished"), level="furnished")

    resp = await authenticated_client.put(
        f"/api/v1/properties/{prop.id}", json={"furnishing_level": "unfurnished"}
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["furnishing_level"] == "furnished"


async def test_update_without_rooms_takes_the_client_value(
    authenticated_client: AsyncClient, db_session, test_user
):
    prop = await _stored(db_session, test_user, rooms=_rooms("furnished"), level="furnished")

    # Clearing the rooms returns the listing to the client value.
    resp = await authenticated_client.put(
        f"/api/v1/properties/{prop.id}",
        json={"listing_preferences": {"rooms": []}, "furnishing_level": "unfurnished"},
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["furnishing_level"] == "unfurnished"


async def test_update_with_an_unknown_room_level_is_422(
    authenticated_client: AsyncClient, db_session, test_user
):
    prop = await _stored(db_session, test_user, rooms=_rooms("furnished"), level="furnished")

    resp = await authenticated_client.put(
        f"/api/v1/properties/{prop.id}",
        json={"listing_preferences": {"rooms": _rooms("lavish")}},
    )

    assert resp.status_code == 422, resp.text
