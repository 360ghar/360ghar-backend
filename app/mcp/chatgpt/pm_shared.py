"""
Shared helpers and utilities for Property Management ChatGPT tools.

These helpers are used across the PM tool sub-modules:
- Serialization helpers for leases, rent charges, and payments
- Natural-language formatting helpers
- Optional user retrieval from MCP context
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from app.core.logging import get_logger
from app.mcp.chatgpt.response_formatter import format_price
from app.mcp.utils import get_user_from_mcp_context, serialize_lease
from app.services.pm.lifecycle import charge_due_total
from app.services.pm.rent_rules import ZERO_MONEY, money

logger = get_logger(__name__)


async def _get_optional_user(db):
    """Get user if authenticated, None for guests."""
    return await get_user_from_mcp_context(db)


def _serialize_lease(lease, viewer) -> dict[str, Any]:
    """The shared lease wire shape (app.mcp.utils.serialize_lease), masked for ``viewer``."""
    return serialize_lease(lease, viewer)


def _serialize_rent_charge(
    charge,
    *,
    amount_paid: Decimal | float,
    status: Any = None,
    pending_fee: Decimal = ZERO_MONEY,
) -> dict[str, Any]:
    """Serialize one rent charge.

    ``amount_paid`` is the settled total from RentPayment rows (``settled_paid_totals``
    or ``list_rent_charges``). ``status`` overrides the stored status when given.
    ``pending_fee`` is the late fee the daily job has not assessed yet
    (``lifecycle.pending_late_fee``); it counts in the amount due, the late fee and the
    balance, as in the rent-due list. The arithmetic is exact (Decimal). The JSON numbers
    are produced here, at the boundary.
    """
    due = charge_due_total(charge) + pending_fee
    paid = money(amount_paid)
    raw_status = status if status is not None else charge.status
    return {
        "id": charge.id,
        "lease_id": charge.lease_id,
        "billing_month": charge.billing_month.isoformat() if charge.billing_month else None,
        "due_date": charge.due_date.isoformat() if charge.due_date else None,
        "amount_due": float(due),
        "amount_paid": float(paid),
        "balance": float(max(due - paid, ZERO_MONEY)),
        "status": getattr(raw_status, "value", raw_status),
        "late_fee": float(money(charge.late_fee_assessed) + pending_fee),
    }


def _format_lease_summary(lease_data: dict[str, Any]) -> str:
    """Generate natural language summary of a lease."""
    # property and tenant are None when the query did not load them.
    property_title = (lease_data.get("property") or {}).get("title") or "property"
    tenant_name = (lease_data.get("tenant") or {}).get("display_name") or "tenant"
    monthly_rent = lease_data.get("monthly_rent", 0)
    status = lease_data.get("status", "active")
    start_date = lease_data.get("start_date", "")
    end_date = lease_data.get("end_date", "")

    rent_str = (
        f"₹{format_price(monthly_rent, is_monthly_rent=True)}/month"
        if monthly_rent
        else "rent not set"
    )
    return f"Lease for {property_title} with {tenant_name}. Status: {status}. {rent_str}. Period: {start_date} to {end_date}."


def _format_rent_summary(charges: list[dict], totals: dict) -> str:
    """Generate natural language summary of rent status."""
    total_due = totals.get("total_due", 0)
    total_paid = totals.get("total_paid", 0)
    overdue = totals.get("overdue_count", 0)

    if total_due == 0:
        return "All rent is current. No outstanding balances."

    summary = f"Rent status: ₹{format_price(total_paid, is_monthly_rent=True)} collected, ₹{format_price(total_due, is_monthly_rent=True)} outstanding."
    if overdue > 0:
        summary += f" {overdue} overdue charges require attention."
    return summary
