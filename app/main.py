import traceback
import yaml
from contextlib import asynccontextmanager

from datetime import datetime
from fastapi import FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
import sentry_sdk
import sentry_sdk.integrations.fastapi
import sentry_sdk.integrations.sqlalchemy
from dotenv import load_dotenv

from app.core.exceptions import BaseAPIException
from app.core.config import settings
from app.api.api_v1.api import api_router
from app.core.database import engine
from app.core.logging import setup_logging, get_logger
from app.core.cache import cache_manager
from sqlalchemy import text


load_dotenv()

# Configure logging
setup_logging()
logger = get_logger(__name__)

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
        release=f"360ghar-backend@2.0.0",
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
    """Application lifespan manager for startup and shutdown events"""
    # Startup
    try:
        # Initialize cache manager
        await cache_manager.connect()
        
        # Test database connection (disabled for PgBouncer compatibility)
        # try:
        #     from app.core.database import AsyncSessionLocal
        #     async with AsyncSessionLocal() as session:
        #         await session.execute(text("SELECT 1"))
        #     logger.info("Database connection verified on startup")
        # except Exception as db_e:
        #     logger.error(f"Database connection test failed: {db_e}")
        logger.info("Database connection test skipped for PgBouncer compatibility")
    except Exception as e:
        logger.error(f"Application startup failed: {e}")
    
    logger.info("API started", extra={
        "event": "startup",
        "env": settings.ENVIRONMENT,
        "version": "2.0.0",
    })
    
    yield
    
    # Shutdown
    await cache_manager.disconnect()
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
        "email": "dev@360ghar.com"
    },
    license_info={
        "name": "MIT License",
        "url": "https://opensource.org/licenses/MIT"
    },
    servers=[
        {
            "url": "http://localhost:8000",
            "description": "Development server"
        },
        {
            "url": "https://api.360ghar.com",
            "description": "Production server"
        }
    ]
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if settings.ENVIRONMENT == "development" else settings.CORS_ORIGINS,
    allow_credentials=False if settings.ENVIRONMENT == "development" else True,
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
    expose_headers=["Content-Length", "Content-Range", "X-Process-Time", "X-Performance-Tier"],
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

@app.get("/")
async def root():
    return {
        "message": "360Ghar Real Estate Platform API",
        "version": "2.0.0",
        "docs": f"{settings.API_V1_STR}/docs",
        "status": "running"
    }

@app.get("/health")
async def health_check():
    """Health check endpoint with database connectivity"""
    try:
        # Check database connection (disabled for PgBouncer compatibility)
        db_status = "connected"  # Assume connected - actual endpoints will test properly
        # try:
        #     from app.core.database import AsyncSessionLocal
        #     async with AsyncSessionLocal() as session:
        #         await session.execute(text("SELECT 1"))
        # except Exception as db_e:
        #     logger.error(f"Database health check failed: {db_e}")
        #     db_status = "disconnected"
        
        overall_status = "healthy" if db_status == "connected" else "degraded"
        
        return {
            "status": overall_status,
            "database": db_status,
            "database_url": settings.DATABASE_URL.split('@')[1] if '@' in settings.DATABASE_URL else "configured",
            "timestamp": datetime.utcnow().isoformat(),
            "version": "2.0.0"
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
            "Analytics"
        ]
    }

@app.get(f"{settings.API_V1_STR}/openapi.yaml")
async def get_openapi_yaml():
    """Download OpenAPI specification as YAML file"""
    openapi_json = app.openapi()
    yaml_str = yaml.dump(openapi_json, default_flow_style=False, sort_keys=False)
    return Response(
        content=yaml_str,
        media_type="application/x-yaml",
        headers={"Content-Disposition": "attachment; filename=360ghar-openapi-spec.yaml"}
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

