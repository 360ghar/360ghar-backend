import traceback
import yaml
from contextlib import asynccontextmanager

from datetime import datetime
from fastapi import FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response

from app.core.exceptions import BaseAPIException
from app.core.config import settings
from app.api.api_v1.api import api_router
from app.core.supabase_client import get_supabase_client, get_supabase_admin_client
from app.core.logging import setup_logging, get_logger
from app.core.cache import cache_manager

# Configure logging
setup_logging()
logger = get_logger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager for startup and shutdown events"""
    # Startup
    try:
        # Initialize cache manager
        await cache_manager.connect()
        
        # Test Supabase connection with a simple query (use admin client to bypass RLS)
        supabase = get_supabase_admin_client()
        # Try to access any table to test connectivity
        try:
            supabase.table("properties").select("id", count="exact").limit(1).execute()
            logger.info("Supabase connection verified on startup")
        except Exception as db_e:
            logger.info(f"Database connection test: {db_e} (tables may not exist yet)")
    except Exception as e:
        logger.error(f"Supabase client creation failed: {e}")
    
    logger.info("API started", extra={
        "event": "startup",
        "env": settings.ENVIRONMENT,
        "version": "1.0.0",
    })
    
    yield
    
    # Shutdown
    await cache_manager.disconnect()
    logger.info("API shutdown", extra={"event": "shutdown"})

app = FastAPI(
    lifespan=lifespan,
    title="360Ghar Real Estate Platform",
    description="Tinder-like real estate platform backend APIs with Supabase integration",
    version="1.0.0",
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
        "version": "1.0.0",
        "docs": f"{settings.API_V1_STR}/docs",
        "status": "running"
    }

@app.get("/health")
async def health_check():
    """Health check endpoint with Supabase connectivity"""
    try:
        # Check Supabase connection
        db_status = "connected"
        try:
            # Use admin client here to avoid RLS/privilege issues in health checks
            supabase = get_supabase_admin_client()
            # Test with a simple query - try properties table first as it's most likely to exist
            try:
                result = supabase.table("properties").select("id", count="exact").limit(1).execute()
                db_status = "connected"
            except Exception as table_e:
                # If properties doesn't exist, the connection is still working
                if "does not exist" in str(table_e).lower():
                    db_status = "connected_no_tables"
                else:
                    raise table_e
        except Exception as db_e:
            logger.error(f"Supabase health check failed: {db_e}")
            db_status = "disconnected"
        
        overall_status = "healthy" if db_status == "connected" else "degraded"
        
        return {
            "status": overall_status,
            "database": db_status,
            "supabase_url": settings.SUPABASE_URL,
            "timestamp": datetime.utcnow().isoformat(),
            "version": "1.0.0"
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
        "supabase_url": settings.SUPABASE_URL,
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
    logger.error(f"Validation error: {exc}")
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
    logger.error(f"Unexpected error: {traceback.format_exc()}")
    
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

