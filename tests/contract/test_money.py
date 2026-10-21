"""Money fields: out-of-range input gives 422, and output is a JSON number that is never -0.0."""

from __future__ import annotations

import math

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.factory import create_app
from app.schemas.base import Money, WriteModel


class Priced(WriteModel):
    price: Money


@pytest.fixture
def client() -> TestClient:
    app = create_app(testing=True)

    @app.post("/_contract/money")
    async def money(payload: Priced):
        return {"price": payload.price}

    return TestClient(app, raise_server_exceptions=False)


@pytest.mark.parametrize("value", [1e30, 10**30, "1e30", 1e26])
def test_out_of_range_money_is_a_validation_error(value):
    with pytest.raises(ValidationError) as exc:
        Priced(price=value)
    assert exc.value.errors()[0]["type"] == "value_error"


def test_out_of_range_money_over_http_is_422_not_500(client):
    resp = client.post("/_contract/money", json={"price": 1e30})
    assert resp.status_code == 422, resp.text
    body = resp.json()
    assert body["error"]["code"] == "VALIDATION_ERROR"
    fields = body["error"]["details"]["fields"]
    assert [(f["field"], f["type"]) for f in fields] == [("body.price", "value_error")]


def test_small_negative_money_is_positive_zero():
    out = Priced(price=-0.001).price
    assert out == 0.0
    assert math.copysign(1.0, out) == 1.0


def test_money_rounds_half_up_to_two_places():
    assert Priced(price="12.345").price == 12.35
    assert Priced(price=7).price == 7.0
