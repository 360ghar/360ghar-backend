"""
Application factory for creating FastAPI app instances.

MCP Server Architecture:
- /mcp        -> User MCP server (owners, tenants, regular users)
- /mcp-admin  -> Admin MCP server (agents, administrators)
- /sse        -> User MCP server (Streamable HTTP, ChatGPT Apps)

All servers share the same OAuth authentication infrastructure (Supabase JWT).
"""
import fastmcp
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from mcp.server.auth.middleware.auth_context import AuthContextMiddleware
from mcp.server.auth.middleware.bearer_auth import BearerAuthBackend
from starlette.routing import Mount, Router
from starlette.middleware import Middleware
from starlette.middleware.authentication import AuthenticationMiddleware

from app.api.api_v1.api import api_router
from app.api.api_v1.endpoints.oauth import oauth_wellknown_router, oauth_mcp_router
from app.core.cache import initialize_cache, shutdown_cache
from app.core.config import settings
from app.core.database import engine
from app.core.logging import get_logger
from app.middleware.rate_limit import RateLimitMiddleware
from app.middleware.security import RequestIDMiddleware, SecurityHeadersMiddleware, RequestLoggingMiddleware
from app.middleware.trailing_slash import StripTrailingSlashMiddleware
from functools import partial
from app.mcp.auth_provider import SupabaseTokenVerifier, configure_fastmcp_auth, get_public_base_url
from app.mcp.chatgpt import register_chatgpt_widgets
from app.mcp.user_server import user_mcp
from app.mcp.admin_server import admin_mcp

logger = get_logger(__name__)


