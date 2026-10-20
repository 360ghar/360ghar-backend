"""OpenAPI document customization, so clients can generate exact types from it.

``install_openapi(app)`` post-processes the schema FastAPI builds:

- Every 422 uses ``ValidationErrorEnvelope``. ``HTTPValidationError`` and ``ValidationError``
  are removed.
- Every operation has a ``default`` response with ``ErrorEnvelope``. The OAuth routes can
  also return the RFC 6749 body, so their default is ``OAuthErrorResponse`` or ``ErrorEnvelope``.
- ``components.securitySchemes`` declares the bearer scheme, and each operation gets
  ``security`` from the auth dependency it uses (required or optional).
- Numeric bounds use the standard JSON schema keywords. Pydantic writes ``ge``, ``gt``,
  ``le`` and ``lt`` for a bound on a ``Money`` field, which no client understands.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from fastapi.dependencies.models import Dependant
from fastapi.routing import APIRoute
from pydantic.json_schema import models_json_schema

from app.api.api_v1.dependencies.auth import (
    get_current_cached_active_user,
    get_current_user,
    get_current_user_optional,
    get_current_user_short_session,
    get_current_user_sse,
)
from app.infrastructure.errors import (
    ErrorEnvelope,
    OAuthErrorResponse,
    ValidationErrorEnvelope,
    is_oauth_route,
)

HTTP_METHODS = ("get", "put", "post", "delete", "options", "head", "patch", "trace")

BEARER_SCHEME = "HTTPBearer"
WEBHOOK_SCHEME = "SupabaseWebhookSignature"
WEBHOOK_PATH_PREFIX = "/api/v1/webhooks/auth/"

# A dependency that reads the Authorization header and rejects a missing or bad token.
_REQUIRED_AUTH = frozenset(
    {
        get_current_user,
        get_current_cached_active_user,
        get_current_user_sse,
        get_current_user_short_session,
    }
)
# A dependency that returns None when there is no token.
_OPTIONAL_AUTH = frozenset({get_current_user_optional})

_SECURITY_SCHEMES: dict[str, dict[str, Any]] = {
    BEARER_SCHEME: {
        "type": "http",
        "scheme": "bearer",
        "bearerFormat": "JWT",
        "description": "Supabase access token. Send it as `Authorization: Bearer <token>`.",
    },
    WEBHOOK_SCHEME: {
        "type": "apiKey",
        "in": "header",
        "name": "X-Supabase-Signature",
        "description": (
            "HMAC-SHA256 of the raw request body with the webhook secret, as a hex digest "
            "(base64 when SUPABASE_WEBHOOK_SIGNATURE_ENCODING is base64)."
        ),
    },
}

# JSON schema keyword for each key pydantic writes for a bound on a wrapped number.
_BOUND_KEYWORDS = {
    "ge": "minimum",
    "le": "maximum",
    "gt": "exclusiveMinimum",
    "lt": "exclusiveMaximum",
}

# Schema keywords whose value is one schema, a list of schemas, or a name -> schema map.
_SCHEMA_VALUE_KEYS = ("items", "additionalProperties", "not", "if", "then", "else", "contains")
_SCHEMA_LIST_KEYS = ("anyOf", "allOf", "oneOf", "prefixItems")
_SCHEMA_MAP_KEYS = ("properties", "patternProperties", "$defs")

_REF_PREFIX = "#/components/schemas/"


def _ref(name: str) -> dict[str, str]:
    return {"$ref": f"{_REF_PREFIX}{name}"}


def normalize_numeric_bounds(schema: Any) -> None:
    """Rename pydantic's raw bound keys (``ge``, ``gt``, ``le``, ``lt``) in place.

    Walks schema objects only, so a property that is itself named ``ge`` is not touched.
    """
    if isinstance(schema, list):
        for item in schema:
            normalize_numeric_bounds(item)
        return
    if not isinstance(schema, dict):
        return
    for raw, keyword in _BOUND_KEYWORDS.items():
        if raw in schema:
            schema[keyword] = schema.pop(raw)
    for key in _SCHEMA_VALUE_KEYS:
        normalize_numeric_bounds(schema.get(key))
    for key in _SCHEMA_LIST_KEYS:
        normalize_numeric_bounds(schema.get(key))
    for key in _SCHEMA_MAP_KEYS:
        mapping = schema.get(key)
        if isinstance(mapping, dict):
            for value in mapping.values():
                normalize_numeric_bounds(value)


def _referenced_names(node: Any) -> set[str]:
    """Component schema names referenced anywhere under ``node``."""
    found: set[str] = set()
    if isinstance(node, dict):
        ref = node.get("$ref")
        if isinstance(ref, str) and ref.startswith(_REF_PREFIX):
            found.add(ref[len(_REF_PREFIX) :])
        for value in node.values():
            found |= _referenced_names(value)
    elif isinstance(node, list):
        for value in node:
            found |= _referenced_names(value)
    return found


def _add_error_components(schemas: dict[str, Any]) -> None:
    _, definitions = models_json_schema(
        [
            (model, "serialization")
            for model in (ErrorEnvelope, ValidationErrorEnvelope, OAuthErrorResponse)
        ],
        ref_template=f"{_REF_PREFIX}{{model}}",
    )
    schemas.update(definitions["$defs"])


def _error_schema(path: str) -> dict[str, Any]:
    if is_oauth_route(path):
        return {"anyOf": [_ref("OAuthErrorResponse"), _ref("ErrorEnvelope")]}
    return _ref("ErrorEnvelope")


def _json_content(schema: dict[str, Any]) -> dict[str, Any]:
    return {"application/json": {"schema": schema}}


def _query_strict(path: str) -> bool:
    """True when the router rejects unknown query keys (a 422), so the operation can return 422."""
    return (
        path.startswith("/api/v1/")
        and not path.startswith("/api/v1/webhooks/")
        and (not is_oauth_route(path))
    )


def _apply_error_responses(paths: dict[str, Any]) -> None:
    for path, item in paths.items():
        for method in HTTP_METHODS:
            operation = item.get(method)
            if not isinstance(operation, dict):
                continue
            responses = operation.setdefault("responses", {})
            if "422" in responses or _query_strict(path):
                responses["422"] = {
                    "description": "Validation Error",
                    "content": _json_content(_ref("ValidationErrorEnvelope")),
                }
            for status, response in responses.items():
                if status[:1] in ("4", "5") and "content" not in response:
                    response["content"] = _json_content(_error_schema(path))
            responses.setdefault(
                "default",
                {
                    "description": "Error. Every non-2xx response has this body.",
                    "content": _json_content(_error_schema(path)),
                },
            )


def _called_functions(dependant: Dependant) -> set[Any]:
    calls = {dependant.call}
    for sub in dependant.dependencies:
        calls |= _called_functions(sub)
    return calls


def _operation_security(route: APIRoute) -> list[dict[str, list[str]]] | None:
    if route.path_format.startswith(WEBHOOK_PATH_PREFIX):
        return [{WEBHOOK_SCHEME: []}]
    calls = _called_functions(route.dependant)
    if calls & _REQUIRED_AUTH:
        return [{BEARER_SCHEME: []}]
    if calls & _OPTIONAL_AUTH:
        # The empty requirement means a request with no token is also allowed.
        return [{BEARER_SCHEME: []}, {}]
    return None


def _drop_authorization_parameter(operation: dict[str, Any]) -> None:
    """The auth dependency reads the header, so FastAPI lists it as a parameter.

    ``security`` now describes it, and OpenAPI says to ignore a header parameter named
    Authorization, so the duplicate only adds an unused argument to generated clients.
    """
    parameters = [
        parameter
        for parameter in operation.get("parameters", [])
        if not (
            parameter.get("in") == "header" and parameter.get("name", "").lower() == "authorization"
        )
    ]
    if parameters:
        operation["parameters"] = parameters
    else:
        operation.pop("parameters", None)


def _apply_security(app: FastAPI, schema: dict[str, Any]) -> None:
    schema.setdefault("components", {})["securitySchemes"] = dict(_SECURITY_SCHEMES)
    paths = schema.get("paths", {})
    for route in app.routes:
        if not isinstance(route, APIRoute) or not route.include_in_schema:
            continue
        security = _operation_security(route)
        if security is None:
            continue
        for method in route.methods:
            operation = paths.get(route.path_format, {}).get(method.lower())
            if operation is not None:
                operation["security"] = security
                _drop_authorization_parameter(operation)


def _drop_unused_validation_schemas(schemas: dict[str, Any], paths: dict[str, Any]) -> None:
    """Remove FastAPI's validation schemas once nothing references them.

    HTTPValidationError comes first because it references ValidationError.
    """
    for name in ("HTTPValidationError", "ValidationError"):
        others = {key: value for key, value in schemas.items() if key != name}
        if name not in _referenced_names(paths) | _referenced_names(others):
            schemas.pop(name, None)


def customize_openapi(app: FastAPI, schema: dict[str, Any]) -> dict[str, Any]:
    """Apply every change to a schema FastAPI built. Idempotent."""
    components = schema.setdefault("components", {})
    schemas = components.setdefault("schemas", {})
    paths = schema.get("paths", {})
    _add_error_components(schemas)
    _apply_error_responses(paths)
    _apply_security(app, schema)
    _drop_unused_validation_schemas(schemas, paths)
    normalize_numeric_bounds(list(schemas.values()))
    components["schemas"] = {name: schemas[name] for name in sorted(schemas)}
    return schema


def install_openapi(app: FastAPI) -> None:
    """Make ``app.openapi()`` return the customized schema. Call once, after the routes exist."""
    build = app.openapi

    def openapi() -> dict[str, Any]:
        if app.openapi_schema is None:
            customize_openapi(app, build())
        return app.openapi_schema or {}

    app.openapi = openapi  # type: ignore[method-assign]
