from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
import logging
import yaml
from app.core.config import settings
from app.api.api_v1.api import api_router

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
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
    ],
    expose_headers=["Content-Length", "Content-Range"],
    max_age=86400,  # Cache preflight requests for 24 hours
)

@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    logger.error(f"Global exception: {str(exc)}")
    return JSONResponse(
        status_code=500,
        content={"message": "Internal server error", "detail": str(exc)}
    )

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
    """Health check endpoint"""
    try:
        return {
            "status": "healthy",
            "database": "connected",
            "supabase_url": settings.SUPABASE_URL,
            "timestamp": "2024-12-29"
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