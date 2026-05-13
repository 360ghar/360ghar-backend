"""Owner lease management tools for ChatGPT App."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from app.core.database import AsyncSessionLocal
from app.core.logging import get_logger
from app.mcp.apps_sdk import MCP_SECURITY_SCHEMES_MIXED, AuthRequiredError, build_widget_tool_meta
from app.mcp.chatgpt import get_widget_for_tool
from app.mcp.chatgpt.pm_shared import _format_lease_summary, _get_optional_user, _serialize_lease
from app.mcp.chatgpt.response_formatter import (
    format_auth_required_response,
    format_chatgpt_response,
)

# Import the user MCP server to register tools
from app.mcp.user.server import user_mcp
from app.models.enums import LeaseStatus

logger = get_logger(__name__)

# ChatGPT tool metadata for widget linkage
LEASE_MANAGEMENT_META = build_widget_tool_meta(
    widget_uri="ui://widget/leasemanagementwidget.html",
    invoking="Loading lease information...",
    invoked="Lease data loaded",
)


@user_mcp.tool(
    "owner_leases_list",
    annotations={
        "title": "List Property Leases",
        "readOnlyHint": True,
        "openWorldHint": False,
        "destructiveHint": False,
        "securitySchemes": MCP_SECURITY_SCHEMES_MIXED,
    },
    meta=LEASE_MANAGEMENT_META,
)
async def owner_leases_list(
    property_id: int | None = None,
    status: str | None = None,
    page: int = 1,
    limit: int = 20,
) -> dict[str, Any]:
    """List leases for the authenticated owner's properties."""
    try:
        from app.services.pm_leases import list_leases

        limit = min(max(1, limit), 50)
        page = max(1, page)

        async with AsyncSessionLocal() as db:
            user = await _get_optional_user(db)

            if not user:
                return format_auth_required_response(
                    action="list_leases",
                    message="To view your leases, please log in to your 360Ghar account.",
                )

            # Convert status string to LeaseStatus enum for the service layer
            lease_status = LeaseStatus(status) if status else None

            # Get leases for owner's properties
            leases = await list_leases(
                db,
                actor=user,
                owner_id=user.id,
                property_id=property_id,
                status=lease_status,
                limit=limit,
                offset=(page - 1) * limit,
            )

            serialized = [_serialize_lease(lease) for lease in leases]

            # Calculate stats
            active_count = sum(1 for lease_data in serialized if lease_data["status"] == "active")
            total_rent = sum(
                lease_data["monthly_rent"] or 0
                for lease_data in serialized
                if lease_data["status"] == "active"
            )

            return format_chatgpt_response(
                data={
                    "leases": serialized,
                    "total": len(serialized),
                    "page": page,
                    "limit": limit,
                    "stats": {
                        "active_leases": active_count,
                        "total_monthly_rent": total_rent,
                    },
                },
                content_summary=f"You have {len(serialized)} leases. {active_count} active with total monthly rent of ₹{total_rent:,.0f}.",
                widget_uri=get_widget_for_tool("owner_leases_list"),
            )

    except AuthRequiredError:
        raise
    except Exception as e:
        logger.error("Error in owner.leases.list: %s", e, exc_info=True)
        return format_chatgpt_response(
            data={"error": True, "message": str(e)},
            content_summary=f"Sorry, there was an error loading your leases: {str(e)}",
            widget_uri=get_widget_for_tool("owner_leases_list"),
        )


