from __future__ import annotations

from app.middleware.trailing_slash import MCP_MOUNT_PATHS, StripTrailingSlashMiddleware


async def _run_with_path(path: str) -> str:
    captured_path = {"value": ""}

    async def app(scope, receive, send):
        captured_path["value"] = scope["path"]

    middleware = StripTrailingSlashMiddleware(app)
    scope = {
        "type": "http",
        "path": path,
    }

    async def _receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def _send(_message):
        return None

    await middleware(scope, _receive, _send)
    return captured_path["value"]


def test_mcp_mount_paths_do_not_include_sse():
    assert "/sse" not in MCP_MOUNT_PATHS
    assert MCP_MOUNT_PATHS == {"/mcp", "/mcp-admin"}


async def test_adds_trailing_slash_for_mcp_mounts():
    assert await _run_with_path("/mcp") == "/mcp/"
    assert await _run_with_path("/mcp-admin") == "/mcp-admin/"


async def test_strips_trailing_slash_for_api_routes():
    assert await _run_with_path("/api/v1/properties/") == "/api/v1/properties"
    assert await _run_with_path("/api/") == "/api/"
