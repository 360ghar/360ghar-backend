from __future__ import annotations

from datetime import datetime
from typing import Any

from app.core.exceptions import (
    InsufficientPermissionsError,
    NotFoundException,
)
from app.mcp.admin.agent_tools.common import (
    MCP_SECURITY_SCHEMES_MIXED,
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
    utc_now,
)
from app.models.enums import UserRole


@admin_mcp.tool(
    "agent_rent_list_due",
    annotations={
        "title": "List Overdue Rent",
        "readOnlyHint": True,
        "openWorldHint": False,
        "destructiveHint": False,
        "securitySchemes": MCP_SECURITY_SCHEMES_MIXED,
    },
)
async def agent_rent_list_due(
    owner_id: int | None = None,
    property_id: int | None = None,
    overdue_only: bool = False,
    page: int = 1,
    limit: int = 20,
) -> dict[str, Any]:
    """List due/overdue rent payments.

    Args:
        owner_id: Filter by owner
        property_id: Filter by property
        overdue_only: Only show overdue payments
        page: Page number
        limit: Items per page
    """
    try:
        from sqlalchemy import select

        from app.models.enums import LeaseStatus
        from app.models.pm_leases import Lease

        limit = min(max(1, limit), 100)

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

            # Get active leases
            stmt = select(Lease).where(Lease.status == LeaseStatus.active)

            if user_role != UserRole.admin:
                accessible_owners = await get_accessible_owner_ids(db, actor=user)
                if accessible_owners is not None:
                    stmt = stmt.where(Lease.owner_id.in_(accessible_owners))

            if owner_id:
                stmt = stmt.where(Lease.owner_id == owner_id)
            if property_id:
                stmt = stmt.where(Lease.property_id == property_id)

            result = await db.execute(stmt)
            leases = result.scalars().all()

            # Calculate due amounts for each lease
            today = utc_now().date()
            due_items = []

            for lease in leases:
                payment_due_day = lease.payment_due_day or 1
                grace_days = lease.grace_period_days or 5

                # Determine if rent is due this month
                due_date = today.replace(day=min(payment_due_day, 28))
                grace_end = due_date.replace(day=min(payment_due_day + grace_days, 28))

                is_overdue = today > grace_end
                is_due = today >= due_date

                if overdue_only and not is_overdue:
                    continue

                if is_due:
                    due_items.append({
                        "lease_id": lease.id,
                        "property_id": lease.property_id,
                        "owner_id": lease.owner_id,
                        "tenant_user_id": lease.tenant_user_id,
                        "monthly_rent": float(lease.monthly_rent or 0),
                        "due_date": due_date.isoformat(),
                        "is_overdue": is_overdue,
                        "days_overdue": (today - grace_end).days if is_overdue else 0,
                    })

            # Paginate
            start = (page - 1) * limit
            end = start + limit
            paginated = due_items[start:end]

            return MCPResponse.success({
                "total": len(due_items),
                "overdue_count": sum(1 for i in due_items if i["is_overdue"]),
                "page": page,
                "limit": limit,
                "items": paginated,
            }).model_dump()
    except AuthRequiredError:
        raise
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
        "securitySchemes": MCP_SECURITY_SCHEMES_MIXED,
    },
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
    except Exception as e:
        logger.error("Error in agent.rent.record_payment: %s", e, exc_info=True)
        return internal_error_response(f"Failed to record payment: {str(e)}")
    return {}
