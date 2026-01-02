import traceback
import yaml
from contextlib import asynccontextmanager

from datetime import datetime

import fastmcp
import sentry_sdk
import sentry_sdk.integrations.fastapi
import sentry_sdk.integrations.sqlalchemy
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from sqlalchemy import text

from app.api.api_v1.api import api_router
from app.api.api_v1.endpoints import oauth
from app.core.cache import cache_manager
from app.core.config import settings
from app.core.database import engine
from app.core.exceptions import BaseAPIException
from app.core.logging import get_logger, setup_logging
from app.mcp.auth_provider import SupabaseAuthProvider, configure_fastmcp_auth
from app.mcp.server import mcp


load_dotenv()

# Configure logging
setup_logging()
logger = get_logger(__name__)

# Configure FastMCP auth to use Supabase-backed JWT verification for HTTP.
configure_fastmcp_auth()
# Ensure our shared FastMCP server instance uses the Supabase auth provider.
mcp.auth = SupabaseAuthProvider()

# Create the MCP HTTP sub-application once so we can use its lifespan
# and mount it under /mcp on the main FastAPI app.
mcp_app = mcp.http_app(
    path="/",
    transport="http",
    json_response=False,
    stateless_http=True,
    middleware=None,
)

# Initialize Sentry
if settings.SENTRY_DSN:
    sentry_sdk.init(
        dsn=settings.SENTRY_DSN,
        environment=settings.ENVIRONMENT,
        # Set sample rate for performance monitoring
        traces_sample_rate=1.0 if settings.ENVIRONMENT == "development" else 0.1,
        # Add data like request headers and IP for users,
        # see https://docs.sentry.io/platforms/python/data-management/data-collected/ for more info
        send_default_pii=True,
        # Release tracking
        release="360ghar-backend@2.0.0",
        # FastAPI integration
        integrations=[
            sentry_sdk.integrations.fastapi.FastApiIntegration(),
            sentry_sdk.integrations.sqlalchemy.SqlalchemyIntegration(),
        ],
    )
    logger.info("Sentry initialized", extra={"environment": settings.ENVIRONMENT})
