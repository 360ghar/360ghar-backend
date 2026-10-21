"""Every /api/v1 JSON route declares a response model, unless it is listed in the allowlist.

Exempt: 204 responses, and streaming, file and redirect responses. Hidden routes
(include_in_schema=False) are not exempt. The allowlist (response_model_allowlist.txt)
lists the offenders that exist today, one "METHOD path" per line. Lines that start with
"#" are comments and hold the reason for the entry below them. A route that gains a
response model must leave the allowlist, or this test fails as stale.
"""

from __future__ import annotations

import typing
from functools import lru_cache
from pathlib import Path

from fastapi.responses import FileResponse, RedirectResponse, StreamingResponse
from fastapi.routing import APIRoute

from app.core.config import settings
from app.factory import create_app

ALLOWLIST = Path(__file__).with_name("response_model_allowlist.txt")
_STREAMING_TYPES = (StreamingResponse, FileResponse, RedirectResponse)


def _response_class(route: APIRoute) -> object:
    # FastAPI wraps the default class in a DefaultPlaceholder.
    return getattr(route.response_class, "value", route.response_class)


def _returns_raw_response(endpoint: object) -> bool:
    try:
        hint = typing.get_type_hints(endpoint).get("return")  # type: ignore[arg-type]
    except Exception:  # noqa: BLE001 - unresolved forward refs mean "no hint"
        return False
    return isinstance(hint, type) and issubclass(hint, _STREAMING_TYPES)


def _is_exempt(route: APIRoute) -> bool:
    if route.status_code == 204:
        return True
    response_class = _response_class(route)
    if isinstance(response_class, type) and issubclass(response_class, _STREAMING_TYPES):
        return True
    return _returns_raw_response(route.endpoint)


@lru_cache(maxsize=1)
def _api_routes() -> tuple[APIRoute, ...]:
    app = create_app(testing=True)
    return tuple(
        route
        for route in app.routes
        if isinstance(route, APIRoute) and route.path.startswith(settings.API_V1_STR)
    )


def offending_routes() -> list[str]:
    """Sorted "METHOD path" lines for /api/v1 routes that lack a response model."""
    lines = {
        f"{method} {route.path}"
        for route in _api_routes()
        if route.response_model is None and not _is_exempt(route)
        for method in route.methods
        if method not in {"HEAD", "OPTIONS"}
    }
    return sorted(lines)


def _allowlist() -> list[str]:
    lines = (line.strip() for line in ALLOWLIST.read_text().splitlines())
    return [line for line in lines if line and not line.startswith("#")]


def test_allowlist_is_sorted_and_unique():
    entries = _allowlist()
    assert entries == sorted(set(entries))


def test_every_api_route_has_a_response_model_or_is_allowlisted():
    unexpected = sorted(set(offending_routes()) - set(_allowlist()))
    assert not unexpected, (
        "These /api/v1 routes have no response_model. Add one, or add the line to "
        f"{ALLOWLIST.name} only as a temporary exception: {unexpected}"
    )


def test_allowlist_has_no_stale_entries():
    stale = sorted(set(_allowlist()) - set(offending_routes()))
    assert not stale, (
        f"Remove these from {ALLOWLIST.name}; they now declare a response model: {stale}"
    )


def test_hidden_route_is_not_exempt():
    async def endpoint():
        return {"ok": True}

    route = APIRoute("/api/v1/hidden-probe", endpoint, methods=["GET"], include_in_schema=False)
    assert not _is_exempt(route)
