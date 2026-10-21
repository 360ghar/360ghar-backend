"""docs/openapi.json describes the wire: error bodies, security, servers, bounds, date-times.

The tests walk ``app.openapi()``, the same document ``scripts/generate_openapi.py`` writes.
"""

from __future__ import annotations

import json
import typing
from datetime import datetime
from typing import Annotated, Any

import pytest
from fastapi.testclient import TestClient
from pydantic import AfterValidator, BaseModel, Field

from app.factory import create_app, openapi_servers
from app.infrastructure.errors import ErrorEnvelope, ValidationErrorEnvelope, is_oauth_route
from app.infrastructure.openapi import (
    BEARER_SCHEME,
    HTTP_METHODS,
    WEBHOOK_SCHEME,
    customize_openapi,
    normalize_numeric_bounds,
)
from app.schemas import base as schema_base
from app.schemas.base import Money, UtcDateTime

ERROR_REF = "#/components/schemas/ErrorEnvelope"
VALIDATION_REF = "#/components/schemas/ValidationErrorEnvelope"
RAW_BOUND_KEYS = {"ge", "le", "gt", "lt"}


@pytest.fixture(scope="module")
def app():
    return create_app(testing=True)


@pytest.fixture(scope="module")
def spec(app) -> dict[str, Any]:
    return app.openapi()


def _operations(spec: dict[str, Any]):
    for path, item in spec["paths"].items():
        for method in HTTP_METHODS:
            if method in item:
                yield path, method, item[method]


def _json_schema(response: dict[str, Any]) -> dict[str, Any]:
    return response["content"]["application/json"]["schema"]


def _refs(schema: dict[str, Any]) -> list[str]:
    return [schema["$ref"]] if "$ref" in schema else [s["$ref"] for s in schema["anyOf"]]


def _raw_bound_keys(node: Any, path: str = "") -> list[str]:
    """Keys ge, le, gt, lt that hold a number. A property named ``ge`` holds a schema, so it is skipped."""
    found: list[str] = []
    if isinstance(node, dict):
        for key, value in node.items():
            if key in RAW_BOUND_KEYS and isinstance(value, (int, float)):
                found.append(f"{path}/{key}")
            found += _raw_bound_keys(value, f"{path}/{key}")
    elif isinstance(node, list):
        for index, value in enumerate(node):
            found += _raw_bound_keys(value, f"{path}[{index}]")
    return found


# --- Error responses -------------------------------------------------------------------------


def test_no_operation_references_http_validation_error(spec):
    text = json.dumps(spec)
    assert "HTTPValidationError" not in text
    assert '#/components/schemas/ValidationError"' not in text
    assert "HTTPValidationError" not in spec["components"]["schemas"]
    assert "ValidationError" not in spec["components"]["schemas"]
    for path, method, operation in _operations(spec):
        for response in operation["responses"].values():
            for media in response.get("content", {}).values():
                assert "HTTPValidationError" not in json.dumps(media), (method, path)


def test_every_422_is_the_validation_envelope(spec):
    seen = 0
    for path, method, operation in _operations(spec):
        response = operation["responses"].get("422")
        if response is None:
            continue
        seen += 1
        assert _refs(_json_schema(response)) == [VALIDATION_REF], (method, path)
    assert seen > 300


def test_every_api_v1_operation_can_return_422(spec):
    """An unknown query key gives 422 on any /api/v1 route, so each of them documents it."""
    for path, method, operation in _operations(spec):
        if path.startswith("/api/v1/") and "/oauth/" not in path and "/webhooks/" not in path:
            assert "422" in operation["responses"], (method, path)


def test_every_operation_has_the_default_error_response(spec):
    count = 0
    for path, method, operation in _operations(spec):
        count += 1
        default = operation["responses"].get("default")
        assert default is not None, f"{method.upper()} {path} has no default error response"
        refs = _refs(_json_schema(default))
        assert ERROR_REF in refs, (method, path)
        if not is_oauth_route(path):
            assert refs == [ERROR_REF], (method, path)
    assert count > 300


def test_oauth_routes_also_document_the_rfc_6749_body(spec):
    default = spec["paths"]["/api/v1/mcp/oauth/token"]["post"]["responses"]["default"]
    assert _refs(_json_schema(default)) == [
        "#/components/schemas/OAuthErrorResponse",
        ERROR_REF,
    ]


def test_declared_error_statuses_have_a_json_body(spec):
    for path, method, operation in _operations(spec):
        for status, response in operation["responses"].items():
            if status[:1] in ("4", "5"):
                assert "application/json" in response["content"], (method, path, status)