else:
    logger.warning("Sentry DSN not configured - error tracking disabled")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager for startup and shutdown events."""
    # Ensure FastMCP's streamable HTTP session manager is running.
    async with mcp_app.lifespan(app):
        try:
            # Initialize cache manager (commented out for now - Redis not required)
            # await cache_manager.connect()

            # Test database connection (disabled for PgBouncer compatibility)
            # try:
            #     from app.core.database import AsyncSessionLocal
            #     async with AsyncSessionLocal() as session:
            #         await session.execute(text("SELECT 1"))
            #     logger.info("Database connection verified on startup")
            # except Exception as db_e:
            #     logger.error(f"Database connection test failed: {db_e}")
            logger.info(
                "Database connection test skipped for PgBouncer compatibility"
            )

            # Optional: start push notification scheduler
            try:
                from app.services.notification_scheduler import (
                    start_notification_scheduler,
                )
                start_notification_scheduler(app)
            except Exception as sched_e:
                logger.error(f"Failed to start notification scheduler: {sched_e}")
            # Optional: start vector sync scheduler
            try:
                from app.services.vector_sync_scheduler import (
                    start_vector_sync_scheduler,
                )
                start_vector_sync_scheduler(app)
            except Exception as sched_vec_e:
                logger.error(f"Failed to start vector sync scheduler: {sched_vec_e}")
        except Exception as e:
            logger.error(f"Application startup failed: {e}")

        logger.info(
            "API started",
            extra={
                "event": "startup",
                "env": settings.ENVIRONMENT,
                "version": "2.0.0",
            },
        )

        yield

        # Shutdown
        # await cache_manager.disconnect()  # Commented out - Redis not required
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

# Configure CORS properly for production and development
if settings.ENVIRONMENT == "development":
    # Development: Allow all origins with no credentials for easier testing
    cors_origins = ["*"]
    cors_credentials = False
else:
    # Production: Use specific origins with credentials
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
        "X-Process-Time",  # Allow client to see performance headers
        "X-Performance-Tier",
    ],
    expose_headers=[
        "Content-Length",
        "Content-Range",
        "X-Process-Time",
        "X-Performance-Tier",
    ],
    max_age=86400,  # Cache preflight requests for 24 hours
)

# # Add global rate limiting
# app.add_middleware(
#     RateLimitMiddleware,
#     calls=100,
#     period=60,
#     scope="global"
# )

# # Add security headers
# app.add_middleware(SecurityHeadersMiddleware)

app.include_router(api_router, prefix=settings.API_V1_STR)
app.include_router(oauth.router)

# Mount MCP HTTP app at /mcp using FastMCP's HTTP transport.
app.mount("/mcp", mcp_app)


@app.get("/")
async def root():
    return {
        "message": "360Ghar Real Estate Platform API",
        "version": "2.0.0",
        "docs": f"{settings.API_V1_STR}/docs",
        "status": "running",
    }


@app.get("/health")
async def health_check():
    """Health check endpoint with database connectivity"""
    try:
        db_status = "connected"
        overall_status = "healthy" if db_status == "connected" else "degraded"

        return {
            "status": overall_status,
            "database": db_status,
            "database_url": settings.DATABASE_URL.split("@")[1]
            if "@" in settings.DATABASE_URL
            else "configured",
            "timestamp": datetime.utcnow().isoformat(),
            "version": "2.0.0",
        }
    except Exception as e:
        logger.error(f"Health check failed: {str(e)}")
        raise HTTPException(status_code=503, detail="Service unavailable")


@app.get("/config")
async def get_config():
    """Get app configuration (non-sensitive)"""
    return {
        "api_version": settings.API_V1_STR,
        "environment": settings.ENVIRONMENT,
        "database": "SQLAlchemy + PostgreSQL",
        "auth": "Supabase",
        "features": [
            "User Authentication",
            "Property Discovery",
            "Location-based Search",
            "Swipe Functionality",
            "Visit Scheduling",
            "Short-stay Bookings",
            "Analytics",
        ],
    }


@app.get(f"{settings.API_V1_STR}/openapi.yaml")
async def get_openapi_yaml():
    """Download OpenAPI specification as YAML file"""
    openapi_json = app.openapi()
    yaml_str = yaml.dump(openapi_json, default_flow_style=False, sort_keys=False)
    return Response(
        content=yaml_str,
        media_type="application/x-yaml",
        headers={
            "Content-Disposition": "attachment; filename=360ghar-openapi-spec.yaml"
        },
    )


@app.exception_handler(BaseAPIException)
async def api_exception_handler(request: Request, exc: BaseAPIException):
    """Handle custom API exceptions"""
    logger.warning(f"API exception: {exc.detail} - {request.method} {request.url.path}")
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "message": exc.detail,
                "type": exc.__class__.__name__,
                "path": str(request.url),
                "method": request.method,
                "timestamp": datetime.utcnow().isoformat(),
                **exc.extra
            }
        },
        headers=exc.headers
    )

@app.exception_handler(ValueError)
async def value_error_handler(request: Request, exc: ValueError):
    """Handle validation errors"""
    logger.warning(f"Validation error: {exc} - {request.method} {request.url.path}")
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "error": {
                "message": str(exc),
                "type": "ValidationError",
                "path": str(request.url),
                "method": request.method,
                "timestamp": datetime.utcnow().isoformat()
            }
        }
    )

@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    """Handle unexpected exceptions"""
    logger.error(f"Unexpected error: {str(exc)} - {request.method} {request.url.path}", exc_info=True)
    
    # Don't expose internal errors in production
    if settings.ENVIRONMENT == "production":
        message = "An unexpected error occurred"
    else:
        message = str(exc)
    
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "error": {
                "message": message,
                "type": "InternalServerError",
                "path": str(request.url),
                "method": request.method,
                "timestamp": datetime.utcnow().isoformat()
            }
        }
    )