def create_app(testing: bool = False) -> FastAPI:
    """Create and configure FastAPI application."""
    logger.info("Creating FastAPI application", extra={"testing": testing})
    configure_fastmcp_auth()

    # Register ChatGPT widgets for both user and admin MCP servers
    register_chatgpt_widgets(user_mcp)
    logger.debug("ChatGPT widgets registered", extra={"server": "user_mcp"})
    register_chatgpt_widgets(admin_mcp)
    logger.debug("ChatGPT widgets registered", extra={"server": "admin_mcp"})

    public_base_url = get_public_base_url()
    user_expected_resources = [
        f"{public_base_url}/mcp",
        f"{public_base_url}/sse",
    ]
    admin_expected_resources = [
        f"{public_base_url}/mcp-admin",
    ]

    def _optional_auth_middleware(expected_resources: list[str]) -> list[Middleware]:
        token_verifier = SupabaseTokenVerifier(
            required_scopes=["mcp:read", "mcp:write"],
            expected_resources=expected_resources,
        )
        return [
            Middleware(AuthenticationMiddleware, backend=BearerAuthBackend(token_verifier)),
            Middleware(AuthContextMiddleware),
        ]

    user_optional_auth_middleware = _optional_auth_middleware(user_expected_resources)
    admin_optional_auth_middleware = _optional_auth_middleware(admin_expected_resources)

    # Add request logging to MCP middleware stacks
    user_mcp_middleware = [
        Middleware(RequestLoggingMiddleware, prefix="/mcp"),
        *user_optional_auth_middleware,
    ]
    admin_mcp_middleware = [
        Middleware(RequestLoggingMiddleware, prefix="/mcp-admin"),
        *admin_optional_auth_middleware,
    ]
    sse_mcp_middleware = [
        Middleware(RequestLoggingMiddleware, prefix="/sse"),
        *user_optional_auth_middleware,
    ]

    # Create MCP http apps with path="/" - they serve at root of mount point
    user_mcp_app = user_mcp.http_app(
        path="/",
        transport="http",
        json_response=False,
        stateless_http=True,
        middleware=user_mcp_middleware,
    )
    logger.debug("User MCP HTTP app created")

    admin_mcp_app = admin_mcp.http_app(
        path="/",
        transport="http",
        json_response=False,
        stateless_http=True,
        middleware=admin_mcp_middleware,
    )
    logger.debug("Admin MCP HTTP app created")

    user_mcp_sse_app = user_mcp.http_app(
        path="/",
        transport="http",
        json_response=False,
        stateless_http=True,
        middleware=sse_mcp_middleware,
    )
    logger.debug("User MCP SSE app created")

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        """Application lifespan manager for startup and shutdown events."""
        async with user_mcp_app.lifespan(app):
            async with admin_mcp_app.lifespan(app):
                async with user_mcp_sse_app.lifespan(app):
                    try:
                        if not testing:
                            try:
                                await initialize_cache()
                            except Exception as cache_e:
                                logger.warning("Cache connection skipped/failed: %s", cache_e)

                        if not testing:
                            try:
                                from app.services.notification_scheduler import (
                                    start_notification_scheduler,
                                )
                                start_notification_scheduler(app)
                            except Exception as sched_e:
                                logger.error("Failed to start notification scheduler: %s", sched_e)

                        if not testing:
                            try:
                                from app.services.vector_sync_scheduler import (
                                    start_vector_sync_scheduler,
                                )
                                start_vector_sync_scheduler(app)
                            except Exception as sched_vec_e:
                                logger.error("Failed to start vector sync scheduler: %s", sched_vec_e)
                    except Exception as exc:
                        logger.error("Application startup failed: %s", exc)

                    logger.info(
                        "API started",
                        extra={
                            "event": "startup",
                            "env": settings.ENVIRONMENT,
                            "version": "2.0.0",
                            "mcp_servers": ["/mcp", "/mcp-admin", "/sse"],
                        },
                    )

                    yield

                    if not testing:
                        try:
                            await shutdown_cache()
                        except Exception as cache_e:
                            logger.warning("Cache disconnect skipped/failed: %s", cache_e)
                    await engine.dispose()
                    logger.info("API shutdown", extra={"event": "shutdown"})

    app = FastAPI(
        lifespan=lifespan,
        debug=(settings.ENVIRONMENT == "development"),
        title="360Ghar Real Estate Platform",
        description="Tinder-like real estate platform backend APIs with SQLAlchemy + Supabase Auth",
        version="2.0.0",
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
                "url": "http://localhost:8000",
                "description": "Development server",
            },
            {
                "url": "https://api.360ghar.com",
                "description": "Production server",
            },
        ],
    )

    if settings.ENVIRONMENT == "development" or testing:
        cors_origins = ["*"]
        cors_credentials = False
    else:
        cors_origins = settings.CORS_ORIGINS
        cors_credentials = True

    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=cors_credentials,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"],
        allow_headers=[
            "Accept",
            "Accept-Language",
            "Content-Language",
            "Content-Type",
            "Authorization",
            "X-Requested-With",
            "X-CSRF-Token",
            "X-API-Key",
            "Cache-Control",
            "Pragma",
            "Expires",
            "X-Process-Time",
            "X-Performance-Tier",
        ],
        expose_headers=[
            "Content-Length",
            "Content-Range",
            "X-Process-Time",
            "X-Performance-Tier",
        ],
        max_age=86400,
    )

    if not testing:
        app.add_middleware(
            RateLimitMiddleware,
            calls=100,
            period=60,
            scope="global",
        )

    app.add_middleware(SecurityHeadersMiddleware)

    app.add_middleware(StripTrailingSlashMiddleware)

    app.add_middleware(RequestIDMiddleware)

    # Add request logging for non-MCP routes (MCP routes have their own logging)
    app.add_middleware(RequestLoggingMiddleware, prefix="")

    @app.exception_handler(401)
    async def mcp_unauthorized_handler(request, exc):
        """Add WWW-Authenticate header for MCP 401 responses."""
        from fastapi.responses import JSONResponse

        path = str(request.url.path)
        if path.startswith("/mcp") or path.startswith("/sse"):
            base_url = settings.PUBLIC_BASE_URL or str(request.base_url).rstrip("/")
            if path.startswith("/mcp-admin"):
                resource_metadata = f"{base_url}/.well-known/oauth-protected-resource/mcp-admin"
            elif path.startswith("/sse"):
                resource_metadata = f"{base_url}/.well-known/oauth-protected-resource/sse"
            else:
                resource_metadata = f"{base_url}/.well-known/oauth-protected-resource/mcp"
            headers = {
                "WWW-Authenticate": (
                    f'Bearer resource_metadata="{resource_metadata}", '
                    'scope="mcp:read mcp:write"'
                )
            }
            return JSONResponse(
                status_code=401,
                content={"error": "unauthorized", "error_description": "Authentication required"},
                headers=headers,
            )
        return JSONResponse(
            status_code=401,
            content={"detail": str(exc.detail) if hasattr(exc, "detail") else "Unauthorized"},
        )

    @app.exception_handler(403)
    async def mcp_forbidden_handler(request, exc):
        """Add WWW-Authenticate header for MCP 403 responses."""
        from fastapi.responses import JSONResponse

        path = str(request.url.path)
        if path.startswith("/mcp") or path.startswith("/sse"):
            headers = {
                "WWW-Authenticate": (
                    'Bearer error="insufficient_scope", scope="mcp:read mcp:write"'
                )
            }
            return JSONResponse(
                status_code=403,
                content={"error": "forbidden", "error_description": "Insufficient scope"},
                headers=headers,
            )
        return JSONResponse(
            status_code=403,
            content={"detail": str(exc.detail) if hasattr(exc, "detail") else "Forbidden"},
        )

    app.include_router(api_router, prefix=settings.API_V1_STR)

    app.include_router(oauth_wellknown_router)
    app.include_router(oauth_mcp_router)

    # Mount MCP apps at their respective paths
    app.mount("/mcp", user_mcp_app)
    app.mount("/mcp-admin", admin_mcp_app)
    app.mount("/sse", user_mcp_sse_app)
    logger.info("MCP servers mounted", extra={"paths": ["/mcp", "/mcp-admin", "/sse"]})

    return app
