"""BE-property fix round 1: status filter, cache binding and masking, agent fallback,
geo clearing, field names in 422 errors, amenity timestamps, recommendation cursor.

Each test pins one reviewer finding (contract-audit/handoffs/BE-property.md, round 1).
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import text

import app.services.property.search as search_module
from app.config import settings
from app.models.enums import PropertyPurpose, PropertyStatus
from app.models.users import UserSwipe
from app.utils.geo import wkt_point
from tests.fixtures.factories import AgentFactory, AmenityFactory, PropertyFactory

pytestmark = pytest.mark.asyncio

COMPANY = "+918000000000"
AGENT_NUMBER = "+918111111111"
OWNER_PHONE = "+919000000000"
MODERATOR_KEYS = {"moderated_by": 99, "moderation_reason": "spam"}


@pytest.fixture(autouse=True)
def _company_number(monkeypatch):
    monkeypatch.setattr(settings, "COMPANY_CONTACT_NUMBER", COMPANY)


@pytest_asyncio.fixture
async def connected_cache(monkeypatch):
    """A connected in-memory cache for this test. The default manager is disconnected in
    tests, so every other test takes the miss path only."""
    import app.core.cache as cache_pkg

    monkeypatch.setattr(settings, "CACHE_BACKEND", "memory")
    monkeypatch.setattr(cache_pkg, "_cache_manager", None)
    manager = cache_pkg.get_cache_manager()
    await manager.connect()
    assert manager.is_available()
    yield manager
    await manager.disconnect()
    monkeypatch.setattr(cache_pkg, "_cache_manager", None)


@pytest_asyncio.fixture
async def assigned_agent(db_session, test_user, test_agent_user):
    """An active agent who manages the owner. The agent user is assigned to the same agent.

    Declared before the agent client fixture, so the client's user snapshot has agent_id."""
    agent = await AgentFactory.create(db_session, contact_number=AGENT_NUMBER)
    test_user.agent_id = agent.id
    test_agent_user.agent_id = agent.id
    await db_session.flush()
    await db_session.refresh(test_user)
    await db_session.refresh(test_agent_user)
    return agent


def _ids(resp) -> list[int]:
    assert resp.status_code == 200, resp.text
    return [item["id"] for item in resp.json()["items"]]


# --- Finding 1: an explicit status filter ignores is_available ----------------------


async def _sold_unavailable(db_session, owner):
    return await PropertyFactory.create(
        db_session,
        owner=owner,
        purpose=PropertyPurpose.buy,
        status=PropertyStatus.sold,
        is_available=False,
    )


async def test_explicit_status_hides_unavailable_from_anonymous_callers(
    client, db_session, test_user
):
    sold = await _sold_unavailable(db_session, test_user)

    resp = await client.get("/api/v1/properties", params={"status": "sold"})

    assert sold.id not in _ids(resp)


async def test_explicit_status_hides_unavailable_from_owner(user_client, db_session, test_user):
    sold = await _sold_unavailable(db_session, test_user)

    resp = await user_client.get("/api/v1/properties", params={"status": "sold"})

    assert sold.id not in _ids(resp)


async def test_explicit_status_lists_unavailable_for_admin(admin_client, db_session, test_user):
    sold = await _sold_unavailable(db_session, test_user)

    resp = await admin_client.get("/api/v1/properties", params={"status": "sold"})

    assert sold.id in _ids(resp)


async def test_default_list_still_hides_unavailable_listings(client, db_session, test_user):
    hidden = await PropertyFactory.create(
        db_session,
        owner=test_user,
        purpose=PropertyPurpose.buy,
        status=PropertyStatus.sold,
        is_available=False,
    )

    resp = await client.get("/api/v1/properties", params={"purpose": "buy"})

    assert hidden.id not in _ids(resp)


# --- Finding 2: the anonymous cache key carries include_total -----------------------


async def test_cached_total_follows_include_total(client, db_session, test_user, connected_cache):
    await PropertyFactory.create(
        db_session, owner=test_user, purpose=PropertyPurpose.buy, locality="Cache Total Lane"
    )
    params = {"purpose": "buy", "locality": "Cache Total Lane"}

    counted = await client.get("/api/v1/properties", params={**params, "include_total": "true"})
    plain = await client.get("/api/v1/properties", params=params)
    counted_again = await client.get(
        "/api/v1/properties", params={**params, "include_total": "true"}
    )

    assert counted.json()["total"] >= 1
    assert plain.json()["total"] is None
    assert counted_again.json()["total"] == counted.json()["total"]


# --- Finding 12 and 3: cache hits are masked per viewer, with the agent fallback ----