def test_error_components_describe_the_wire(spec):
    schemas = spec["components"]["schemas"]
    error_body = schemas["ErrorBody"]
    assert set(error_body["properties"]) == {"code", "message", "details"}
    assert error_body["required"] == ["code", "message"]  # details is absent when empty
    assert error_body["properties"]["details"]["type"] == "object"
    assert schemas["ErrorEnvelope"]["required"] == ["error"]
    fields = schemas["ValidationErrorDetails"]["properties"]["fields"]
    assert fields["type"] == "array"
    item = schemas[fields["items"]["$ref"].rsplit("/", 1)[1]]
    assert set(item["properties"]) == {"field", "msg", "type"}
    assert set(item["required"]) == {"field", "msg", "type"}
    assert schemas["ValidationErrorBody"]["required"] == ["code", "message", "details"]


def test_real_error_bodies_match_the_components(app):
    client = TestClient(app, raise_server_exceptions=False)
    not_found = client.get("/api/v1/no-such-route")
    assert not_found.status_code == 404
    ErrorEnvelope.model_validate(not_found.json())

    unauthorized = client.get("/api/v1/users/me")
    assert unauthorized.status_code == 401
    ErrorEnvelope.model_validate(unauthorized.json())

    unknown_key = client.get("/api/v1/amenities", params={"nope": "1"})
    assert unknown_key.status_code == 422
    body = ValidationErrorEnvelope.model_validate(unknown_key.json())
    assert [f.field for f in body.error.details.fields] == ["query.nope"]


def test_cursor_page_schemas_mark_every_field_required(spec):
    """The server always sends all five fields (null when unset), so clients get no "?"."""
    pages = {n: c for n, c in spec["components"]["schemas"].items() if n.startswith("CursorPage_")}
    assert len(pages) > 30
    for name, page in pages.items():
        assert {"items", "next_cursor", "has_more", "limit", "total"} <= set(page["required"]), name
    assert "unread_count" in spec["components"]["schemas"]["NotificationPage"]["required"]


def test_every_list_limit_parameter_documents_the_maximum(spec):
    limits = [
        parameter
        for _path, _method, operation in _operations(spec)
        for parameter in operation.get("parameters", [])
        if parameter["name"] == "limit" and parameter["in"] == "query"
    ]
    assert len(limits) > 50
    documented = [p for p in limits if p["schema"].get("maximum") == 100]
    # Routes with their own limit (agent messages, notifications) may use another range.
    assert len(documented) > 40


def test_a_limit_above_100_is_a_422_that_names_the_field(app):
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get("/api/v1/amenities", params={"limit": 200})
    assert resp.status_code == 422
    body = ValidationErrorEnvelope.model_validate(resp.json())
    assert [(f.field, f.type) for f in body.error.details.fields] == [
        ("query.limit", "less_than_equal")
    ]


# --- Security and servers ---------------------------------------------------------------------


def test_security_schemes_are_declared(spec):
    schemes = spec["components"]["securitySchemes"]
    assert schemes[BEARER_SCHEME]["type"] == "http"
    assert schemes[BEARER_SCHEME]["scheme"] == "bearer"
    assert schemes[WEBHOOK_SCHEME] == {
        "type": "apiKey",
        "in": "header",
        "name": "X-Supabase-Signature",
        "description": schemes[WEBHOOK_SCHEME]["description"],
    }
    assert "security" not in spec  # public routes stay public: security is per operation


def test_security_follows_the_auth_dependency(spec):
    paths = spec["paths"]
    required = paths["/api/v1/users/me"]["get"]
    assert required["security"] == [{BEARER_SCHEME: []}]
    # get_current_user_optional: a request with no token is also allowed ({}).
    optional = paths["/api/v1/properties"]["get"]
    assert optional["security"] == [{BEARER_SCHEME: []}, {}]
    # get_current_admin reaches get_current_user through get_current_active_user.
    assert paths["/api/v1/leads"]["get"]["security"] == [{BEARER_SCHEME: []}]
    assert "security" not in paths["/api/v1/amenities"]["get"]
    webhook = paths["/api/v1/webhooks/auth/password-changed"]["post"]
    assert webhook["security"] == [{WEBHOOK_SCHEME: []}]


def test_security_names_a_declared_scheme_and_the_header_parameter_is_gone(spec):
    declared = set(spec["components"]["securitySchemes"])
    secured = 0
    for path, method, operation in _operations(spec):
        for requirement in operation.get("security", []):
            assert set(requirement) <= declared, (method, path)
        if "security" in operation:
            secured += 1
        for parameter in operation.get("parameters", []):
            assert not (
                parameter["in"] == "header" and parameter["name"].lower() == "authorization"
            ), (method, path)
    assert secured > 100


def test_server_description_follows_the_url(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "PUBLIC_BASE_URL", None)
    assert openapi_servers() == [
        {"url": "https://api.360ghar.com", "description": "Production server"}
    ]
    monkeypatch.setattr(settings, "PUBLIC_BASE_URL", "https://api.360ghar.com/")
    assert openapi_servers()[0]["description"] == "Production server"
    monkeypatch.setattr(settings, "PUBLIC_BASE_URL", "http://localhost:3600")
    server = openapi_servers()[0]
    assert server["url"] == "http://localhost:3600"
    assert "Production" not in server["description"]


# --- Money bounds ----------------------------------------------------------------------------


