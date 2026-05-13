"""Application factory for creating FastAPI app instances.

MCP Server Architecture:
- /mcp        -> User MCP server (owners, tenants, regular users)
- /mcp-admin  -> Admin MCP server (agents, administrators)

All servers share the same OAuth authentication infrastructure.
"""

from fastapi import FastAPI

from app.config import settings
from app.core.logging import get_logger
from app.infrastructure.errors import register_exception_handlers
from app.infrastructure.lifespan import create_lifespan
from app.infrastructure.mcp import build_mcp_http_apps
from app.infrastructure.middleware import register_middleware
from app.infrastructure.routing import register_routes

logger = get_logger(__name__)


def create_app(testing: bool = False) -> FastAPI:
    """Create and configure the FastAPI application."""
    logger.info("Creating FastAPI application", extra={"testing": testing})

    user_mcp_app, admin_mcp_app = build_mcp_http_apps()

    app = FastAPI(
        lifespan=create_lifespan(testing, user_mcp_app, admin_mcp_app),
        debug=(settings.ENVIRONMENT == "development"),
        redirect_slashes=False,
        title="360Ghar Real Estate Platform",
        description="Tinder-like real estate platform backend APIs with SQLAlchemy + Supabase Auth",
        version=settings.APP_VERSION,
        openapi_url=f"{settings.API_V1_STR}/openapi.json",
        docs_url=f"{settings.API_V1_STR}/docs",
        redoc_url=f"{settings.API_V1_STR}/redoc",
        contact={
            "name": "360Ghar Development Team",
            "email": "dev@360ghar.com",
        },
        license_info={
            "name": "MIT License",
            "url": "https://opensource.org/licenses/MIT",
        },
        servers=[
            {
                "url": settings.PUBLIC_BASE_URL or "https://api.360ghar.com",
                "description": "Production server",
            },
        ],
    )

    register_middleware(app, testing=testing)
    register_exception_handlers(app)
    register_routes(app, user_mcp_app=user_mcp_app, admin_mcp_app=admin_mcp_app)

    return app