@user_mcp.tool(
    "owner_leases_get",
    annotations={
        "title": "Get Lease Details",
        "readOnlyHint": True,
        "openWorldHint": False,
        "destructiveHint": False,
        "securitySchemes": MCP_SECURITY_SCHEMES_MIXED,
    },
    meta=LEASE_MANAGEMENT_META,
)
async def owner_leases_get(
    lease_id: int,
) -> dict[str, Any]:
    """Get lease details for an authenticated owner or tenant."""
    try:
        from app.services.pm_leases import get_lease

        async with AsyncSessionLocal() as db:
            user = await _get_optional_user(db)

            if not user:
                return format_auth_required_response(
                    action="get_lease",
                    message="To view lease details, please log in to your 360Ghar account.",
                )

            try:
                lease = await get_lease(db, actor=user, lease_id=lease_id)
            except Exception as e:
                if "not found" in str(e).lower() or "permission" in str(e).lower():
                    return format_chatgpt_response(
                        data={"error": True, "code": "NOT_FOUND", "lease_id": lease_id},
                        content_summary=f"Lease with ID {lease_id} was not found or you don't have access to it.",
                        widget_uri=get_widget_for_tool("owner_leases_get"),
                    )
                raise

            lease_data = _serialize_lease(lease)

            return format_chatgpt_response(
                data={"lease": lease_data},
                content_summary=_format_lease_summary(lease_data),
                widget_uri=get_widget_for_tool("owner_leases_get"),
            )

    except AuthRequiredError:
        raise
    except Exception as e:
        logger.error("Error in owner.leases.get: %s", e, exc_info=True)
        return format_chatgpt_response(
            data={"error": True, "message": str(e)},
            content_summary=f"Sorry, there was an error loading the lease: {str(e)}",
            widget_uri=get_widget_for_tool("owner_leases_get"),
        )


@user_mcp.tool(
    "owner_leases_terminate",
    annotations={
        "title": "Terminate Lease",
        "readOnlyHint": False,
        "destructiveHint": True,
        "openWorldHint": False,
        "securitySchemes": MCP_SECURITY_SCHEMES_MIXED,
    },
    meta={
        "openai/toolInvocation/invoking": "Terminating lease...",
        "openai/toolInvocation/invoked": "Lease terminated",
    },
)
async def owner_leases_terminate(
    lease_id: int,
    termination_date: str,
    reason: str | None = None,
) -> dict[str, Any]:
    """Terminate an active lease early."""
    try:
        from app.services.pm_leases import terminate_lease

        async with AsyncSessionLocal() as db:
            user = await _get_optional_user(db)

            if not user:
                return format_auth_required_response(
                    action="terminate_lease",
                    message="To terminate a lease, please log in to your 360Ghar account.",
                )

            # Parse termination date
            try:
                term_date = datetime.fromisoformat(termination_date.replace("Z", "+00:00")).date()
            except ValueError:
                return format_chatgpt_response(
                    data={"error": True, "code": "INVALID_DATE"},
                    content_summary="Invalid date format. Please use ISO 8601 format like '2025-03-15'.",
                    widget_uri=get_widget_for_tool("owner_leases_terminate"),
                )

            try:
                await terminate_lease(
                    db,
                    actor=user,
                    lease_id=lease_id,
                    termination_date=term_date,
                    reason=reason,
                )
                await db.commit()
            except Exception as e:
                if "not found" in str(e).lower() or "permission" in str(e).lower():
                    return format_chatgpt_response(
                        data={"error": True, "code": "NOT_FOUND"},
                        content_summary=f"Lease with ID {lease_id} was not found or you don't have permission to terminate it.",
                        widget_uri=get_widget_for_tool("owner_leases_terminate"),
                    )
                raise

            return format_chatgpt_response(
                data={
                    "success": True,
                    "lease_id": lease_id,
                    "status": "terminated",
                    "termination_date": termination_date,
                },
                content_summary=f"Lease has been terminated effective {termination_date}.{' Reason: ' + reason if reason else ''}",
                widget_uri=get_widget_for_tool("owner_leases_terminate"),
            )

    except AuthRequiredError:
        raise
    except Exception as e:
        logger.error("Error in owner.leases.terminate: %s", e, exc_info=True)
        return format_chatgpt_response(
            data={"error": True, "message": str(e)},
            content_summary=f"Sorry, there was an error terminating the lease: {str(e)}",
            widget_uri=get_widget_for_tool("owner_leases_terminate"),
        )
