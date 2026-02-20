"""
ChatGPT App Module for 360Ghar.

This module provides ChatGPT-specific MCP tools and widget registration for
the 360Ghar real estate platform's ChatGPT App integration.

Tools:
- Discovery tools: Property search, details, feed, swipe, shortlist
- Visit tools: Schedule, list, get, cancel visits

Widgets:
- PropertySearchWidget, PropertyDetailsWidget, PropertySwipeWidget
- VisitSchedulerWidget, VisitListWidget
- LeaseDetailsWidget, MaintenanceWidget, OwnerDashboardWidget
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional, Dict, Any

from fastmcp import FastMCP

from app.core.logging import get_logger
from app.core.config import settings

logger = get_logger(__name__)

# Widget directory (where built HTML bundles are stored)
# Located at project_root/chatgpt-widgets/dist/
WIDGET_DIR = Path(__file__).parent.parent.parent.parent / "chatgpt-widgets" / "dist"

# Widget to tool mapping with metadata
WIDGETS: Dict[str, Dict[str, Any]] = {
    "PropertySearchWidget": {
        "tools": ["discovery_search"],
        "title": "Property Search Results",
        "description": "Grid view of property search results with filtering",
    },
    "PropertyDetailsWidget": {
        "tools": ["discovery_property_get"],
        "title": "Property Details",
        "description": "Full property details with images and amenities",
    },
    "PropertySwipeWidget": {
        "tools": ["discovery_feed"],
        "title": "Property Discovery",
        "description": "Swipe-based property discovery interface",
    },
    "VisitSchedulerWidget": {
        "tools": ["visits_schedule"],
        "title": "Schedule Visit",
        "description": "Schedule a property visit with date/time selection",
    },
    "VisitListWidget": {
        "tools": ["visits_list"],
        "title": "My Visits",
        "description": "List of scheduled property visits",
    },
    "LeaseDetailsWidget": {
        "tools": ["tenant_lease_current"],
        "title": "Lease Details",
        "description": "Current lease information for tenants",
    },
    "MaintenanceWidget": {
        "tools": ["tenant_maintenance_list", "tenant_maintenance_create"],
        "title": "Maintenance Requests",
        "description": "Submit and track maintenance requests",
    },
    "OwnerDashboardWidget": {
        "tools": ["owner_properties_list", "owner_dashboard_overview"],
        "title": "Owner Dashboard",
        "description": "Property owner dashboard with stats and listings",
    },
    # Property Management Widgets
    "LeaseManagementWidget": {
        "tools": ["owner_leases_list", "owner_leases_get"],
        "title": "Lease Management",
        "description": "View and manage property leases",
    },
    "RentCollectionWidget": {
        "tools": ["owner_rent_status", "owner_rent_record_payment", "owner_rent_history"],
        "title": "Rent Collection",
        "description": "Track rent payments and record transactions",
    },
    "TenantRentWidget": {
        "tools": ["tenant_rent_dues", "tenant_rent_history"],
        "title": "My Rent",
        "description": "View rent dues and payment history",
    },
}


def load_widget_html(widget_name: str) -> Optional[str]:
    """Load widget HTML bundle from disk."""
    widget_path = WIDGET_DIR / f"{widget_name}.html"
    if widget_path.exists():
        return widget_path.read_text()
    return None


def get_widget_for_tool(tool_name: str) -> Optional[str]:
    """Get the widget URI for a tool."""
    for widget_name, config in WIDGETS.items():
        if tool_name in config["tools"]:
            return f"ui://widget/{widget_name.lower()}.html"
    return None


def register_chatgpt_widgets(mcp: FastMCP) -> None:
    """Register ChatGPT widget HTML bundles as MCP resources.

    Widgets are registered with standard HTML mimeType for broader MCP host
    compatibility, while retaining OpenAI-specific metadata aliases.
    """
    # Determine base URL for CSP
    base_url = settings.PUBLIC_BASE_URL or "https://api.360ghar.com"

    registered_count = 0
    for widget_name, config in WIDGETS.items():
        widget_html = load_widget_html(widget_name)
        if widget_html:
            resource_uri = f"ui://widget/{widget_name.lower()}.html"

            resource_meta = {
                # --- MCP Apps standard (SEP-1865) keys ---
                "ui": {
                    "resourceUri": resource_uri,
                    "visibility": "host",
                    "csp": {
                        "connectDomains": [
                            base_url,
                            "https://api.360ghar.com",
                        ],
                        "resourceDomains": [
                            "https://images.360ghar.com",
                            "https://*.cloudinary.com",
                            "https://res.cloudinary.com",
                        ],
                    },
                },
                # --- Backward-compatible aliases ---
                "ui/resourceUri": resource_uri,
                "ui/visibility": "host",
                "openai/widgetPrefersBorder": True,
                "openai/widgetDomain": "https://chatgpt.com",
                "openai/widgetDescription": config.get("description", ""),
                "openai/widgetCSP": {
                    "connect_domains": [
                        base_url,
                        "https://api.360ghar.com",
                    ],
                    "resource_domains": [
                        "https://images.360ghar.com",
                        "https://*.cloudinary.com",
                        "https://res.cloudinary.com",
                    ],
                },
            }

            def make_widget_reader(html: str):
                async def get_widget() -> str:
                    return html

                return get_widget

            handler = make_widget_reader(widget_html)

            mcp.resource(
                resource_uri,
                mime_type="text/html",
                name=config["title"],
                description=config["description"],
                meta=resource_meta,
            )(handler)

            registered_count += 1
            logger.info(f"Registered ChatGPT widget: {widget_name} -> {resource_uri}")
        else:
            logger.debug(f"Widget not found (build required): {widget_name}")

    logger.info(f"Registered {registered_count}/{len(WIDGETS)} ChatGPT widgets")


def register_chatgpt_tools(mcp: FastMCP) -> None:
    """Register all ChatGPT-specific tools on the MCP server.

    This imports and registers:
    - Discovery tools (search, property details, feed, swipe, etc.)
    - Visit tools (schedule, list, get, cancel)
    - Property Management tools (leases, rent, maintenance for owners/tenants)
    """
    # Import tool modules to trigger registration
    from app.mcp.chatgpt import discovery_tools  # noqa: F401
    from app.mcp.chatgpt import visit_tools  # noqa: F401
    from app.mcp.chatgpt import pm_tools  # noqa: F401

    logger.info("Registered ChatGPT tools (discovery, visits, property management)")


__all__ = [
    "register_chatgpt_tools",
    "register_chatgpt_widgets",
    "get_widget_for_tool",
    "load_widget_html",
    "WIDGETS",
]
