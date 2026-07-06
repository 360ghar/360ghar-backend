from __future__ import annotations

from datetime import datetime
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
    make_tz_aware,
    not_found_response,
)
from app.mcp.apps_sdk import build_widget_tool_meta
from app.mcp.tool_ops.rent import compute_rent_due_items
from app.models.enums import UserRole
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
        cursor_payload = decode_cursor(cursor) if cursor else {}

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
                    "This endpoint is for agents and admins only"
                ).model_dump()

            from app.services.pm_authz import get_accessible_owner_ids

            user_role = get_user_role(user)
            owner_ids: list[int] | None = None

            if user_role != UserRole.admin:
                accessible_owners = await get_accessible_owner_ids(db, actor=user)
                owner_ids = list(accessible_owners) if accessible_owners is not None else None
                if owner_id and owner_ids is not None and owner_id not in owner_ids:
                    return MCPResponse.success({
                        "items": [],
                        "total_due": 0,
                        "overdue_count": 0,
                        "next_cursor": None,
                        "has_more": False,
                        "limit": limit,
                        "total": 0,
                    }).model_dump()

            if owner_id:
                owner_ids = [owner_id]

            due_data = await compute_rent_due_items(
                db,
                owner_ids=owner_ids,
                property_id=property_id,
                overdue_only=overdue_only,
                cursor_payload=cursor_payload,
                limit=limit,
            )
            due_data["total"] = len(due_data["items"])

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
    payment_date: str,
    payment_method: str,
    transaction_reference: str | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    """Record a rent payment for a lease.

    Args:
        lease_id: ID of the lease
        amount: Payment amount
        payment_date: Date of payment (ISO-8601)
        payment_method: cash, bank_transfer, upi, cheque, online
        transaction_reference: Reference number
        notes: Additional notes
    """
    try:
        from app.models.pm_finance import RentPayment

        try:
            pay_date = make_tz_aware(datetime.fromisoformat(payment_date))
        except ValueError:
            return invalid_input_response("payment_date must be in ISO-8601 format")
        if pay_date is None:
            return invalid_input_response("payment_date must be in ISO-8601 format")

        valid_methods = ['cash', 'bank_transfer', 'upi', 'cheque', 'online', 'other']
        if payment_method.lower() not in valid_methods:
            return invalid_input_response(f"payment_method must be one of: {', '.join(valid_methods)}")

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
                    "This endpoint is for agents and admins only"
                ).model_dump()

            from app.schemas.user import User as UserSchema
            from app.services.pm_authz import assert_can_access_lease

            user_schema = UserSchema.model_validate(user)

            try:
                await assert_can_access_lease(
                    db, actor=user_schema, lease_id=lease_id
                )
            except NotFoundException:
                return not_found_response("Lease", lease_id)
            except InsufficientPermissionsError:
                return MCPResponse.failure(
                    MCPErrorCode.INSUFFICIENT_PERMISSIONS,
                    "You do not have access to this lease"
                ).model_dump()

            # Create payment record
            payment = RentPayment(
                lease_id=lease_id,
                amount_paid=amount,
                paid_at=pay_date,
                payment_method=payment_method.lower(),
                reference=transaction_reference,
                notes=notes,
                recorded_by_user_id=user.id,
                status="completed",
            )
            db.add(payment)
            await db.flush()
            await db.refresh(payment)
            await db.commit()

            return MCPResponse.success({
                "message": "Payment recorded successfully",
                "payment": {
                    "id": payment.id,
                    "lease_id": payment.lease_id,
                    "amount": float(payment.amount_paid),
                    "payment_date": payment.paid_at.isoformat() if payment.paid_at else None,
                    "payment_method": payment.payment_method,
                    "status": payment.status,  # type: ignore[attr-defined]
                },
            }).model_dump()
    except AuthRequiredError:
        raise
    except BadRequestException as e:
        return invalid_input_response(str(e))
    except Exception as e:
        logger.error("Error in agent.rent.record_payment: %s", e, exc_info=True)
        return internal_error_response(f"Failed to record payment: {str(e)}")
    return {}
