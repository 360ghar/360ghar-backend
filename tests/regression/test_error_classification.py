"""Only client input errors are 422. A pydantic ValidationError on server data is a 500."""

from __future__ import annotations

from fastapi.testclient import TestClient
from pydantic import BaseModel, Field, ValidationError

from app.core.exceptions import ValidationException, client_input_error
from app.factory import create_app
from app.schemas.base import WriteModel


class Price(WriteModel):
    price: int = Field(gt=0)


class ServerRow(BaseModel):
    count: int


def _client() -> TestClient:
    app = create_app(testing=True)

    @app.post("/_cls/body")
    async def body(payload: Price):
        return {"ok": True}

    @app.get("/_cls/response-build")
    async def response_build():
        # Server data that does not fit the response model.
        ServerRow.model_validate({"count": "not a number"})

    @app.post("/_cls/client-input")
    async def client_input():
        try:
            Price.model_validate({"price": -1})
        except ValidationError as exc:
            raise client_input_error(exc, "body") from exc

    @app.get("/_cls/explicit")
    async def explicit():
        raise ValidationException(detail="Bad slug", error_code="INVALID_SLUG")

    return TestClient(app, raise_server_exceptions=False)


def test_request_body_validation_is_422():
    resp = _client().post("/_cls/body", json={"price": 0})
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "VALIDATION_ERROR"
    assert resp.json()["error"]["details"]["fields"][0]["field"] == "body.price"


def test_pydantic_validation_error_on_server_data_is_500():
    resp = _client().get("/_cls/response-build")
    assert resp.status_code == 500
    body = resp.json()["error"]
    assert body["code"] == "INTERNAL_ERROR"
    assert "count" not in resp.text


def test_client_input_error_helper_is_422_with_prefixed_field():
    resp = _client().post("/_cls/client-input")
    assert resp.status_code == 422
    fields = resp.json()["error"]["details"]["fields"]
    assert fields[0]["field"] == "body.price"


def test_explicit_validation_exception_is_422():
    resp = _client().get("/_cls/explicit")
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "INVALID_SLUG"
