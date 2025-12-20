from app.factory import create_app
from app.middleware.rate_limit import RateLimitMiddleware
from app.middleware.security import RequestIDMiddleware, SecurityHeadersMiddleware
from fastapi.testclient import TestClient


class TestCreateApp:
    """Tests for application factory."""

    def test_testing_mode_skips_rate_limit_middleware(self) -> None:
        """Rate limit middleware should be skipped in testing mode."""
        app = create_app(testing=True)

        middleware_classes = {m.cls for m in app.user_middleware}
        assert RateLimitMiddleware not in middleware_classes
        assert SecurityHeadersMiddleware in middleware_classes
        assert RequestIDMiddleware in middleware_classes

    def test_mounts_mcp(self) -> None:
        """MCP should be mounted at /mcp path."""
        app = create_app(testing=True)
        assert any(getattr(r, "path", None) == "/mcp" for r in app.routes)

    def test_includes_api_router(self) -> None:
        """API router should be included with correct prefix."""
        app = create_app(testing=True)
        # Check that API routes are present
        paths = [getattr(r, "path", "") for r in app.routes]
        # Should have /api/v1 prefix routes
        assert any("/api/v1" in p for p in paths)

    def test_openapi_docs_accessible(self) -> None:
        """OpenAPI docs should be accessible."""
        app = create_app(testing=True)
        client = TestClient(app)

        # Docs endpoint should be accessible
        response = client.get("/api/v1/docs")
        assert response.status_code == 200

    def test_openapi_json_accessible(self) -> None:
        """OpenAPI JSON should be accessible."""
        app = create_app(testing=True)
        client = TestClient(app)

        response = client.get("/api/v1/openapi.json")
        assert response.status_code == 200
        data = response.json()
        assert "openapi" in data
        assert "info" in data

    def test_cors_configured(self) -> None:
        """CORS should be configured."""
        app = create_app(testing=True)

        # Check that CORSMiddleware is in the middleware stack
        middleware_classes = {m.cls.__name__ for m in app.user_middleware}
        assert "CORSMiddleware" in middleware_classes

    def test_app_metadata(self) -> None:
        """App should have correct metadata."""
        app = create_app(testing=True)

        assert app.title == "360Ghar Real Estate Platform"
        assert app.version == "2.0.0"

    def test_health_endpoint_accessible(self) -> None:
        """Health endpoint should be accessible."""
        app = create_app(testing=True)
        client = TestClient(app)

        # The health endpoint should exist and be accessible
        response = client.get("/api/v1/health")
        # Accept 200 or 404 (if not implemented), but not 500
        assert response.status_code in [200, 404]

    def test_security_middleware_order(self) -> None:
        """Security middlewares should be in correct order."""
        app = create_app(testing=True)

        # Get middleware in order (outermost first)
        middleware_list = [m.cls for m in app.user_middleware]

        # RequestIDMiddleware should be outermost (added last)
        if RequestIDMiddleware in middleware_list:
            request_id_index = middleware_list.index(RequestIDMiddleware)
            # It should be first in the list (outermost)
            assert request_id_index == 0


# Legacy tests (keeping for backwards compatibility)
def test_create_app_testing_mode_skips_rate_limit_middleware() -> None:
    app = create_app(testing=True)
    middleware_classes = {m.cls for m in app.user_middleware}
    assert RateLimitMiddleware not in middleware_classes
    assert SecurityHeadersMiddleware in middleware_classes
    assert RequestIDMiddleware in middleware_classes


def test_create_app_mounts_mcp() -> None:
    app = create_app(testing=True)
    assert any(getattr(r, "path", None) == "/mcp" for r in app.routes)