def test_no_raw_bound_keys_in_the_document(spec):
    assert _raw_bound_keys(spec) == []


def test_money_bounds_use_the_standard_keywords(spec):
    schemas = spec["components"]["schemas"]
    assert schemas["LeaseCreate"]["properties"]["monthly_rent"]["exclusiveMinimum"] == 0
    assert schemas["LeaseCreate"]["properties"]["security_deposit"]["minimum"] == 0
    assert schemas["ExpenseCreate"]["properties"]["amount"]["exclusiveMinimum"] == 0
    optional = schemas["MaintenanceRequestCreate"]["properties"]["estimated_cost"]
    assert optional["anyOf"][0] == {"type": "number", "minimum": 0}
    base_price = schemas["ManagedPropertyCreate"]["properties"]["base_price"]
    assert (base_price["minimum"], base_price["maximum"]) == (0, 9999999999.99)


class _Priced(BaseModel):
    greater: Annotated[Money, Field(gt=0)]
    at_least: Annotated[Money | None, Field(ge=0)] = None
    between: Annotated[Money, Field(ge=0, le=100)] = 0
    below: Annotated[Money, Field(lt=5)] = 0
    ge: str = "a property that is named like a bound"


def test_normalize_numeric_bounds_renames_every_raw_key():
    schema = _Priced.model_json_schema()
    assert _raw_bound_keys(schema)  # pydantic writes the raw keys: the reason for the rename
    normalize_numeric_bounds(schema)
    properties = schema["properties"]
    assert _raw_bound_keys(schema) == []
    assert properties["greater"]["exclusiveMinimum"] == 0
    assert properties["at_least"]["anyOf"][0]["minimum"] == 0
    assert (properties["between"]["minimum"], properties["between"]["maximum"]) == (0, 100)
    assert properties["below"]["exclusiveMaximum"] == 5
    assert properties["ge"]["type"] == "string"  # a property called ge keeps its name
    assert "ge" in properties


def test_the_bounds_are_still_enforced_when_validating():
    with pytest.raises(ValueError):
        _Priced(greater=0)
    with pytest.raises(ValueError):
        _Priced(greater=1, between=101)
    assert _Priced(greater="1.005").greater == 1.01


def test_customize_openapi_is_idempotent(app):
    first = json.dumps(customize_openapi(app, app.openapi()), sort_keys=True)
    second = json.dumps(customize_openapi(app, app.openapi()), sort_keys=True)
    assert first == second


# --- UtcDateTime keeps "format": "date-time" -------------------------------------------------


class _Stamped(BaseModel):
    created_at: UtcDateTime
    removed_at: UtcDateTime | None = None
    seen: list[UtcDateTime] = []


@pytest.mark.parametrize("mode", ["validation", "serialization"])
def test_utc_datetime_schema_has_the_date_time_format(mode):
    properties = _Stamped.model_json_schema(mode=mode)["properties"]
    assert properties["created_at"] == {
        "format": "date-time",
        "title": "Created At",
        "type": "string",
    }
    assert {"format": "date-time", "type": "string"} in properties["removed_at"]["anyOf"]
    assert properties["seen"]["items"] == {"format": "date-time", "type": "string"}


def test_utc_datetime_output_still_ends_in_z():
    stamped = _Stamped(created_at=datetime(2026, 1, 2, 3, 4, 5))
    assert json.loads(stamped.model_dump_json())["created_at"] == "2026-01-02T03:04:05Z"


def _uses_utc_datetime(annotation: Any) -> bool:
    for arg in typing.get_args(annotation):
        if isinstance(arg, AfterValidator) and arg.func is schema_base._to_utc:
            return True
        if _uses_utc_datetime(arg):
            return True
    return False


def _models(namespace: Any):
    for value in vars(namespace).values():
        if isinstance(value, type) and issubclass(value, BaseModel):
            yield value


def test_every_utc_datetime_field_in_the_document_has_the_format(spec):
    import importlib
    import pkgutil

    import app.schemas as schemas_package

    components = spec["components"]["schemas"]
    checked = 0
    for module_info in pkgutil.iter_modules(schemas_package.__path__):
        module = importlib.import_module(f"app.schemas.{module_info.name}")
        for model in _models(module):
            component = components.get(model.__name__)
            if component is None or model.__module__ != module.__name__:
                continue
            for name, field in model.model_fields.items():
                if not _uses_utc_datetime(field.annotation) and not any(
                    isinstance(m, AfterValidator) and m.func is schema_base._to_utc
                    for m in field.metadata
                ):
                    continue
                prop = component.get("properties", {}).get(name)
                if prop is None:
                    continue
                branches = prop.get("anyOf", [prop])
                branches = [b.get("items", b) for b in branches]
                strings = [b for b in branches if b.get("type") == "string"]
                assert strings, (model.__name__, name, prop)
                assert all(b.get("format") == "date-time" for b in strings), (
                    model.__name__,
                    name,
                    prop,
                )
                checked += 1
    assert checked > 50
