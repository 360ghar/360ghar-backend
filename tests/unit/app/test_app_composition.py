from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.core.exceptions import BadRequestException
from app.factory import create_app

ROOT = Path(__file__).resolve().parents[3]


def test_openapi_paths_match_refactor_baseline():
    app = create_app(testing=True)
    current_paths = sorted(app.openapi().get("paths", {}).keys())
    baseline_paths = json.loads((ROOT / "tests/fixtures/openapi_path_baseline.json").read_text())

    assert current_paths == baseline_paths


def test_mcp_mount_paths_are_registered():
    app = create_app(testing=True)
    mounted_paths = {route.path for route in app.routes}

    assert "/mcp" in mounted_paths
    assert "/mcp-admin" in mounted_paths


def test_base_api_exception_envelope_is_preserved():
    app = create_app(testing=True)

    @app.get("/_characterization/bad-request")
    async def bad_request_route():
        raise BadRequestException("bad request")

    response = TestClient(app, raise_server_exceptions=False).get(
        "/_characterization/bad-request"
    )

    assert response.status_code == 400
    assert response.json() == {
        "error": {
            "code": "BAD_REQUEST",
            "message": "bad request",
        }
    }


def test_legacy_request_id_filter_import_remains_compatible():
    from app.core.logging import RequestIDFilter
    from app.infrastructure.request_context import RequestIDFilter as LegacyRequestIDFilter

    assert LegacyRequestIDFilter is RequestIDFilter


def test_canonical_domain_modules_expose_existing_property_service():
    from app.services.property import get_unified_properties_optimized

    assert callable(get_unified_properties_optimized)


def test_blog_router_is_not_mounted_under_duplicate_prefix():
    """Regression for duplicate blog router mounts.

    The blog router was previously mounted at both ``/blog`` and ``/blogs``.
    Only the canonical ``/blog`` (singular) prefix is allowed; the duplicate
    ``/blogs`` polluted the OpenAPI schema and shadowed routes.
    """
    app = create_app(testing=True)
    paths = {route.path for route in app.routes}

    blog_singular = {p for p in paths if p.startswith("/api/v1/blog/")}
    blog_plural = {p for p in paths if p.startswith("/api/v1/blogs/")}

    assert blog_singular, "Canonical /api/v1/blog/* routes must be registered"
    assert not blog_plural, (
        f"Blog router must NOT be mounted at /api/v1/blogs/*. Found: {sorted(blog_plural)}"
    )
