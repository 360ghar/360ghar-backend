"""Reject query keys that the matched route does not declare (they give 422)."""

from __future__ import annotations

from fastapi import Request
from fastapi.dependencies.models import Dependant
from fastapi.dependencies.utils import get_cached_model_fields
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from pydantic import BaseModel

# Accepted on every route, declared or not, so generic list clients can send them.
GLOBAL_QUERY_KEYS = frozenset({"cursor", "limit", "include_total"})

# Routes with their own query handling, or that are called from outside the API.
_EXCLUDED_MODULE_PARTS = frozenset({"oauth", "webhooks"})


def declared_query_names(dependant: Dependant) -> set[str]:
    """Collect query parameter names from a route's dependant and every sub-dependant."""
    fields = dependant.query_params
    model = fields[0].field_info.annotation if len(fields) == 1 else None
    # A lone query model (Annotated[Model, Query()]) takes its keys from the model's fields,
    # the same rule FastAPI uses when it reads the request.
    if isinstance(model, type) and issubclass(model, BaseModel):
        names = {field.alias for field in get_cached_model_fields(model)}
    else:
        names = {field.alias for field in fields}
    for sub in dependant.dependencies:
        names |= declared_query_names(sub)
    return names


def _is_excluded(route: APIRoute) -> bool:
    module_parts = set(getattr(route.endpoint, "__module__", "").split("."))
    path = route.path
    return bool(module_parts & _EXCLUDED_MODULE_PARTS) or path.startswith("/mcp")


async def reject_unknown_query_params(request: Request) -> None:
    """Router dependency for /api/v1. Unknown query keys raise a 422 with ``query.<name>`` fields."""
    route = request.scope.get("route")
    if not isinstance(route, APIRoute) or _is_excluded(route):
        return
    allowed = declared_query_names(route.dependant) | GLOBAL_QUERY_KEYS
    unknown = [key for key in request.query_params.keys() if key not in allowed]
    if unknown:
        raise RequestValidationError(
            [
                {
                    "type": "extra_forbidden",
                    "loc": ("query", key),
                    "msg": "unknown parameter",
                    "input": None,
                }
                for key in unknown
            ]
        )
