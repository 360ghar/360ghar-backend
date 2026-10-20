from __future__ import annotations

from datetime import UTC, date, datetime, time
from typing import Any

from app.core.exceptions import (
    BadRequestException,
    InsufficientPermissionsError,
    NotFoundException,
)
from app.mcp.admin.agent_tools.common import (
    MCP_SECURITY_SCHEMES_OAUTH2_ONLY,
    AuthRequiredError,
    MCPErrorCode,
    MCPResponse,
    _get_user,
    _require_agent_or_admin,
    _require_auth,
    admin_mcp,
    get_db,
    get_user_role,
    internal_error_response,
    invalid_input_response,
    logger,
    not_found_response,
)
from app.mcp.apps_sdk import build_widget_tool_meta
from app.mcp.tool_ops.rent import compute_rent_due_items, record_lease_rent_payment
from app.mcp.utils import serialize_rent_payment
from app.models.enums import PaymentMethod, UserRole
from app.schemas.pagination import decode_cursor

AGENT_RENT_COLLECTION_META = build_widget_tool_meta(
    widget_uri="ui://widget/rentcollectionwidget.html",
    invoking="Loading rent data...",
    invoked="Rent data loaded",
)


@admin_mcp.tool(
    "agent_rent_list_due",
    annotations={
        "title": "List Overdue Rent",
        "readOnlyHint": True,
        "openWorldHint": False,
        "destructiveHint": False,
        "securitySchemes": MCP_SECURITY_SCHEMES_OAUTH2_ONLY,
    },
    meta=AGENT_RENT_COLLECTION_META,
)
async def agent_rent_list_due(
    owner_id: int | None = None,
    property_id: int | None = None,
    overdue_only: bool = False,
    cursor: str | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    """List due/overdue rent payments.

    Args:
        owner_id: Filter by owner
        property_id: Filter by property
        overdue_only: Only show overdue payments
        cursor: Opaque pagination cursor from a prior response's next_cursor
        limit: Items per page
    """
    try:
        limit = min(max(1, limit), 100)
        cursor_payload = (
            decode_cursor(
                cursor,
                {"owner_id": owner_id, "property_id": property_id, "overdue_only": overdue_only},
            )
            if cursor
            else {}
        )

        async for db in get_db():
            user = await _get_user(db)
            if not user:
                _require_auth(
                    action="agent_rent_list_due",
                    message="Please log in to view overdue rent.",
                    scope="mcp:read",
                )

            if not _require_agent_or_admin(user):
                return MCPResponse.failure(
                    MCPErrorCode.INSUFFICIENT_PERMISSIONS,
                    "This endpoint is for agents and admins only",
                ).model_dump()

            from app.services.pm_authz import get_accessible_owner_ids

            user_role = get_user_role(user)
            owner_ids: list[int] | None = None

            if user_role != UserRole.admin:
                accessible_owners = await get_accessible_owner_ids(db, actor=user)
                if owner_id and accessible_owners is not None and owner_id not in accessible_owners:
                    return MCPResponse.success(
                        {
                            "items": [],
                            "totals": {
                                "total_due": 0,
                                "total_paid": 0,
                                "overdue_count": 0,
                                "charges_count": 0,
                            },
                            "next_cursor": None,
                            "has_more": False,
                            "limit": limit,
                        }
                    ).model_dump()
                owner_ids = list(accessible_owners) if accessible_owners is not None else []

            if owner_id:
                owner_ids = [owner_id]

            due_data = await compute_rent_due_items(
                db,
                owner_ids=owner_ids,
                property_id=property_id,
                overdue_only=overdue_only,
                cursor_payload=cursor_payload,
                limit=limit,
                filters={
                    "owner_id": owner_id,
                    "property_id": property_id,
                    "overdue_only": overdue_only,
                },
            )

            return MCPResponse.success(due_data).model_dump()
    except AuthRequiredError:
        raise
    except BadRequestException as e:
        return invalid_input_response(str(e))
    except Exception as e:
        logger.error("Error in agent.rent.list_due: %s", e, exc_info=True)
        return internal_error_response(f"Failed to list due rent: {str(e)}")
    return {}


@admin_mcp.tool(
    "agent_rent_record_payment",
    annotations={
        "title": "Record Rent Payment",
        "readOnlyHint": False,
        "destructiveHint": False,
        "openWorldHint": False,
        "securitySchemes": MCP_SECURITY_SCHEMES_OAUTH2_ONLY,
    },
    meta=AGENT_RENT_COLLECTION_META,
)
async def agent_rent_record_payment(
    lease_id: int,
    amount: float,
    payment_date: date,
    payment_method: PaymentMethod = PaymentMethod.bank_transfer,
    transaction_reference: str | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    """Record a settled rent payment for a lease. It settles the oldest open charge.

    Args:
        lease_id: ID of the lease
        amount: Payment amount
        payment_date: Date of payment (YYYY-MM-DD)
        payment_method: cash, bank_transfer, upi, cheque, online or other
        transaction_reference: Reference number
        notes: Additional notes
    """
    try:
        async for db in get_db():
            user = await _get_user(db)
            if not user:
                _require_auth(
                    action="agent_rent_record_payment",
                    message="Please log in to record a rent payment.",
                    scope="mcp:write",
                )

            if not _require_agent_or_admin(user):
                return MCPResponse.failure(
                    MCPErrorCode.INSUFFICIENT_PERMISSIONS,
                    "This endpoint is for agents and admins only",
                ).model_dump()

            try:
                payment = await record_lease_rent_payment(
                    db,
                    actor=user,
                    lease_id=lease_id,
                    amount=amount,
                    paid_at=datetime.combine(payment_date, time.min, tzinfo=UTC),
                    payment_method=payment_method,
                    reference=transaction_reference,
                    notes=notes,
                )
            except NotFoundException:
                return not_found_response("Lease", lease_id)
            except InsufficientPermissionsError:
                return MCPResponse.failure(
                    MCPErrorCode.INSUFFICIENT_PERMISSIONS, "You do not have access to this lease"
                ).model_dump()

            result = MCPResponse.success(
                {
                    "message": "Payment recorded",
                    "payment": serialize_rent_payment(payment),
                }
            ).model_dump()
            await db.commit()
            return result
    except AuthRequiredError:
        raise
    except BadRequestException as e:
        return invalid_input_response(str(e))
    except Exception as e:
        logger.error("Error in agent.rent.record_payment: %s", e, exc_info=True)
        return internal_error_response(f"Failed to record payment: {str(e)}")
    return {}
