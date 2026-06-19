from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import RedirectResponse

from app.api.api_v1.endpoints import (
    # AI Agent
    agent_chat,
    agents,
    ai,
    amenities,
    auth,
    blog,
    bookings,
    core,
    custom_domains,
    dashboard,
    # Data Hub
    data_hub,
    design_studio,
    flatmates,
    flatmates_admin,
    floor_plans,
    hotspots,
    notifications,
    oauth,
    payments,
    pm_applications,
    pm_assignments,
    pm_dashboard,
    pm_documents,
    pm_expenses,
    pm_inspections,
    pm_leases,
    pm_maintenance,
    pm_properties,
    pm_rent,
    pm_reports,
    pm_tenants,
    properties,
    public,
    scenes,
    swipes,
    # 360 Virtual Tours
    tours,
    upload,
    users,
    vastu,
    visits,
    webhooks,
)

api_router = APIRouter()


@api_router.get("/health", include_in_schema=False)
async def api_v1_health_redirect():
    """Redirect /api/v1/health to the root /health endpoint."""
    return RedirectResponse(url="/health", status_code=307)


api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(users.router, prefix="/users", tags=["users"])
api_router.include_router(properties.router, prefix="/properties", tags=["properties"])
api_router.include_router(visits.router, prefix="/visits", tags=["visits"])
api_router.include_router(bookings.router, prefix="/bookings", tags=["bookings"])
api_router.include_router(swipes.router, prefix="/swipes", tags=["swipes"])
api_router.include_router(payments.router, prefix="/payments", tags=["payments"])
api_router.include_router(agents.router, prefix="/agents", tags=["agents"])
api_router.include_router(amenities.router, prefix="/amenities", tags=["amenities"])
api_router.include_router(upload.router, prefix="/upload", tags=["upload"])
api_router.include_router(core.router, prefix="", tags=["core"])
api_router.include_router(blog.router, prefix="/blog", tags=["blog"])
api_router.include_router(flatmates.router, prefix="/flatmates", tags=["flatmates"])
api_router.include_router(flatmates_admin.router, prefix="/flatmates", tags=["flatmates-admin"])
api_router.include_router(notifications.router, prefix="/notifications", tags=["notifications"])
# OAuth endpoints are mounted at the root level for MCP compatibility
api_router.include_router(oauth.router, tags=["oauth"])

# Property Management (PM) - new surface area for the PM mobile app
api_router.include_router(pm_dashboard.router, prefix="/pm/dashboard", tags=["pm-dashboard"])
api_router.include_router(pm_properties.router, prefix="/pm/properties", tags=["pm-properties"])
api_router.include_router(pm_assignments.router, prefix="/pm/assignments", tags=["pm-assignments"])
api_router.include_router(pm_applications.router, prefix="/pm/applications", tags=["pm-applications"])
api_router.include_router(pm_applications.public_router, prefix="/pm/public", tags=["pm-public"])
api_router.include_router(pm_tenants.router, prefix="/pm/tenants", tags=["pm-tenants"])
api_router.include_router(pm_leases.router, prefix="/pm/leases", tags=["pm-leases"])
api_router.include_router(pm_rent.router, prefix="/pm/rent", tags=["pm-rent"])
api_router.include_router(pm_expenses.router, prefix="/pm/expenses", tags=["pm-expenses"])
api_router.include_router(pm_maintenance.router, prefix="/pm/maintenance", tags=["pm-maintenance"])
api_router.include_router(pm_documents.router, prefix="/pm/documents", tags=["pm-documents"])
api_router.include_router(pm_inspections.router, prefix="/pm/inspections", tags=["pm-inspections"])
api_router.include_router(pm_reports.router, prefix="/pm/reports", tags=["pm-reports"])

# AI Design Studio - image generation (auth required)
api_router.include_router(design_studio.router, prefix="/design-studio", tags=["design-studio"])

# Vastu Checker - public endpoint (no auth required)
api_router.include_router(vastu.router, prefix="/vastu", tags=["vastu"])

# 360 Virtual Tours
api_router.include_router(tours.router, prefix="/tours", tags=["tours"])
api_router.include_router(scenes.router, prefix="/scenes", tags=["scenes"])
api_router.include_router(hotspots.router, prefix="/hotspots", tags=["hotspots"])
api_router.include_router(floor_plans.router, tags=["floor-plans"])
api_router.include_router(dashboard.router, prefix="/dashboard", tags=["dashboard"])

# 360 Virtual Tours - Public endpoints (no auth required)
api_router.include_router(public.router, prefix="/public", tags=["public-tours"])

# 360 Virtual Tours - AI endpoints
api_router.include_router(ai.router, prefix="/ai", tags=["ai"])

# 360 Virtual Tours - Custom Domains
api_router.include_router(custom_domains.router, prefix="/custom-domains", tags=["custom-domains"])

# AI Agent
api_router.include_router(agent_chat.router, prefix="/agent", tags=["ai-agent"])

# Data Hub
api_router.include_router(data_hub.router, prefix="/data-hub", tags=["data-hub"])

# Webhooks (inbound integrations). The router already carries the
# /webhooks/auth prefix, so the full path is /api/v1/webhooks/auth/...
api_router.include_router(webhooks.router)
