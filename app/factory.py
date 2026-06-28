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

# OpenAPI tag descriptions. Tag names mirror the `tags=[...]` arguments used
# in app/api/api_v1/api.py and app/infrastructure/routing.py so Swagger/Redoc
# can render a grouped, documented operation list.
OPENAPI_TAGS: list[dict[str, str]] = [
    {"name": "auth", "description": "Auth/onboarding support endpoints (Supabase mirrors)."},
    {"name": "users", "description": "User profile, preferences, privacy, and admin user management."},
    {"name": "properties", "description": "Property listings: create, search, recommend, update, delete."},
    {"name": "visits", "description": "Property visit scheduling, reschedule, cancel, and completion."},
    {"name": "bookings", "description": "Short-stay bookings: availability, pricing, payment, reviews."},
    {"name": "swipes", "description": "Tinder-style property swipes, history, and statistics."},
    {"name": "agents", "description": "Real-estate agent discovery, assignment, and workload stats."},
    {"name": "amenities", "description": "Property amenity catalog lookup."},
    {"name": "upload", "description": "File uploads, presigned URLs, and media library management."},
    {"name": "core", "description": "Bugs, pages, app versions, and FAQs (core platform support)."},
    {"name": "blog", "description": "Blog posts, categories, and tags with AI generation."},
    {"name": "flatmates", "description": "Flatmate discovery, swipes, matches, conversations, and moderation."},
    {"name": "flatmates-admin", "description": "Admin moderation of flatmate listings and reports."},
    {"name": "notifications", "description": "Push notification devices, sending, and marketing broadcasts."},
    {"name": "oauth", "description": "OAuth2 authorization, token, registration, and discovery endpoints."},
    {"name": "pm-dashboard", "description": "Property management dashboard overview and activity."},
    {"name": "pm-properties", "description": "Managed property CRUD for the PM app."},
    {"name": "pm-assignments", "description": "Owner-to-RM (relationship manager) assignments."},
    {"name": "pm-applications", "description": "Rental application forms and inbox, including decisions."},
    {"name": "pm-public", "description": "Public rental application form submission (no auth)."},
    {"name": "pm-tenants", "description": "Owner tenant listing and detail lookups."},
    {"name": "pm-leases", "description": "Lease lifecycle: create, sign, renew, terminate."},
    {"name": "pm-rent", "description": "Rent charge generation, payments, and tenant payment intents."},
    {"name": "pm-expenses", "description": "Property expense tracking and updates."},
    {"name": "pm-maintenance", "description": "Maintenance request submission and updates."},
    {"name": "pm-documents", "description": "Property document upload, metadata, and download."},
    {"name": "pm-inspections", "description": "Inspection checklists and signing."},
    {"name": "pm-reports", "description": "PM financial reports: rent roll, income, P&L, occupancy."},
    {"name": "design-studio", "description": "AI-powered design image generation."},
    {"name": "vastu", "description": "Vastu compliance analysis for floor plans (public)."},
    {"name": "tours", "description": "360 virtual tour CRUD, publish, duplicate, analytics."},
    {"name": "scenes", "description": "Tour scene CRUD and nested hotspot management."},
    {"name": "hotspots", "description": "Hotspot CRUD and position updates within scenes."},
    {"name": "floor-plans", "description": "Floor plan CRUD and marker management for tours."},
    {"name": "dashboard", "description": "Tour dashboard stats and realtime metrics."},
    {"name": "public-tours", "description": "Public (no-auth) tour viewing, events, and likes."},
    {"name": "ai", "description": "AI jobs for tour/scene analysis, generation, and optimization."},
    {"name": "custom-domains", "description": "Custom domain registration and verification for tours."},
    {"name": "ai-agent", "description": "Conversational AI agent chat, conversations, and widgets."},
    {"name": "data-hub", "description": "Real-estate data hub: RERA, auctions, circle rates, registry."},
    {"name": "websocket", "description": "Realtime WebSocket streams for job/user/tour updates."},
    {"name": "share", "description": "Public tour sharing endpoints."},
]


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
        openapi_tags=OPENAPI_TAGS,
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
