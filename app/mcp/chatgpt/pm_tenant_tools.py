"""
Tenant-specific tools for ChatGPT App.

Tools:
- tenant_rent_dues: View current rent dues for the tenant
"""

from __future__ import annotations

from typing import Any

from app.core.database import AsyncSessionLocal
from app.core.logging import get_logger
from app.mcp.apps_sdk import MCP_SECURITY_SCHEMES_MIXED, AuthRequiredError, build_widget_tool_meta
from app.mcp.chatgpt import get_widget_for_tool
from app.mcp.chatgpt.pm_shared import _get_optional_user, _serialize_rent_charge
from app.mcp.chatgpt.response_formatter import (
    format_auth_required_response,
    format_chatgpt_response,
)

# Import the user MCP server to register tools
from app.mcp.user.server import user_mcp

logger = get_logger(__name__)

# ChatGPT tool metadata for widget linkage
TENANT_RENT_META = build_widget_tool_meta(
    widget_uri="ui://widget/tenantrentwidget.html",
    invoking="Loading your rent status...",
    invoked="Rent status loaded",
)


@user_mcp.tool(
    "tenant_rent_dues",
    annotations={
        "title": "View My Rent Dues",
        "readOnlyHint": True,
        "openWorldHint": False,
        "destructiveHint": False,
        "securitySchemes": MCP_SECURITY_SCHEMES_MIXED,
    },
    meta=TENANT_RENT_META,
)
async def tenant_rent_dues() -> dict[str, Any]:
    """View current rent dues for the tenant.

    Shows outstanding rent charges and payment due dates.

    This tool requires authentication.

    Returns:
        Outstanding rent charges with due dates and amounts.
    """
    try:
        from sqlalchemy import select

        from app.models.enums import RentChargeStatus
        from app.models.pm_finance import RentCharge
        from app.models.pm_leases import Lease

        async with AsyncSessionLocal() as db:
            user = await _get_optional_user(db)

            if not user:
                return format_auth_required_response(
                    action="rent_dues",
                    message="To view your rent dues, please log in to your 360Ghar account.",
                )

            # Get tenant's active leases
            lease_stmt = select(Lease.id).where(Lease.tenant_user_id == user.id)
            lease_result = await db.execute(lease_stmt)
            lease_ids = [row[0] for row in lease_result.fetchall()]

            if not lease_ids:
                return format_chatgpt_response(
                    data={"charges": [], "total_due": 0},
                    content_summary="You don't have any active leases.",
                    widget_uri=get_widget_for_tool("tenant_rent_dues"),
                )

            # Get outstanding charges
            charges_stmt = (
                select(RentCharge)
                .where(
                    RentCharge.lease_id.in_(lease_ids),
                    RentCharge.status.in_(
                        [
                            RentChargeStatus.pending,
                            RentChargeStatus.partial,
                            RentChargeStatus.overdue,
                        ]
                    ),
                )
                .order_by(RentCharge.due_date)
            )

            charges_result = await db.execute(charges_stmt)
            charges = charges_result.scalars().all()

            serialized = [_serialize_rent_charge(c) for c in charges]
            total_due = sum(c["balance"] for c in serialized)
            overdue_count = sum(1 for c in serialized if c["status"] == "overdue")

            if total_due == 0:
                summary = "Your rent is up to date! No outstanding payments."
            else:
                summary = f"You have ₹{total_due:,.0f} in outstanding rent."
                if overdue_count > 0:
                    summary += f" {overdue_count} payment(s) are overdue."

            return format_chatgpt_response(
                data={
                    "charges": serialized,
                    "total_due": total_due,
                    "overdue_count": overdue_count,
                },
                content_summary=summary,
                widget_uri=get_widget_for_tool("tenant_rent_dues"),
            )

    except AuthRequiredError:
        raise
    except Exception as e:
        logger.error("Error in tenant.rent.dues: %s", e, exc_info=True)
        return format_chatgpt_response(
            data={"error": True, "message": str(e)},
            content_summary=f"Sorry, there was an error loading your rent dues: {str(e)}",
            widget_uri=get_widget_for_tool("tenant_rent_dues"),
        )
