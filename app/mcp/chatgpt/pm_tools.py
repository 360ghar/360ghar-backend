"""
Property Management tools for ChatGPT App.

These tools enable property management features for owners and tenants:
- Owner: Lease management, rent collection, property analytics
- Tenant: View rent dues, make payment requests

All tools use ChatGPT-specific response formatting for rich widget display.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional

from app.core.database import AsyncSessionLocal
from app.core.logging import get_logger
from app.mcp.apps_sdk import AuthRequiredError, MCP_SECURITY_SCHEMES_MIXED, build_widget_tool_meta
from app.mcp.chatgpt.response_formatter import (
    format_chatgpt_response,
    format_auth_required_response,
)
from app.mcp.utils import get_user_from_mcp_context

# Import the user MCP server to register tools
from app.mcp.user_server import user_mcp

logger = get_logger(__name__)

# ChatGPT tool metadata for widget linkage
LEASE_MANAGEMENT_META = build_widget_tool_meta(
    widget_uri="ui://widget/leasemanagementwidget.html",
    invoking="Loading lease information...",
    invoked="Lease data loaded",
)

RENT_COLLECTION_META = build_widget_tool_meta(
    widget_uri="ui://widget/rentcollectionwidget.html",
    invoking="Loading rent data...",
    invoked="Rent data loaded",
)

OWNER_DASHBOARD_META = build_widget_tool_meta(
    widget_uri="ui://widget/ownerdashboardwidget.html",
    invoking="Loading dashboard...",
    invoked="Dashboard ready",
)

MAINTENANCE_META = build_widget_tool_meta(
    widget_uri="ui://widget/maintenancewidget.html",
    invoking="Loading maintenance requests...",
    invoked="Maintenance data loaded",
)

TENANT_RENT_META = build_widget_tool_meta(
    widget_uri="ui://widget/tenantrentwidget.html",
    invoking="Loading your rent status...",
    invoked="Rent status loaded",
)


async def _get_optional_user(db):
    """Get user if authenticated, None for guests."""
    return await get_user_from_mcp_context(db)


def _serialize_lease(lease) -> Dict[str, Any]:
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
    if lease.tenant:
        tenant_data = {
            "id": lease.tenant.id,
            "name": lease.tenant.full_name,
            "phone": lease.tenant.phone,
            "email": lease.tenant.email,
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
        "rent_paid_through": lease.rent_paid_through.isoformat() if hasattr(lease, "rent_paid_through") and lease.rent_paid_through else None,
        "created_at": lease.created_at.isoformat() if lease.created_at else None,
    }


def _serialize_rent_charge(charge) -> Dict[str, Any]:
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
        "late_fee": float(charge.late_fee) if hasattr(charge, "late_fee") and charge.late_fee else 0,
    }


def _serialize_rent_payment(payment) -> Dict[str, Any]:
    """Serialize a rent payment object."""
    return {
        "id": payment.id,
        "rent_charge_id": payment.rent_charge_id,
        "amount": float(payment.amount) if payment.amount else 0,
        "payment_date": payment.payment_date.isoformat() if payment.payment_date else None,
        "payment_method": payment.payment_method.value if hasattr(payment.payment_method, "value") else payment.payment_method,
        "transaction_id": payment.transaction_id,
        "notes": payment.notes,
        "created_at": payment.created_at.isoformat() if payment.created_at else None,
    }


def _format_lease_summary(lease_data: Dict[str, Any]) -> str:
    """Generate natural language summary of a lease."""
    property_title = lease_data.get("property", {}).get("title", "property")
    tenant_name = lease_data.get("tenant", {}).get("name", "tenant")
    monthly_rent = lease_data.get("monthly_rent", 0)
    status = lease_data.get("status", "active")
    start_date = lease_data.get("start_date", "")
    end_date = lease_data.get("end_date", "")

    rent_str = f"₹{monthly_rent:,.0f}/month" if monthly_rent else "rent not set"
    return f"Lease for {property_title} with {tenant_name}. Status: {status}. {rent_str}. Period: {start_date} to {end_date}."


def _format_rent_summary(charges: List[Dict], totals: Dict) -> str:
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


# ============================================================================
# Owner Lease Management Tools
# ============================================================================


@user_mcp.tool(
    "owner_leases_list",
    annotations={
        "title": "List Property Leases",
        "readOnlyHint": True,
        "securitySchemes": MCP_SECURITY_SCHEMES_MIXED,
    },
    meta=LEASE_MANAGEMENT_META,
)
async def owner_leases_list(
    property_id: Optional[int] = None,
    status: Optional[str] = None,
    page: int = 1,
    limit: int = 20,
) -> Dict[str, Any]:
    """List leases for properties owned by the user.

    View all lease agreements for your properties with tenant information.

    This tool requires authentication.

    Args:
        property_id: Filter by specific property ID
        status: Filter by status (active, pending, expired, terminated)
        page: Page number for pagination
        limit: Results per page (max 50)

    Returns:
        List of leases with tenant and property details.
    """
    try:
        from app.services.pm_leases import list_leases
        from app.schemas.user import User as UserSchema

        limit = min(max(1, limit), 50)
        page = max(1, page)

        async with AsyncSessionLocal() as db:
            user = await _get_optional_user(db)

            if not user:
                return format_auth_required_response(
                    action="list_leases",
                    message="To view your leases, please log in to your 360Ghar account.",
                )

            user_schema = UserSchema.model_validate(user)

            # Get leases for owner's properties
            leases = await list_leases(
                db,
                actor=user_schema,
                owner_id=user.id,
                property_id=property_id,
                status=status,
                limit=limit,
                offset=(page - 1) * limit,
            )

            serialized = [_serialize_lease(lease) for lease in leases]

            # Calculate stats
            active_count = sum(1 for l in serialized if l["status"] == "active")
            total_rent = sum(l["monthly_rent"] or 0 for l in serialized if l["status"] == "active")

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
            )

    except AuthRequiredError:
        raise
    except Exception as e:
        logger.error(f"Error in owner.leases.list: {e}", exc_info=True)
        return format_chatgpt_response(
            data={"error": True, "message": str(e)},
            content_summary=f"Sorry, there was an error loading your leases: {str(e)}",
        )


@user_mcp.tool(
    "owner_leases_get",
    annotations={
        "title": "Get Lease Details",
        "readOnlyHint": True,
        "securitySchemes": MCP_SECURITY_SCHEMES_MIXED,
    },
    meta=LEASE_MANAGEMENT_META,
)
async def owner_leases_get(
    lease_id: int,
) -> Dict[str, Any]:
    """Get detailed information about a specific lease.

    View full lease details including tenant info, payment status, and terms.

    This tool requires authentication.

    Args:
        lease_id: The lease ID to retrieve

    Returns:
        Full lease details with tenant and property information.
    """
    try:
        from app.services.pm_leases import get_lease
        from app.schemas.user import User as UserSchema

        async with AsyncSessionLocal() as db:
            user = await _get_optional_user(db)

            if not user:
                return format_auth_required_response(
                    action="get_lease",
                    message="To view lease details, please log in to your 360Ghar account.",
                )

            user_schema = UserSchema.model_validate(user)

            try:
                lease = await get_lease(db, actor=user_schema, lease_id=lease_id)
            except Exception as e:
                if "not found" in str(e).lower() or "permission" in str(e).lower():
                    return format_chatgpt_response(
                        data={"error": True, "code": "NOT_FOUND", "lease_id": lease_id},
                        content_summary=f"Lease with ID {lease_id} was not found or you don't have access to it.",
                    )
                raise

            lease_data = _serialize_lease(lease)

            return format_chatgpt_response(
                data={"lease": lease_data},
                content_summary=_format_lease_summary(lease_data),
            )

    except AuthRequiredError:
        raise
    except Exception as e:
        logger.error(f"Error in owner.leases.get: {e}", exc_info=True)
        return format_chatgpt_response(
            data={"error": True, "message": str(e)},
            content_summary=f"Sorry, there was an error loading the lease: {str(e)}",
        )


@user_mcp.tool(
    "owner_leases_terminate",
    annotations={
        "title": "Terminate Lease",
        "readOnlyHint": False,
        "destructiveHint": True,
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
    reason: Optional[str] = None,
) -> Dict[str, Any]:
    """Terminate an active lease early.

    End a lease agreement before its scheduled end date.

    This tool requires authentication.

    Args:
        lease_id: The lease ID to terminate
        termination_date: The effective termination date (ISO 8601 format)
        reason: Optional reason for termination

    Returns:
        Confirmation of lease termination.
    """
    try:
        from app.services.pm_leases import terminate_lease
        from app.schemas.user import User as UserSchema

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
                )

            user_schema = UserSchema.model_validate(user)

            try:
                lease = await terminate_lease(
                    db,
                    actor=user_schema,
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
            )

    except AuthRequiredError:
        raise
    except Exception as e:
        logger.error(f"Error in owner.leases.terminate: {e}", exc_info=True)
        return format_chatgpt_response(
            data={"error": True, "message": str(e)},
            content_summary=f"Sorry, there was an error terminating the lease: {str(e)}",
        )


# ============================================================================
# Owner Rent Management Tools
# ============================================================================


@user_mcp.tool(
    "owner_rent_status",
    annotations={
        "title": "View Rent Collection Status",
        "readOnlyHint": True,
        "securitySchemes": MCP_SECURITY_SCHEMES_MIXED,
    },
    meta=RENT_COLLECTION_META,
)
async def owner_rent_status(
    property_id: Optional[int] = None,
    include_paid: bool = False,
    page: int = 1,
    limit: int = 20,
) -> Dict[str, Any]:
    """View rent collection status for your properties.

    Shows outstanding rent charges, overdue payments, and collection summary.

    This tool requires authentication.

    Args:
        property_id: Filter by specific property ID
        include_paid: Include fully paid charges (default: False, only show outstanding)
        page: Page number for pagination
        limit: Results per page (max 50)

    Returns:
        Rent charges with payment status and totals.
    """
    try:
        from app.services.pm_rent import list_rent_charges
        from app.schemas.user import User as UserSchema
        from app.models.enums import RentChargeStatus

        limit = min(max(1, limit), 50)
        page = max(1, page)

        async with AsyncSessionLocal() as db:
            user = await _get_optional_user(db)

            if not user:
                return format_auth_required_response(
                    action="rent_status",
                    message="To view rent status, please log in to your 360Ghar account.",
                )

            user_schema = UserSchema.model_validate(user)

            # Get rent charges
            status_filter = None if include_paid else ["pending", "partial", "overdue"]
            charges = await list_rent_charges(
                db,
                actor=user_schema,
                owner_id=user.id,
                property_id=property_id,
                status=status_filter,
                limit=limit,
                offset=(page - 1) * limit,
            )

            serialized = [_serialize_rent_charge(c) for c in charges]

            # Calculate totals
            total_due = sum(c["balance"] for c in serialized)
            total_paid = sum(c["amount_paid"] for c in serialized)
            overdue_count = sum(1 for c in serialized if c["status"] == "overdue")

            totals = {
                "total_due": total_due,
                "total_paid": total_paid,
                "overdue_count": overdue_count,
                "charges_count": len(serialized),
            }

            return format_chatgpt_response(
                data={
                    "charges": serialized,
                    "totals": totals,
                    "page": page,
                    "limit": limit,
                },
                content_summary=_format_rent_summary(serialized, totals),
            )

    except AuthRequiredError:
        raise
    except Exception as e:
        logger.error(f"Error in owner.rent.status: {e}", exc_info=True)
        return format_chatgpt_response(
            data={"error": True, "message": str(e)},
            content_summary=f"Sorry, there was an error loading rent status: {str(e)}",
        )


@user_mcp.tool(
    "owner_rent_record_payment",
    annotations={
        "title": "Record Rent Payment",
        "readOnlyHint": False,
        "securitySchemes": MCP_SECURITY_SCHEMES_MIXED,
    },
    meta=RENT_COLLECTION_META,
)
async def owner_rent_record_payment(
    rent_charge_id: int,
    amount: float,
    payment_date: str,
    payment_method: str,
    transaction_id: Optional[str] = None,
    notes: Optional[str] = None,
) -> Dict[str, Any]:
    """Record a rent payment received from a tenant.

    Log a payment against an outstanding rent charge.

    This tool requires authentication.

    Args:
        rent_charge_id: The rent charge ID to apply payment to
        amount: Payment amount in INR
        payment_date: Date payment was received (ISO 8601 format)
        payment_method: Method of payment (cash, bank_transfer, upi, cheque, online)
        transaction_id: Optional transaction/reference ID
        notes: Optional payment notes

    Returns:
        Payment confirmation with updated charge status.
    """
    try:
        from app.services.pm_rent import record_rent_payment
        from app.schemas.user import User as UserSchema
        from app.models.enums import PaymentMethod

        async with AsyncSessionLocal() as db:
            user = await _get_optional_user(db)

            if not user:
                return format_auth_required_response(
                    action="record_payment",
                    message="To record a payment, please log in to your 360Ghar account.",
                )

            # Parse payment date
            try:
                pay_date = datetime.fromisoformat(payment_date.replace("Z", "+00:00")).date()
            except ValueError:
                return format_chatgpt_response(
                    data={"error": True, "code": "INVALID_DATE"},
                    content_summary="Invalid date format. Please use ISO 8601 format like '2025-02-15'.",
                )

            # Validate payment method
            try:
                method = PaymentMethod(payment_method.lower())
            except ValueError:
                valid_methods = [m.value for m in PaymentMethod]
                return format_chatgpt_response(
                    data={"error": True, "code": "INVALID_METHOD", "valid_methods": valid_methods},
                    content_summary=f"Invalid payment method. Please use one of: {', '.join(valid_methods)}.",
                )

            user_schema = UserSchema.model_validate(user)

            try:
                payment = await record_rent_payment(
                    db,
                    actor=user_schema,
                    rent_charge_id=rent_charge_id,
                    amount=amount,
                    payment_date=pay_date,
                    payment_method=method,
                    transaction_id=transaction_id,
                    notes=notes,
                )
                await db.commit()
            except Exception as e:
                if "not found" in str(e).lower():
                    return format_chatgpt_response(
                        data={"error": True, "code": "NOT_FOUND"},
                        content_summary=f"Rent charge with ID {rent_charge_id} was not found.",
                    )
                raise

            return format_chatgpt_response(
                data={
                    "success": True,
                    "payment": _serialize_rent_payment(payment),
                },
                content_summary=f"Payment of ₹{amount:,.0f} recorded successfully via {payment_method} on {payment_date}.",
            )

    except AuthRequiredError:
        raise
    except Exception as e:
        logger.error(f"Error in owner.rent.record_payment: {e}", exc_info=True)
        return format_chatgpt_response(
            data={"error": True, "message": str(e)},
            content_summary=f"Sorry, there was an error recording the payment: {str(e)}",
        )


@user_mcp.tool(
    "owner_rent_history",
    annotations={
        "title": "View Payment History",
        "readOnlyHint": True,
        "securitySchemes": MCP_SECURITY_SCHEMES_MIXED,
    },
    meta=RENT_COLLECTION_META,
)
async def owner_rent_history(
    property_id: Optional[int] = None,
    lease_id: Optional[int] = None,
    page: int = 1,
    limit: int = 20,
) -> Dict[str, Any]:
    """View rent payment history for your properties.

    See all recorded payments with dates and methods.

    This tool requires authentication.

    Args:
        property_id: Filter by specific property ID
        lease_id: Filter by specific lease ID
        page: Page number for pagination
        limit: Results per page (max 50)

    Returns:
        List of rent payments with details.
    """
    try:
        from app.services.pm_rent import list_rent_payments
        from app.schemas.user import User as UserSchema

        limit = min(max(1, limit), 50)
        page = max(1, page)

        async with AsyncSessionLocal() as db:
            user = await _get_optional_user(db)

            if not user:
                return format_auth_required_response(
                    action="rent_history",
                    message="To view payment history, please log in to your 360Ghar account.",
                )

            user_schema = UserSchema.model_validate(user)

            payments = await list_rent_payments(
                db,
                actor=user_schema,
                owner_id=user.id,
                property_id=property_id,
                lease_id=lease_id,
                limit=limit,
                offset=(page - 1) * limit,
            )

            serialized = [_serialize_rent_payment(p) for p in payments]
            total_collected = sum(p["amount"] for p in serialized)

            return format_chatgpt_response(
                data={
                    "payments": serialized,
                    "total": len(serialized),
                    "total_collected": total_collected,
                    "page": page,
                    "limit": limit,
                },
                content_summary=f"Showing {len(serialized)} payments totaling ₹{total_collected:,.0f}.",
            )

    except AuthRequiredError:
        raise
    except Exception as e:
        logger.error(f"Error in owner.rent.history: {e}", exc_info=True)
        return format_chatgpt_response(
            data={"error": True, "message": str(e)},
            content_summary=f"Sorry, there was an error loading payment history: {str(e)}",
        )


# ============================================================================
# Owner Dashboard/Analytics Tools
# ============================================================================


@user_mcp.tool(
    "owner_dashboard_overview",
    annotations={
        "title": "Property Owner Dashboard",
        "readOnlyHint": True,
        "securitySchemes": MCP_SECURITY_SCHEMES_MIXED,
    },
    meta=OWNER_DASHBOARD_META,
)
async def owner_dashboard_overview(
) -> Dict[str, Any]:
    """Get a comprehensive dashboard overview for property owners.

    Shows portfolio summary, occupancy stats, rent collection, and recent activity.

    This tool requires authentication.

    Returns:
        Dashboard metrics including properties, leases, rent, and maintenance.
    """
    try:
        from app.services.pm_dashboard import get_dashboard_overview
        from app.schemas.user import User as UserSchema

        async with AsyncSessionLocal() as db:
            user = await _get_optional_user(db)

            if not user:
                return format_auth_required_response(
                    action="dashboard",
                    message="To view your dashboard, please log in to your 360Ghar account.",
                )

            user_schema = UserSchema.model_validate(user)

            dashboard = await get_dashboard_overview(db, actor=user_schema, owner_id=user.id)

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
            )

    except AuthRequiredError:
        raise
    except Exception as e:
        logger.error(f"Error in owner.dashboard.overview: {e}", exc_info=True)
        return format_chatgpt_response(
            data={"error": True, "message": str(e)},
            content_summary=f"Sorry, there was an error loading your dashboard: {str(e)}",
        )


@user_mcp.tool(
    "owner_maintenance_list",
    annotations={
        "title": "List Maintenance Requests",
        "readOnlyHint": True,
        "securitySchemes": MCP_SECURITY_SCHEMES_MIXED,
    },
    meta=MAINTENANCE_META,
)
async def owner_maintenance_list(
    property_id: Optional[int] = None,
    status: Optional[str] = None,
    priority: Optional[str] = None,
    page: int = 1,
    limit: int = 20,
) -> Dict[str, Any]:
    """List maintenance requests for your properties.

    View all maintenance issues reported by tenants.

    This tool requires authentication.

    Args:
        property_id: Filter by specific property ID
        status: Filter by status (open, in_progress, scheduled, completed, cancelled)
        priority: Filter by priority (low, medium, high, urgent)
        page: Page number for pagination
        limit: Results per page (max 50)

    Returns:
        List of maintenance requests with status and priority.
    """
    try:
        from sqlalchemy import select

        from app.models.enums import MaintenanceRequestStatus, MaintenanceUrgency, WorkOrderStatus
        from app.models.pm_maintenance import MaintenanceRequest
        from app.models.properties import Property
        from app.mcp.utils import serialize_maintenance_request

        limit = min(max(1, limit), 50)
        page = max(1, page)

        async with AsyncSessionLocal() as db:
            user = await _get_optional_user(db)

            if not user:
                return format_auth_required_response(
                    action="list_maintenance",
                    message="To view maintenance requests, please log in to your 360Ghar account.",
                )

            # Get property IDs owned by user
            props_stmt = select(Property.id).where(Property.owner_id == user.id)
            props_result = await db.execute(props_stmt)
            owner_property_ids = [row[0] for row in props_result.fetchall()]

            if not owner_property_ids:
                return format_chatgpt_response(
                    data={"items": [], "total": 0, "stats": {}},
                    content_summary="You don't have any properties to show maintenance requests for.",
                )

            # Build maintenance query
            stmt = select(MaintenanceRequest).where(
                MaintenanceRequest.property_id.in_(owner_property_ids)
            )

            if property_id:
                stmt = stmt.where(MaintenanceRequest.property_id == property_id)

            if status:
                status_norm = status.lower().strip()
                if status_norm == "open":
                    stmt = stmt.where(MaintenanceRequest.request_status == MaintenanceRequestStatus.open)
                elif status_norm == "in_progress":
                    stmt = stmt.where(MaintenanceRequest.work_order_status == WorkOrderStatus.in_progress)
                elif status_norm == "scheduled":
                    stmt = stmt.where(MaintenanceRequest.scheduled_for.is_not(None))
                elif status_norm == "completed":
                    stmt = stmt.where(MaintenanceRequest.completed_at.is_not(None))
                elif status_norm == "cancelled":
                    stmt = stmt.where(MaintenanceRequest.work_order_status == WorkOrderStatus.cancelled)

            if priority:
                priority_norm = priority.lower().strip()
                urgency_map = {
                    "low": MaintenanceUrgency.low,
                    "medium": MaintenanceUrgency.medium,
                    "high": MaintenanceUrgency.high,
                    "urgent": MaintenanceUrgency.emergency,
                    "emergency": MaintenanceUrgency.emergency,
                }
                urgency = urgency_map.get(priority_norm)
                if urgency is not None:
                    stmt = stmt.where(MaintenanceRequest.urgency == urgency)

            stmt = stmt.order_by(MaintenanceRequest.created_at.desc())
            stmt = stmt.offset((page - 1) * limit).limit(limit)

            result = await db.execute(stmt)
            requests = result.scalars().all()

            serialized = [serialize_maintenance_request(r) for r in requests]

            # Stats
            open_count = sum(1 for r in serialized if r["status"] in ("open", "in_progress"))
            urgent_count = sum(1 for r in serialized if r["priority"] == "urgent")

            return format_chatgpt_response(
                data={
                    "items": serialized,
                    "total": len(serialized),
                    "page": page,
                    "limit": limit,
                    "total_pages": (len(serialized) + limit - 1) // limit if serialized else 0,
                    "stats": {
                        "open": open_count,
                        "urgent": urgent_count,
                    },
                },
                content_summary=f"Found {len(serialized)} maintenance requests. {open_count} open, {urgent_count} urgent.",
            )

    except AuthRequiredError:
        raise
    except Exception as e:
        logger.error(f"Error in owner.maintenance.list: {e}", exc_info=True)
        return format_chatgpt_response(
            data={"error": True, "message": str(e)},
            content_summary=f"Sorry, there was an error loading maintenance requests: {str(e)}",
        )


@user_mcp.tool(
    "owner_maintenance_update",
    annotations={
        "title": "Update Maintenance Request",
        "readOnlyHint": False,
        "securitySchemes": MCP_SECURITY_SCHEMES_MIXED,
    },
    meta=MAINTENANCE_META,
)
async def owner_maintenance_update(
    request_id: int,
    status: str,
    vendor_name: Optional[str] = None,
    scheduled_date: Optional[str] = None,
    estimated_cost: Optional[float] = None,
    actual_cost: Optional[float] = None,
    resolution_notes: Optional[str] = None,
) -> Dict[str, Any]:
    """Update a maintenance request status.

    Update status, assign vendor, schedule work, or mark as complete.

    This tool requires authentication.

    Args:
        request_id: The maintenance request ID to update
        status: New status (in_progress, scheduled, completed, cancelled)
        vendor_name: Name of assigned vendor/contractor
        scheduled_date: Scheduled date for the work (ISO 8601 format)
        estimated_cost: Estimated cost of repair
        actual_cost: Actual cost after completion
        resolution_notes: Notes about the resolution

    Returns:
        Updated maintenance request details.
    """
    try:
        from sqlalchemy import select

        from app.models.enums import MaintenanceRequestStatus, WorkOrderStatus
        from app.models.pm_maintenance import MaintenanceRequest
        from app.models.properties import Property
        from app.mcp.utils import serialize_maintenance_request

        async with AsyncSessionLocal() as db:
            user = await _get_optional_user(db)

            if not user:
                return format_auth_required_response(
                    action="update_maintenance",
                    message="To update maintenance requests, please log in to your 360Ghar account.",
                )

            # Get the maintenance request
            stmt = select(MaintenanceRequest).where(MaintenanceRequest.id == request_id)
            result = await db.execute(stmt)
            request = result.scalar_one_or_none()

            if not request:
                return format_chatgpt_response(
                    data={"error": True, "code": "NOT_FOUND"},
                    content_summary=f"Maintenance request with ID {request_id} was not found.",
                )

            # Verify ownership
            prop_stmt = select(Property).where(Property.id == request.property_id)
            prop_result = await db.execute(prop_stmt)
            prop = prop_result.scalar_one_or_none()

            if not prop or prop.owner_id != user.id:
                return format_chatgpt_response(
                    data={"error": True, "code": "FORBIDDEN"},
                    content_summary="You don't have permission to update this maintenance request.",
                )

            valid_statuses = ["open", "in_progress", "scheduled", "completed", "cancelled"]
            status_norm = status.lower().strip()
            if status_norm not in valid_statuses:
                return format_chatgpt_response(
                    data={
                        "error": True,
                        "code": "INVALID_STATUS",
                        "valid_statuses": valid_statuses,
                    },
                    content_summary=f"Invalid status. Please use one of: {', '.join(valid_statuses)}.",
                )

            # Update optional fields
            if scheduled_date:
                try:
                    request.scheduled_for = datetime.fromisoformat(scheduled_date.replace("Z", "+00:00"))
                except ValueError:
                    pass
            if estimated_cost is not None:
                request.estimated_cost = estimated_cost
            if actual_cost is not None:
                request.actual_cost = actual_cost

            if resolution_notes is not None:
                request.completion_notes = resolution_notes

            if status_norm == "open":
                request.request_status = MaintenanceRequestStatus.open
                request.work_order_status = None
                request.scheduled_for = None
                request.completed_at = None
            elif status_norm == "scheduled":
                request.request_status = MaintenanceRequestStatus.work_order_created
                request.work_order_status = WorkOrderStatus.assigned
            elif status_norm == "in_progress":
                request.request_status = MaintenanceRequestStatus.work_order_created
                request.work_order_status = WorkOrderStatus.in_progress
            elif status_norm == "completed":
                request.request_status = MaintenanceRequestStatus.resolved
                request.work_order_status = WorkOrderStatus.completed
                if request.completed_at is None:
                    request.completed_at = datetime.now(timezone.utc)
            elif status_norm == "cancelled":
                request.request_status = MaintenanceRequestStatus.closed
                request.work_order_status = WorkOrderStatus.cancelled

            await db.commit()

            return format_chatgpt_response(
                data={
                    "success": True,
                    "request": serialize_maintenance_request(request),
                },
                content_summary=f"Maintenance request updated to '{status_norm}'.",
            )

    except AuthRequiredError:
        raise
    except Exception as e:
        logger.error(f"Error in owner.maintenance.update: {e}", exc_info=True)
        return format_chatgpt_response(
            data={"error": True, "message": str(e)},
            content_summary=f"Sorry, there was an error updating the maintenance request: {str(e)}",
        )


# ============================================================================
# Tenant Rent Tools
# ============================================================================


@user_mcp.tool(
    "tenant_rent_dues",
    annotations={
        "title": "View My Rent Dues",
        "readOnlyHint": True,
        "securitySchemes": MCP_SECURITY_SCHEMES_MIXED,
    },
    meta=TENANT_RENT_META,
)
async def tenant_rent_dues(
) -> Dict[str, Any]:
    """View current rent dues for the tenant.

    Shows outstanding rent charges and payment due dates.

    This tool requires authentication.

    Returns:
        Outstanding rent charges with due dates and amounts.
    """
    try:
        from sqlalchemy import select
        from app.models.pm_finance import RentCharge
        from app.models.pm_leases import Lease
        from app.models.enums import RentChargeStatus

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
                )

            # Get outstanding charges
            charges_stmt = select(RentCharge).where(
                RentCharge.lease_id.in_(lease_ids),
                RentCharge.status.in_([RentChargeStatus.pending, RentChargeStatus.partial, RentChargeStatus.overdue]),
            ).order_by(RentCharge.due_date)

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
            )

    except AuthRequiredError:
        raise
    except Exception as e:
        logger.error(f"Error in tenant.rent.dues: {e}", exc_info=True)
        return format_chatgpt_response(
            data={"error": True, "message": str(e)},
            content_summary=f"Sorry, there was an error loading your rent dues: {str(e)}",
        )