async def test_anonymous_list_cache_hit_masks_owner_contact(
    client, db_session, test_user, assigned_agent, connected_cache
):
    prop = await PropertyFactory.create(
        db_session,
        owner=test_user,
        purpose=PropertyPurpose.buy,
        locality="Cache Mask Lane",
        title="Before",
        owner_contact=OWNER_PHONE,
        listing_preferences={"moderation_status": "live", **MODERATOR_KEYS},
    )
    params = {"purpose": "buy", "locality": "Cache Mask Lane"}

    first = await client.get("/api/v1/properties", params=params)
    row = next(item for item in first.json()["items"] if item["id"] == prop.id)
    assert row["owner_contact"] == AGENT_NUMBER

    # The row changes in the database. The second request must still see the cached
    # title, which proves it is a cache hit.
    prop.title = "After"
    await db_session.flush()

    second = await client.get("/api/v1/properties", params=params)

    assert second.status_code == 200, second.text
    hit = next(item for item in second.json()["items"] if item["id"] == prop.id)
    assert hit["title"] == "Before"
    assert hit["owner_contact"] == AGENT_NUMBER
    assert OWNER_PHONE not in second.text
    assert set(MODERATOR_KEYS).isdisjoint(hit["listing_preferences"] or {})
    assert "agent" not in hit


async def test_anonymous_recommendations_cache_hit_masks_owner_contact(
    client, db_session, test_user, connected_cache
):
    prop = await PropertyFactory.create(
        db_session,
        owner=test_user,
        purpose=PropertyPurpose.buy,
        title="Before",
        owner_contact=OWNER_PHONE,
        listing_preferences={"moderation_status": "live", **MODERATOR_KEYS},
    )

    first = await client.get("/api/v1/properties/recommendations", params={"limit": 50})
    assert first.status_code == 200, first.text
    assert prop.id in [item["id"] for item in first.json()["items"]]

    prop.title = "After"
    await db_session.flush()

    second = await client.get("/api/v1/properties/recommendations", params={"limit": 50})

    assert second.status_code == 200, second.text
    hit = next(item for item in second.json()["items"] if item["id"] == prop.id)
    assert hit["title"] == "Before"
    assert hit["owner_contact"] == COMPANY
    assert OWNER_PHONE not in second.text
    assert set(MODERATOR_KEYS).isdisjoint(hit["listing_preferences"] or {})


# --- Finding 6: write responses show the assigned agent's number --------------------


async def test_assigned_agent_create_response_shows_the_agent_number(
    assigned_agent, agent_authenticated_client: AsyncClient, test_user
):
    resp = await agent_authenticated_client.post(
        "/api/v1/properties",
        params={"owner_id": test_user.id},
        json={
            "title": "Agent created",
            "property_type": "apartment",
            "purpose": "buy",
            "base_price": 5_000_000,
            "city": "Mumbai",
            "locality": "Andheri",
            "owner_contact": OWNER_PHONE,
        },
    )

    assert resp.status_code == 201, resp.text
    assert resp.json()["owner_contact"] == AGENT_NUMBER
    assert "agent" not in resp.json()


async def test_assigned_agent_update_and_read_show_the_agent_number(
    assigned_agent, agent_authenticated_client: AsyncClient, db_session, test_user
):
    prop = await PropertyFactory.create(
        db_session, owner=test_user, purpose=PropertyPurpose.buy, owner_contact=OWNER_PHONE
    )

    put = await agent_authenticated_client.put(
        f"/api/v1/properties/{prop.id}", json={"title": "Agent edit"}
    )
    get = await agent_authenticated_client.get(f"/api/v1/properties/{prop.id}")

    assert put.status_code == 200, put.text
    assert put.json()["owner_contact"] == AGENT_NUMBER
    assert get.status_code == 200, get.text
    assert get.json()["owner_contact"] == AGENT_NUMBER
    assert get.json()["agent"]["contact_number"] == AGENT_NUMBER


# --- Finding 4: clearing a coordinate clears the stored point -----------------------


async def test_clearing_coordinates_removes_the_listing_from_geo_search(
    authenticated_client: AsyncClient, db_session, test_user
):
    lat, lng = 19.0760, 72.8777
    prop = await PropertyFactory.create(
        db_session,
        owner=test_user,
        purpose=PropertyPurpose.buy,
        latitude=lat,
        longitude=lng,
        location=wkt_point(lng, lat),
    )
    near = {"lat": lat, "lng": lng, "radius": 1}

    before = await authenticated_client.get("/api/v1/properties", params=near)
    assert prop.id in _ids(before)

    put = await authenticated_client.put(
        f"/api/v1/properties/{prop.id}", json={"latitude": None, "longitude": None}
    )
    after = await authenticated_client.get("/api/v1/properties", params=near)

    assert put.status_code == 200, put.text
    assert put.json()["latitude"] is None
    assert put.json()["longitude"] is None
    assert prop.id not in _ids(after)


