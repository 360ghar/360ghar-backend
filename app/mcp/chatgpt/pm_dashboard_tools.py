"""
Owner Dashboard/Analytics tools for ChatGPT App.

Tools:
- owner_dashboard_overview: Get a comprehensive dashboard overview for property owners
"""

from __future__ import annotations

from typing import Any

from app.core.database import AsyncSessionLocal
from app.core.logging import get_logger
from app.mcp.apps_sdk import MCP_SECURITY_SCHEMES_MIXED, AuthRequiredError, build_widget_tool_meta
from app.mcp.chatgpt import get_widget_for_tool
from app.mcp.chatgpt.pm_shared import _get_optional_user
from app.mcp.chatgpt.response_formatter import (
    format_auth_required_response,
    format_chatgpt_response,
)

# Import the user MCP server to register tools
from app.mcp.user.server import user_mcp

logger = get_logger(__name__)

# ChatGPT tool metadata for widget linkage
OWNER_DASHBOARD_META = build_widget_tool_meta(
    widget_uri="ui://widget/ownerdashboardwidget.html",
    invoking="Loading dashboard...",
    invoked="Dashboard ready",
)


@user_mcp.tool(
    "owner_dashboard_overview",
    annotations={
        "title": "Property Owner Dashboard",
        "readOnlyHint": True,
        "openWorldHint": False,
        "destructiveHint": False,
        "securitySchemes": MCP_SECURITY_SCHEMES_MIXED,
    },
    meta=OWNER_DASHBOARD_META,
)
async def owner_dashboard_overview() -> dict[str, Any]:
    """Get a comprehensive dashboard overview for property owners.

    Shows portfolio summary, occupancy stats, rent collection, and recent activity.

    This tool requires authentication.

    Returns:
        Dashboard metrics including properties, leases, rent, and maintenance.
    """
    try:
        from app.services.pm_dashboard import get_dashboard_overview

        async with AsyncSessionLocal() as db:
            user = await _get_optional_user(db)

            if not user:
                return format_auth_required_response(
                    action="dashboard",
                    message="To view your dashboard, please log in to your 360Ghar account.",
                )

            dashboard = await get_dashboard_overview(db, actor=user, owner_id=user.id)

            # Format summary
            total_props = dashboard.get("properties", {}).get("total", 0)
            occupied = dashboard.get("properties", {}).get("occupied", 0)
            vacant = dashboard.get("properties", {}).get("vacant", 0)
            monthly_income = dashboard.get("rent", {}).get("expected_monthly", 0)
            collected = dashboard.get("rent", {}).get("collected_this_month", 0)
            pending_maintenance = dashboard.get("maintenance", {}).get("open", 0)

            summary = (
                f"Portfolio: {total_props} properties ({occupied} occupied, {vacant} vacant). "
                f"Monthly rent: ₹{monthly_income:,.0f} expected, ₹{collected:,.0f} collected this month. "
                f"{pending_maintenance} open maintenance requests."
            )

            return format_chatgpt_response(
                data={"dashboard": dashboard},
                content_summary=summary,
                widget_uri=get_widget_for_tool("owner_dashboard_overview"),
            )

    except AuthRequiredError:
        raise
    except Exception as e:
        logger.error("Error in owner.dashboard.overview: %s", e, exc_info=True)
        return format_chatgpt_response(
            data={"error": True, "message": str(e)},
            content_summary=f"Sorry, there was an error loading your dashboard: {str(e)}",
            widget_uri=get_widget_for_tool("owner_dashboard_overview"),
        )
