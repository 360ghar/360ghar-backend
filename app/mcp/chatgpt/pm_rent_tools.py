"""Owner rent management tools for ChatGPT App."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from app.core.database import AsyncSessionLocal
from app.core.logging import get_logger
from app.mcp.apps_sdk import MCP_SECURITY_SCHEMES_MIXED, AuthRequiredError, build_widget_tool_meta
from app.mcp.chatgpt import get_widget_for_tool
from app.mcp.chatgpt.pm_shared import (
    _format_rent_summary,
    _get_optional_user,
    _serialize_rent_charge,
    _serialize_rent_payment,
)
from app.mcp.chatgpt.response_formatter import (
    format_auth_required_response,
    format_chatgpt_response,
)

# Import the user MCP server to register tools
from app.mcp.user.server import user_mcp

logger = get_logger(__name__)

# ChatGPT tool metadata for widget linkage
RENT_COLLECTION_META = build_widget_tool_meta(
    widget_uri="ui://widget/rentcollectionwidget.html",
    invoking="Loading rent data...",
    invoked="Rent data loaded",
)


@user_mcp.tool(
    "owner_rent_status",
    annotations={
        "title": "View Rent Collection Status",
        "readOnlyHint": True,
        "openWorldHint": False,
        "destructiveHint": False,
        "securitySchemes": MCP_SECURITY_SCHEMES_MIXED,
    },
    meta=RENT_COLLECTION_META,
)
async def owner_rent_status(
    property_id: int | None = None,
    include_paid: bool = False,
    page: int = 1,
    limit: int = 20,
) -> dict[str, Any]:
    """View rent charges and collection totals for the authenticated owner."""
    try:
        from app.models.enums import RentChargeStatus
        from app.services.pm_rent import list_rent_charges

        limit = min(max(1, limit), 50)
        page = max(1, page)

        async with AsyncSessionLocal() as db:
            user = await _get_optional_user(db)

            if not user:
                return format_auth_required_response(
                    action="rent_status",
                    message="To view rent status, please log in to your 360Ghar account.",
                )

            # list_rent_charges accepts a single RentChargeStatus, not a list.
            # When excluding paid charges, query each unpaid status and merge.
            if include_paid:
                charges = await list_rent_charges(
                    db,
                    actor=user,
                    owner_id=user.id,
                    property_id=property_id,
                    status=None,
                    limit=limit,
                    offset=(page - 1) * limit,
                )
            else:
                unpaid_statuses = [RentChargeStatus.pending, RentChargeStatus.partial, RentChargeStatus.overdue]
                all_charges: list = []
                for s in unpaid_statuses:
                    batch = await list_rent_charges(
                        db,
                        actor=user,
                        owner_id=user.id,
                        property_id=property_id,
                        status=s,
                        limit=limit,
                        offset=0,
                    )
                    all_charges.extend(batch)
                # Sort by due_date ascending (matching service default) and paginate
                def _sort_key(c: Any) -> Any:
                    charge_obj = c.get("charge") if isinstance(c, dict) and "charge" in c else c
                    return getattr(charge_obj, "due_date", None) or ""

                all_charges.sort(key=_sort_key)
                offset = (page - 1) * limit
                charges = all_charges[offset : offset + limit]

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
                widget_uri=get_widget_for_tool("owner_rent_status"),
            )

    except AuthRequiredError:
        raise
    except Exception as e:
        logger.error("Error in owner.rent.status: %s", e, exc_info=True)
        return format_chatgpt_response(
            data={"error": True, "message": str(e)},
            content_summary=f"Sorry, there was an error loading rent status: {str(e)}",
            widget_uri=get_widget_for_tool("owner_rent_status"),
        )


@user_mcp.tool(
    "owner_rent_record_payment",
    annotations={
        "title": "Record Rent Payment",
        "readOnlyHint": False,
        "destructiveHint": False,
        "openWorldHint": False,
        "securitySchemes": MCP_SECURITY_SCHEMES_MIXED,
    },
    meta=RENT_COLLECTION_META,
)
async def owner_rent_record_payment(
    rent_charge_id: int,
    amount: float,
    payment_date: str,
    payment_method: str,
    transaction_id: str | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    """Record a rent payment against an outstanding charge."""
    try:
        from app.models.enums import PaymentMethod
        from app.services.pm_rent import record_rent_payment

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
                    widget_uri=get_widget_for_tool("owner_rent_record_payment"),
                )

            # Validate payment method
            try:
                method = PaymentMethod(payment_method.lower())
            except ValueError:
                valid_methods = [m.value for m in PaymentMethod]
                return format_chatgpt_response(
                    data={"error": True, "code": "INVALID_METHOD", "valid_methods": valid_methods},
                    content_summary=f"Invalid payment method. Please use one of: {', '.join(valid_methods)}.",
                    widget_uri=get_widget_for_tool("owner_rent_record_payment"),
                )

            try:
                payment = await record_rent_payment(
                    db,
                    actor=user,
                    charge_id=rent_charge_id,
                    amount_paid=amount,
                    paid_at=datetime.combine(pay_date, datetime.min.time()),
                    payment_method=method,
                    reference=transaction_id,
                    notes=notes,
                )
                await db.commit()
            except Exception as e:
                if "not found" in str(e).lower():
                    return format_chatgpt_response(
                        data={"error": True, "code": "NOT_FOUND"},
                        content_summary=f"Rent charge with ID {rent_charge_id} was not found.",
                        widget_uri=get_widget_for_tool("owner_rent_record_payment"),
                    )
                raise

            return format_chatgpt_response(
                data={
                    "success": True,
                    "payment": _serialize_rent_payment(payment),
                },
                content_summary=f"Payment of ₹{amount:,.0f} recorded successfully via {payment_method} on {payment_date}.",
                widget_uri=get_widget_for_tool("owner_rent_record_payment"),
            )

    except AuthRequiredError:
        raise
    except Exception as e:
        logger.error("Error in owner.rent.record_payment: %s", e, exc_info=True)
        return format_chatgpt_response(
            data={"error": True, "message": str(e)},
            content_summary=f"Sorry, there was an error recording the payment: {str(e)}",
            widget_uri=get_widget_for_tool("owner_rent_record_payment"),
        )


@user_mcp.tool(
    "owner_rent_history",
    annotations={
        "title": "View Payment History",
        "readOnlyHint": True,
        "openWorldHint": False,
        "destructiveHint": False,
        "securitySchemes": MCP_SECURITY_SCHEMES_MIXED,
    },
    meta=RENT_COLLECTION_META,
)
async def owner_rent_history(
    property_id: int | None = None,
    lease_id: int | None = None,
    page: int = 1,
    limit: int = 20,
) -> dict[str, Any]:
    """View rent payment history for the authenticated owner's properties."""
    try:
        from app.services.pm_rent import list_rent_payments

        limit = min(max(1, limit), 50)
        page = max(1, page)

        async with AsyncSessionLocal() as db:
            user = await _get_optional_user(db)

            if not user:
                return format_auth_required_response(
                    action="rent_history",
                    message="To view payment history, please log in to your 360Ghar account.",
                )

            payments = await list_rent_payments(
                db,
                actor=user,
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
                widget_uri=get_widget_for_tool("owner_rent_history"),
            )

    except AuthRequiredError:
        raise
    except Exception as e:
        logger.error("Error in owner.rent.history: %s", e, exc_info=True)
        return format_chatgpt_response(
            data={"error": True, "message": str(e)},
            content_summary=f"Sorry, there was an error loading payment history: {str(e)}",
            widget_uri=get_widget_for_tool("owner_rent_history"),
        )
