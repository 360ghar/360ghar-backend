"""BE-tours residual pass (r2-route-matrix-27, r2-notify-realtime-10): no WebSocket route reads a token from the query string.

The token is sent in the first frame after accept (see app/api/api_v1/endpoints/websocket.py).
A route that declares a token query parameter would put the JWT in server and proxy logs.
"""

from __future__ import annotations

import inspect
from pathlib import Path

from fastapi.routing import APIWebSocketRoute

import app as app_package
from app.factory import create_app

REQUIRED_WEBSOCKET_PATHS = {"/ws/jobs/{job_id}", "/ws/user"}


def _websocket_routes():
    return [
        route for route in create_app(testing=True).routes if isinstance(route, APIWebSocketRoute)
    ]


def test_the_checked_websocket_routes_are_registered():
    # The rules below run on every registered WebSocket route. This guard fails
    # if the check would otherwise pass on an empty set.
    paths = {route.path for route in _websocket_routes()}

    assert REQUIRED_WEBSOCKET_PATHS <= paths


def test_no_websocket_route_declares_a_token_query_parameter():
    for route in _websocket_routes():
        query_names = {param.name for param in route.dependant.query_params}
        assert "token" not in query_names, route.path


def test_no_websocket_endpoint_takes_a_token_argument():
    for route in _websocket_routes():
        assert "token" not in inspect.signature(route.endpoint).parameters, route.path


APP_ROOT = Path(app_package.__file__).parent
QUERY_STRING_READS = ("query_params", "query_string", 'scope["query_string"]')


def _websocket_source_files() -> list[Path]:
    # Any app module that defines or handles a WebSocket. A module that reads the query
    # string on a socket path is caught here even when no route declares the parameter.
    files = []
    for path in sorted(APP_ROOT.rglob("*.py")):
        source = path.read_text(encoding="utf-8")
        if "WebSocket" in source or "router.websocket(" in source:
            files.append(path)
    return files


def _reads_query_string(source: str) -> bool:
    return any(marker in source for marker in QUERY_STRING_READS)


def test_the_websocket_source_scan_finds_the_socket_modules():
    # Guard: the scan must not pass on an empty set.
    names = {path.name for path in _websocket_source_files()}

    assert {"websocket.py"} <= names


def test_no_websocket_module_reads_the_query_string():
    offenders = [
        str(path.relative_to(APP_ROOT))
        for path in _websocket_source_files()
        if _reads_query_string(path.read_text(encoding="utf-8"))
    ]

    assert offenders == []


def test_the_query_string_scan_flags_a_direct_read():
    # Self-check of the scan: a socket body that reads the query string is flagged.
    body = 'token = websocket.query_params.get("token")'

    assert _reads_query_string(body)
    assert not _reads_query_string('data = await websocket.receive_json()\ntoken = data["token"]')