# --- Finding 8: filter-model errors name the query parameter ------------------------


async def test_inverted_price_range_error_is_named_query(client: AsyncClient):
    resp = await client.get("/api/v1/properties", params={"price_min": 500000, "price_max": 100000})

    assert resp.status_code == 422, resp.text
    fields = [item["field"] for item in resp.json()["error"]["details"]["fields"]]
    assert fields == ["query"]


async def test_out_of_range_bedrooms_error_names_the_query_parameter(client: AsyncClient):
    resp = await client.get("/api/v1/properties", params={"bedrooms_min": 51})

    assert resp.status_code == 422, resp.text
    fields = [item["field"] for item in resp.json()["error"]["details"]["fields"]]
    assert fields == ["query.bedrooms_min"]


# --- Finding 7: amenity timestamps are UTC with Z -----------------------------------


async def test_amenity_timestamps_end_with_z(client: AsyncClient, db_session):
    await AmenityFactory.create(db_session, title="Zulu Amenity")

    resp = await client.get("/api/v1/amenities")

    assert resp.status_code == 200, resp.text
    item = resp.json()["items"][0]
    assert item["created_at"].endswith("Z")
    assert item["updated_at"].endswith("Z")


# --- Finding 14: the recommendation cursor survives a new like ----------------------


async def test_recommendation_cursor_survives_a_new_like(
    authenticated_client: AsyncClient, db_session, test_user, test_user_2
):
    first_listing = await PropertyFactory.create(
        db_session, owner=test_user_2, purpose=PropertyPurpose.buy
    )
    await PropertyFactory.create(db_session, owner=test_user_2, purpose=PropertyPurpose.buy)

    first = await authenticated_client.get(
        "/api/v1/properties/recommendations", params={"limit": 1}
    )
    assert first.status_code == 200, first.text
    cursor = first.json()["next_cursor"]
    assert cursor

    db_session.add(
        UserSwipe(
            user_id=test_user.id,
            property_id=first_listing.id,
            is_liked=True,
            target_type="property",
            swipe_action="like",
        )
    )
    await db_session.flush()

    second = await authenticated_client.get(
        "/api/v1/properties/recommendations", params={"limit": 1, "cursor": cursor}
    )

    assert second.status_code == 200, second.text


# --- Round 1 reviewer 10 (residual round 2): the status rule covers semantic search -----
# Each caller is its own test. user_client and admin_client override the auth dependencies
# on the shared app for the rest of the test, so one test cannot mix anonymous and
# authenticated calls.


async def _semantic_sold_listing(db_session, owner, monkeypatch):
    # The embedding service is unavailable here, so semantic search falls back to text.
    # (With a vector, the query joins property_embeddings, which the test schema lacks.)
    monkeypatch.setattr(
        search_module,
        "embed_query",
        AsyncMock(side_effect=RuntimeError("embedding service unavailable")),
    )
    sold = await PropertyFactory.create(
        db_session,
        owner=owner,
        purpose=PropertyPurpose.buy,
        title="Sold sunny balcony flat",
        status=PropertyStatus.sold,
        is_available=False,
    )
    # The test schema has no FTS trigger, so set the search vector the trigger would set.
    await db_session.execute(
        text(
            "UPDATE properties SET \"__ts_vector__\" = to_tsvector('english', title) WHERE id = :id"
        ),
        {"id": sold.id},
    )
    return sold


SEMANTIC_STATUS_PARAMS = {"q": "sunny balcony", "status": "sold"}


async def test_semantic_search_status_hides_unavailable_from_anonymous(
    client, db_session, test_user, monkeypatch
):
    sold = await _semantic_sold_listing(db_session, test_user, monkeypatch)

    resp = await client.get("/api/v1/properties/semantic-search", params=SEMANTIC_STATUS_PARAMS)

    assert sold.id not in _ids(resp)


async def test_semantic_search_status_hides_unavailable_from_owner(
    user_client, db_session, test_user, monkeypatch
):
    sold = await _semantic_sold_listing(db_session, test_user, monkeypatch)

    resp = await user_client.get(
        "/api/v1/properties/semantic-search", params=SEMANTIC_STATUS_PARAMS
    )

    assert sold.id not in _ids(resp)


async def test_semantic_search_status_lists_unavailable_for_admin(
    admin_client, db_session, test_user, monkeypatch
):
    # The control: the listing matches q and status, so the admin call must list it.
    sold = await _semantic_sold_listing(db_session, test_user, monkeypatch)

    resp = await admin_client.get(
        "/api/v1/properties/semantic-search", params=SEMANTIC_STATUS_PARAMS
    )

    assert sold.id in _ids(resp)
