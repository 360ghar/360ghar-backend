"""
Shared helpers and utilities for Property Management ChatGPT tools.

These helpers are used across the PM tool sub-modules:
- Serialization helpers for leases, rent charges, and payments
- Natural-language formatting helpers
- Optional user retrieval from MCP context
"""

from __future__ import annotations

from typing import Any

from app.core.logging import get_logger
from app.mcp.utils import get_user_from_mcp_context

logger = get_logger(__name__)


async def _get_optional_user(db):
    """Get user if authenticated, None for guests."""
    return await get_user_from_mcp_context(db)


def _serialize_lease(lease) -> dict[str, Any]:
    """Serialize a lease object."""
    property_data = None
    if lease.property:
        property_data = {
            "id": lease.property.id,
            "title": lease.property.title,
            "locality": lease.property.locality,
            "city": lease.property.city,
            "full_address": lease.property.full_address,
            "main_image_url": lease.property.images[0].image_url if lease.property.images else None,
        }

    tenant_data = None
    if lease.tenant_user:
        tenant_data = {
            "id": lease.tenant_user.id,
            "name": lease.tenant_user.full_name,
            "phone": lease.tenant_user.phone,
            "email": lease.tenant_user.email,
        }

    return {
        "id": lease.id,
        "property_id": lease.property_id,
        "property": property_data,
        "tenant_user_id": lease.tenant_user_id,
        "tenant": tenant_data,
        "start_date": lease.start_date.isoformat() if lease.start_date else None,
        "end_date": lease.end_date.isoformat() if lease.end_date else None,
        "monthly_rent": float(lease.monthly_rent) if lease.monthly_rent else None,
        "security_deposit": float(lease.security_deposit) if lease.security_deposit else None,
        "payment_due_day": lease.payment_due_day,
        "status": lease.status.value if hasattr(lease.status, "value") else lease.status,
        "rent_paid_through": lease.rent_paid_through.isoformat()
        if hasattr(lease, "rent_paid_through") and lease.rent_paid_through
        else None,
        "created_at": lease.created_at.isoformat() if lease.created_at else None,
    }


def _serialize_rent_charge(charge) -> dict[str, Any]:
    """Serialize a rent charge object."""
    return {
        "id": charge.id,
        "lease_id": charge.lease_id,
        "billing_month": charge.billing_month.isoformat() if charge.billing_month else None,
        "due_date": charge.due_date.isoformat() if charge.due_date else None,
        "amount_due": float(charge.amount_due) if charge.amount_due else 0,
        "amount_paid": float(charge.amount_paid) if charge.amount_paid else 0,
        "balance": float(charge.amount_due - charge.amount_paid) if charge.amount_due else 0,
        "status": charge.status.value if hasattr(charge.status, "value") else charge.status,
        "late_fee": float(charge.late_fee)
        if hasattr(charge, "late_fee") and charge.late_fee
        else 0,
    }


def _serialize_rent_payment(payment) -> dict[str, Any]:
    """Serialize a rent payment object."""
    return {
        "id": payment.id,
        "rent_charge_id": payment.rent_charge_id,
        "amount": float(payment.amount) if payment.amount else 0,
        "payment_date": payment.payment_date.isoformat() if payment.payment_date else None,
        "payment_method": payment.payment_method.value
        if hasattr(payment.payment_method, "value")
        else payment.payment_method,
        "transaction_id": payment.transaction_id,
        "notes": payment.notes,
        "created_at": payment.created_at.isoformat() if payment.created_at else None,
    }


def _format_lease_summary(lease_data: dict[str, Any]) -> str:
    """Generate natural language summary of a lease."""
    property_title = lease_data.get("property", {}).get("title", "property")
    tenant_name = lease_data.get("tenant", {}).get("name", "tenant")
    monthly_rent = lease_data.get("monthly_rent", 0)
    status = lease_data.get("status", "active")
    start_date = lease_data.get("start_date", "")
    end_date = lease_data.get("end_date", "")

    rent_str = f"₹{monthly_rent:,.0f}/month" if monthly_rent else "rent not set"
    return f"Lease for {property_title} with {tenant_name}. Status: {status}. {rent_str}. Period: {start_date} to {end_date}."


def _format_rent_summary(charges: list[dict], totals: dict) -> str:
    """Generate natural language summary of rent status."""
    total_due = totals.get("total_due", 0)
    total_paid = totals.get("total_paid", 0)
    overdue = totals.get("overdue_count", 0)

    if total_due == 0:
        return "All rent is current. No outstanding balances."

    summary = f"Rent status: ₹{total_paid:,.0f} collected, ₹{total_due:,.0f} outstanding."
    if overdue > 0:
        summary += f" {overdue} overdue charges require attention."
    return summary
