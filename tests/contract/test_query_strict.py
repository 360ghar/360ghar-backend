"""Unknown query keys on /api/v1 routes give 422 VALIDATION_ERROR with query.<name> fields."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, FastAPI, Query
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from pydantic import BaseModel, Field

from app.api.api_v1.dependencies import query_params
from app.factory import create_app
from app.infrastructure.errors import register_exception_handlers
from app.schemas.pagination import CursorParams


class Filters(BaseModel):
    min_price: int | None = None
    max_price: int | None = Field(default=None, alias="maxPrice")


def _app_client() -> TestClient:
    return TestClient(create_app(testing=True), raise_server_exceptions=False)


def _route(app, path: str, method: str = "GET") -> APIRoute:
    return next(
        r for r in app.routes if isinstance(r, APIRoute) and r.path == path and method in r.methods
    )


def test_unknown_query_key_gives_422_with_query_field():
    resp = _app_client().get("/api/v1/tours", params={"bogus": "1"})
    assert resp.status_code == 422
    body = resp.json()
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert body["error"]["details"]["fields"] == [
        {"field": "query.bogus", "msg": "unknown parameter", "type": "extra_forbidden"}
    ]


def test_global_keys_are_accepted_on_any_route():
    resp = _app_client().get(
        "/api/v1/tours", params={"cursor": "", "limit": "5", "include_total": "true"}
    )
    # Auth is required, so the request reaches the auth check and never fails on query keys.
    assert resp.status_code == 401, resp.text
    assert resp.json()["error"]["code"] == "AUTH_HEADER_MISSING"
    assert "query." not in resp.text


def test_declared_keys_are_collected_through_sub_dependencies():
    app = create_app(testing=True)
    names = query_params.declared_query_names(_route(app, "/api/v1/properties").dependant)
    assert {"lat", "lng", "radius", "q"} <= names
    assert {"cursor", "limit", "include_total"} <= names


def test_cursor_params_declares_the_global_keys():
    assert {"cursor", "limit", "include_total"} <= query_params.declared_query_names(
        _dependant_of(CursorParams)
    )


def test_webhook_routes_are_not_checked():
    resp = _app_client().post("/api/v1/webhooks/auth/password-changed", params={"bogus": "1"})
    # The only error is the missing body. The unknown query key is not reported.
    assert resp.status_code == 422, resp.text
    assert resp.json()["error"]["code"] == "VALIDATION_ERROR"
    assert resp.json()["error"]["details"]["fields"] == [
        {"field": "body", "msg": "Field required", "type": "missing"}
    ]


def test_query_model_fields_are_declared_names():
    async def endpoint(f: Annotated[Filters, Query()]):
        return {}

    dependant = APIRoute("/q", endpoint, methods=["GET"]).dependant
    assert {"min_price", "maxPrice"} <= query_params.declared_query_names(dependant)


def test_query_model_route_accepts_its_fields_and_rejects_others():
    app = FastAPI(dependencies=[Depends(query_params.reject_unknown_query_params)])
    register_exception_handlers(app)

    @app.get("/q")
    async def q(f: Annotated[Filters, Query()]):
        return {"ok": True}

    client = TestClient(app, raise_server_exceptions=False)
    ok = client.get("/q", params={"min_price": "5", "maxPrice": "9"})
    assert ok.status_code == 200, ok.text
    assert ok.json() == {"ok": True}

    bad = client.get("/q", params={"min_price": "5", "nope": "1"})
    assert bad.status_code == 422, bad.text
    assert bad.json()["error"]["details"]["fields"] == [
        {"field": "query.nope", "msg": "unknown parameter", "type": "extra_forbidden"}
    ]


def test_oauth_module_routes_are_excluded():
    async def endpoint():
        return None

    endpoint.__module__ = "app.api.api_v1.endpoints.oauth.token"
    route = APIRoute("/api/v1/mcp/oauth/token", endpoint, methods=["POST"])
    assert query_params._is_excluded(route)


def test_mcp_routes_are_excluded():
    async def endpoint():
        return None

    route = APIRoute("/mcp/tools", endpoint, methods=["GET"])
    assert query_params._is_excluded(route)


def _dependant_of(cls: type):
    from fastapi.dependencies.utils import get_dependant

    return get_dependant(path="/", call=cls)
