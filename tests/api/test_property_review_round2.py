"""BE-property fix round 2: minimum_stay_days is NOT NULL on create and update, and the
POST OpenAPI example uses a valid purpose.

Each test pins one reviewer finding (contract-audit/handoffs/BE-property.md, round 2).
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.models.enums import PropertyPurpose
from app.schemas.property import PropertyUpdate
from tests.fixtures.factories import PropertyFactory

pytestmark = pytest.mark.asyncio


def _field_errors(resp) -> list[dict]:
    assert resp.status_code == 422, resp.text
    return resp.json()["error"]["details"]["fields"]


# --- Finding 1: minimum_stay_days is NOT NULL ---------------------------------------


async def test_put_null_minimum_stay_days_is_422(
    authenticated_client: AsyncClient, db_session, test_user
):
    prop = await PropertyFactory.create(
        db_session, owner=test_user, purpose=PropertyPurpose.buy, minimum_stay_days=7
    )

    resp = await authenticated_client.put(
        f"/api/v1/properties/{prop.id}", json={"minimum_stay_days": None}
    )

    fields = _field_errors(resp)
    assert any(f["field"] == "body.minimum_stay_days" for f in fields), fields


async def test_post_null_minimum_stay_days_is_422(authenticated_client: AsyncClient):
    resp = await authenticated_client.post(
        "/api/v1/properties",
        json={
            "title": "Null stay",
            "property_type": "apartment",
            "purpose": "buy",
            "base_price": 5_000_000,
            "minimum_stay_days": None,
        },
    )

    fields = _field_errors(resp)
    assert any(f["field"] == "body.minimum_stay_days" for f in fields), fields


async def test_post_without_minimum_stay_days_defaults_to_one(authenticated_client: AsyncClient):
    resp = await authenticated_client.post(
        "/api/v1/properties",
        json={
            "title": "Default stay",
            "property_type": "apartment",
            "purpose": "buy",
            "base_price": 5_000_000,
        },
    )

    assert resp.status_code == 201, resp.text
    assert resp.json()["minimum_stay_days"] == 1


async def test_put_with_a_value_still_sets_minimum_stay_days(
    authenticated_client: AsyncClient, db_session, test_user
):
    prop = await PropertyFactory.create(db_session, owner=test_user, purpose=PropertyPurpose.buy)

    resp = await authenticated_client.put(
        f"/api/v1/properties/{prop.id}", json={"minimum_stay_days": 30}
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["minimum_stay_days"] == 30


async def test_property_update_schema_rejects_null_minimum_stay_days():
    # The PM PATCH path (pm_properties.update_managed_property) reuses PropertyUpdate.
    from pydantic import ValidationError

    with pytest.raises(ValidationError) as exc:
        PropertyUpdate.model_validate({"minimum_stay_days": None})

    assert exc.value.errors()[0]["loc"] == ("minimum_stay_days",)


# --- Finding 2: the POST example uses a valid purpose -------------------------------


def test_post_openapi_examples_use_valid_purposes():
    from app.api.api_v1.endpoints.properties import router

    route = next(
        r
        for r in router.routes
        if getattr(r, "path", None) == "" and "POST" in getattr(r, "methods", ())
    )
    examples = route.openapi_extra["requestBody"]["content"]["application/json"]["examples"]
    valid = {p.value for p in PropertyPurpose}

    purposes = {name: ex["value"]["purpose"] for name, ex in examples.items()}
    assert purposes["buy"] == "buy"
    assert set(purposes.values()) <= valid, purposes
