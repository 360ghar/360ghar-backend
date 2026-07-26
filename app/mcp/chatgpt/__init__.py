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

import hashlib
from pathlib import Path
from typing import Any

from fastmcp import FastMCP

from app.config import settings
from app.core.logging import get_logger
from app.mcp.apps_sdk import RESOURCE_MIME_TYPE

logger = get_logger(__name__)

# Populated at registration time with versioned URIs keyed by tool name.
_TOOL_WIDGET_URIS: dict[str, str] = {}

# Widget directory (where built HTML bundles are stored)
# Located at project_root/chatgpt-widgets/dist/
WIDGET_DIR = Path(__file__).parent.parent.parent.parent / "chatgpt-widgets" / "dist"

# Widget to tool mapping with metadata
WIDGETS: dict[str, dict[str, Any]] = {
    "PropertySearchWidget": {
        "tools": [
            "discovery_search",
            "discovery_recommendations",
            "guest_property_search",
            "guest_property_recommendations",
        ],
        "title": "Property Search Results",
        "description": "Grid view of property search results with filtering",
    },
    "PropertyDetailsWidget": {
        "tools": [
            "discovery_property_get",
            "guest_property_details",
            "owner_properties_get",
            "agent_properties_get",
        ],
        "title": "Property Details",
        "description": "Full property details with images and amenities",
    },
    "PropertySwipeWidget": {
        "tools": ["discovery_feed"],
        "title": "Property Discovery",
        "description": "Swipe-based property discovery interface",
    },
    "VisitSchedulerWidget": {
        "tools": ["visits_schedule", "bookings_get"],
        "title": "Schedule Visit",
        "description": "Schedule a property visit with date/time selection",
    },
    "VisitListWidget": {
        "tools": [
            "visits_list",
            "bookings_list",
            "agent_bookings_list_all",
        ],
        "title": "My Visits",
        "description": "List of scheduled property visits",
    },
    "LeaseDetailsWidget": {
        "tools": ["tenant_lease_current"],
        "title": "Lease Details",
        "description": "Current lease information for tenants",
    },
    "MaintenanceWidget": {
        "tools": [
            "tenant_maintenance_list",
            "tenant_maintenance_create",
            "agent_maintenance_list",
        ],
        "title": "Maintenance Requests",
        "description": "Submit and track maintenance requests",
    },
    "OwnerDashboardWidget": {
        "tools": [
            "owner_properties_list",
            "owner_dashboard_overview",
            "agent_properties_list",
            "agent_dashboard_overview",
        ],
        "title": "Owner Dashboard",
        "description": "Property owner dashboard with stats and listings",
    },
    # Property Management Widgets
    "LeaseManagementWidget": {
        "tools": [
            "owner_leases_list",
            "owner_leases_get",
            "agent_leases_list",
        ],
        "title": "Lease Management",
        "description": "View and manage property leases",
    },
    "RentCollectionWidget": {
        "tools": [
            "owner_rent_status",
            "owner_rent_record_payment",
            "owner_rent_history",
            "agent_rent_list_due",
            "agent_rent_record_payment",
        ],
        "title": "Rent Collection",
        "description": "Track rent payments and record transactions",
    },
    "TenantRentWidget": {
        "tools": ["tenant_rent_dues", "tenant_rent_history"],
        "title": "My Rent",
        "description": "View rent dues and payment history",
    },
}


def load_widget_html(widget_name: str) -> str | None:
    """Load widget HTML bundle from disk."""
    widget_path = WIDGET_DIR / f"{widget_name}.html"
    if widget_path.exists():
        return widget_path.read_text()
    return None


def get_widget_for_tool(tool_name: str) -> str | None:
    """Get the versioned widget URI for a tool.

    Returns the content-hashed URI if widgets have been registered,
    otherwise falls back to the un-versioned URI.
    """
    if tool_name in _TOOL_WIDGET_URIS:
        return _TOOL_WIDGET_URIS[tool_name]
    for widget_name, config in WIDGETS.items():
        if tool_name in config["tools"]:
            return f"ui://widget/{widget_name.lower()}.html"
    return None


def get_widget_name_for_tool(tool_name: str) -> str | None:
    """Get the widget class name for a tool (e.g. 'OwnerDashboardWidget')."""
    for widget_name, config in WIDGETS.items():
        if tool_name in config["tools"]:
            return widget_name
    return None


def _build_widget_resource_meta(
    *,
    resource_uri: str,
    base_url: str,
    description: str,
) -> dict[str, Any]:
    """Build metadata for a concrete widget resource URI."""
    return {
        # --- MCP Apps standard (SEP-1865) keys ---
        "ui": {
            "resourceUri": resource_uri,
            "visibility": "host",
            "domain": base_url,
            "prefersBorder": True,
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
                "frameDomains": [],
            },
        },
        # --- Backward-compatible OpenAI aliases ---
        "ui/resourceUri": resource_uri,
        "ui/visibility": "host",
        "openai/widgetPrefersBorder": True,
        "openai/widgetDomain": base_url,
        "openai/widgetDescription": description,
        "openai/widgetCSP": {
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
    }


def register_chatgpt_widgets(mcp: FastMCP) -> None:
    """Register ChatGPT widget HTML bundles as MCP resources.

    Widgets are registered with standard HTML mimeType for broader MCP host
    compatibility, while retaining OpenAI-specific metadata aliases. Each
    widget is exposed at both the stable URI advertised in tool metadata and a
    content-hashed alias used by result-level widget hints.
    """
    # Determine base URL for CSP
    base_url = settings.PUBLIC_BASE_URL or "https://api.360ghar.com"

    registered_count = 0
    for widget_name, config in WIDGETS.items():
        widget_html = load_widget_html(widget_name)
        if widget_html:
            # Append content hash for cache busting when widgets change.
            content_hash = hashlib.md5(widget_html.encode()).hexdigest()[:8]
            stable_resource_uri = f"ui://widget/{widget_name.lower()}.html"
            versioned_resource_uri = f"{stable_resource_uri}?v={content_hash}"

            def make_widget_reader(html: str):
                async def get_widget() -> str:
                    return html

                return get_widget

            handler = make_widget_reader(widget_html)

            for resource_uri in (stable_resource_uri, versioned_resource_uri):
                mcp.resource(
                    resource_uri,
                    mime_type=RESOURCE_MIME_TYPE,
                    name=config["title"],
                    description=config["description"],
                    meta=_build_widget_resource_meta(
                        resource_uri=resource_uri,
                        base_url=base_url,
                        description=config.get("description", ""),
                    ),
                )(handler)

            # Store versioned URIs so get_widget_for_tool() returns them.
            for tool_name in config["tools"]:
                _TOOL_WIDGET_URIS[tool_name] = versioned_resource_uri

            registered_count += 1
            logger.info(
                "Registered ChatGPT widget: %s -> %s",
                widget_name,
                versioned_resource_uri,
            )
        else:
            logger.debug("Widget not found (build required): %s", widget_name)

    logger.info("Registered %s/%s ChatGPT widgets", registered_count, len(WIDGETS))


__all__ = [
    "register_chatgpt_widgets",
    "get_widget_for_tool",
    "get_widget_name_for_tool",
    "load_widget_html",
    "WIDGETS",
]
