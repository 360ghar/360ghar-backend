"""
Tenant-specific tools for ChatGPT App.

Tools:
- tenant_rent_dues: View current rent dues for the tenant
"""

from __future__ import annotations

from typing import Any

from app.core.database import AsyncSessionLocal
from app.core.logging import get_logger
from app.mcp.apps_sdk import (
    MCP_SECURITY_SCHEMES_OAUTH2_ONLY,
    AuthRequiredError,
    build_widget_tool_meta,
)
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
        "securitySchemes": MCP_SECURITY_SCHEMES_OAUTH2_ONLY,
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
        from app.services.pm.lifecycle import (
            charge_outstanding,
            effective_status,
            pending_late_fee,
            settled_paid_totals,
        )
        from app.services.pm.rent_rules import ZERO_MONEY, business_today, grace_days, money

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
                select(RentCharge, Lease)
                .join(Lease, Lease.id == RentCharge.lease_id)
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

            charge_rows = list((await db.execute(charges_stmt)).all())

            paid_by_charge = await settled_paid_totals(db, [c.id for c, _ in charge_rows])
            today = business_today()
            serialized = []
            balance_sum = ZERO_MONEY
            for charge, lease in charge_rows:
                paid = paid_by_charge.get(charge.id, ZERO_MONEY)
                # The late fee the daily job has not assessed yet counts, as in the rent-due list.
                pending_fee = pending_late_fee(charge, lease, paid, today)
                balance = charge_outstanding(charge, paid) + pending_fee
                # Read-time status (the daily job may not have run). A repaid charge is not due.
                status = effective_status(
                    charge.status,
                    charge.due_date,
                    grace_days(lease.grace_period_days),
                    balance,
                    today,
                )
                if status == RentChargeStatus.paid:
                    continue
                serialized.append(
                    _serialize_rent_charge(
                        charge, amount_paid=paid, status=status, pending_fee=pending_fee
                    )
                )
                balance_sum += balance
            # Sum the Decimal balances. The JSON number is made once, here.
            total_due = float(money(balance_sum))
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
