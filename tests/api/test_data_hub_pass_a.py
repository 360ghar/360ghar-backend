"""Contract pass A (BE-content): data hub request validation over HTTP."""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_auction_detail_requires_kind(client):
    response = await client.get("/api/v1/data-hub/auctions/1")

    assert response.status_code == 422
    fields = response.json()["error"]["details"]["fields"]
    assert any(item["field"] == "query.kind" for item in fields)


@pytest.mark.asyncio
async def test_auction_detail_404_when_missing_in_the_named_table(client):
    response = await client.get("/api/v1/data-hub/auctions/999999?kind=court")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "AUCTION_NOT_FOUND"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "query",
    ["source=not_a_source", "type=vehicle", "property_type=Residential%20Flat"],
)
async def test_auction_list_rejects_unknown_enum_values(client, query):
    response = await client.get(f"/api/v1/data-hub/auctions?{query}")

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


@pytest.mark.asyncio
async def test_gazette_type_filter_is_enum_bound(client):
    response = await client.get("/api/v1/data-hub/gazette?type=not_a_type")

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_auction_list_rejects_unknown_query_keys(client):
    response = await client.get("/api/v1/data-hub/auctions?unknown_filter=1")

    assert response.status_code == 422
