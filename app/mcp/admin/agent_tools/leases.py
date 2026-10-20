from __future__ import annotations

from datetime import datetime
from typing import Any

from app.core.exceptions import (
    BadRequestException,
    ConflictException,
    InsufficientPermissionsError,
    NotFoundException,
    PropertyNotFoundException,
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
    internal_error_response,
    invalid_input_response,
    logger,
    not_found_response,
    serialize_lease,
    utc_now,
)
from app.mcp.apps_sdk import build_widget_tool_meta
from app.models.enums import LeaseStatus
from app.schemas.pagination import decode_cursor

AGENT_LEASES_LIST_META = build_widget_tool_meta(
    widget_uri="ui://widget/leasemanagementwidget.html",
    invoking="Loading leases...",
    invoked="Leases loaded",
)


@admin_mcp.tool(
    "agent_leases_list",
    annotations={
        "title": "List Leases",
        "readOnlyHint": True,
        "openWorldHint": False,
        "destructiveHint": False,
        "securitySchemes": MCP_SECURITY_SCHEMES_OAUTH2_ONLY,
    },
    meta=AGENT_LEASES_LIST_META,
)
async def agent_leases_list(
    owner_id: int | None = None,
    property_id: int | None = None,
    status: LeaseStatus | None = None,
    cursor: str | None = None,
    limit: int = 20,
    include_total: bool = False,
) -> dict[str, Any]:
    """List leases for managed properties.

    Args:
        owner_id: Filter by owner
        property_id: Filter by property
        status: Filter by status (draft, active, expired, terminated)
        cursor: Opaque pagination cursor from a prior response's next_cursor
        limit: Items per page (1-100)
        include_total: Set true to get the count of matching leases
    """
    try:
        from app.mcp.tool_ops import list_leases
        from app.services.pm_authz import get_accessible_owner_ids

        limit = min(max(1, limit), 100)
        filters = {
            "owner_id": owner_id,
            "property_id": property_id,
            "status": status.lower().strip() if status else None,
        }
        cursor_payload = decode_cursor(cursor, filters) if cursor else {}

        async for db in get_db():
            user = await _get_user(db)
            if not user:
                _require_auth(
                    action="agent_leases_list",
                    message="Please log in to list leases.",
                    scope="mcp:read",
                )

            if not _require_agent_or_admin(user):
                return MCPResponse.failure(
                    MCPErrorCode.INSUFFICIENT_PERMISSIONS,
                    "This endpoint is for agents and admins only",
                ).model_dump()

            accessible = await get_accessible_owner_ids(db, actor=user)
            if accessible is not None and owner_id and owner_id not in accessible:
                return MCPResponse.failure(
                    MCPErrorCode.INSUFFICIENT_PERMISSIONS,
                    "You do not have access to this owner's leases",
                ).model_dump()

            result = await list_leases(
                db,
                actor=user,
                owner_id=owner_id,
                property_id=property_id,
                status=status,
                cursor_payload=cursor_payload,
                limit=limit,
                accessible_owner_ids=None if accessible is None else list(accessible),
                filters=filters,
                include_total=include_total,
            )
            if result.get("error"):
                return invalid_input_response(result.get("message", "Invalid filter"))
            return MCPResponse.success(result).model_dump()
    except AuthRequiredError:
        raise
    except BadRequestException as e:
        return invalid_input_response(str(e))
    except Exception as e:
        logger.error("Error in agent.leases.list: %s", e, exc_info=True)
        return internal_error_response(f"Failed to list leases: {str(e)}")
    return {}


@admin_mcp.tool(
    "agent_leases_create",
    annotations={
        "title": "Create Lease",
        "readOnlyHint": False,
        "destructiveHint": False,
        "openWorldHint": False,
        "securitySchemes": MCP_SECURITY_SCHEMES_OAUTH2_ONLY,
    },
)
async def agent_leases_create(
    property_id: int,
    tenant_user_id: int,
    start_date: str,
    end_date: str,
    monthly_rent: float,
    security_deposit: float,
    payment_due_day: int | None = None,
    grace_period_days: int | None = None,
    terms: str | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    """Create a new lease for a property.

    Args:
        property_id: ID of the property
        tenant_user_id: ID of the tenant user
        start_date: Lease start date (ISO-8601)
        end_date: Lease end date (ISO-8601)
        monthly_rent: Monthly rent amount
        security_deposit: Security deposit amount
        payment_due_day: Day of month rent is due (1-28). Default: the managed property's day.
        grace_period_days: Grace period for late payments. Default: the managed property's
            value. 0 means no grace period.
        terms: Lease terms and conditions
        notes: Additional notes
    """
    try:
        from app.models.enums import LeaseStatus

        try:
            start = datetime.fromisoformat(start_date).date()
            end = datetime.fromisoformat(end_date).date()
        except ValueError:
            return invalid_input_response("Dates must be in ISO-8601 format")

        if end <= start:
            return invalid_input_response("End date must be after start date")

        async for db in get_db():
            user = await _get_user(db)
            if not user:
                _require_auth(
                    action="agent_leases_create",
                    message="Please log in to create a lease.",
                    scope="mcp:write",
                )

            if not _require_agent_or_admin(user):
                return MCPResponse.failure(
                    MCPErrorCode.INSUFFICIENT_PERMISSIONS,
                    "This endpoint is for agents and admins only",
                ).model_dump()

            from app.schemas.user import User as UserSchema
            from app.services.pm_authz import assert_can_access_property

            user_schema = UserSchema.model_validate(user)

            # Verify access to property
            try:
                prop = await assert_can_access_property(
                    db, actor=user_schema, property_id=property_id
                )
            except PropertyNotFoundException:
                return not_found_response("Property", property_id)
            except InsufficientPermissionsError:
                return MCPResponse.failure(
                    MCPErrorCode.INSUFFICIENT_PERMISSIONS, "You do not have access to this property"
                ).model_dump()

            # Verify tenant exists
            from app.services.user import get_user_by_id

            tenant = await get_user_by_id(db, tenant_user_id)
            if not tenant:
                return not_found_response("Tenant user", tenant_user_id)

            # Create the lease through the PM service, as the REST route does.
            from app.services.pm_leases import create_lease as create_pm_lease

            lease = await create_pm_lease(
                db,
                actor=user_schema,
                owner_id=prop.owner_id,
                property_id=property_id,
                tenant_user_id=tenant_user_id,
                tenant_name=None,
                tenant_phone=None,
                tenant_email=None,
                status=LeaseStatus.active,
                start_date=start,
                end_date=end,
                monthly_rent=monthly_rent,
                security_deposit=security_deposit,
                payment_due_day=payment_due_day,
                grace_period_days=grace_period_days,
                lease_terms={"terms": terms} if terms else None,
                special_clauses=notes,
            )
            await db.commit()

            return MCPResponse.success(
                {
                    "message": "Lease created successfully",
                    "lease": serialize_lease(lease, user),
                }
            ).model_dump()
    except AuthRequiredError:
        raise
    except BadRequestException as e:
        return invalid_input_response(str(e))
    except ConflictException as e:
        return MCPResponse.failure(MCPErrorCode.CONFLICT, str(e.detail)).model_dump()
    except Exception as e:
        logger.error("Error in agent.leases.create: %s", e, exc_info=True)
        return internal_error_response(f"Failed to create lease: {str(e)}")
    return {}


@admin_mcp.tool(
    "agent_leases_terminate",
    annotations={
        "title": "Terminate Lease",
        "readOnlyHint": False,
        "destructiveHint": True,
        "openWorldHint": False,
        "securitySchemes": MCP_SECURITY_SCHEMES_OAUTH2_ONLY,
    },
)
async def agent_leases_terminate(
    lease_id: int,
    reason: str,
    termination_date: str | None = None,
) -> dict[str, Any]:
    """Terminate an active lease.

    Args:
        lease_id: ID of the lease
        reason: Reason for termination
        termination_date: Termination date (ISO-8601, defaults to today)
    """
    try:
        from app.schemas.user import User as UserSchema
        from app.services.pm_leases import terminate_lease

        term_date = utc_now().date()
        if termination_date:
            try:
                term_date = datetime.fromisoformat(termination_date).date()
            except ValueError:
                return invalid_input_response("termination_date must be in ISO-8601 format")

        async for db in get_db():
            user = await _get_user(db)
            if not user:
                _require_auth(
                    action="agent_leases_terminate",
                    message="Please log in to terminate a lease.",
                    scope="mcp:write",
                )

            if not _require_agent_or_admin(user):
                return MCPResponse.failure(
                    MCPErrorCode.INSUFFICIENT_PERMISSIONS,
                    "This endpoint is for agents and admins only",
                ).model_dump()

            user_schema = UserSchema.model_validate(user)

            try:
                await terminate_lease(
                    db,
                    actor=user_schema,
                    lease_id=lease_id,
                    termination_date=term_date,
                    reason=reason,
                )
            except NotFoundException:
                return not_found_response("Lease", lease_id)
            except InsufficientPermissionsError:
                return MCPResponse.failure(
                    MCPErrorCode.INSUFFICIENT_PERMISSIONS, "You do not have access to this lease"
                ).model_dump()
            except BadRequestException as e:
                return MCPResponse.failure(
                    MCPErrorCode.OPERATION_FAILED,
                    str(e.detail) if hasattr(e, "detail") else str(e),
                ).model_dump()

            await db.commit()

            return MCPResponse.success(
                {
                    "message": "Lease terminated successfully",
                    "lease_id": lease_id,
                    "termination_date": term_date.isoformat(),
                }
            ).model_dump()
    except AuthRequiredError:
        raise
    except BadRequestException as e:
        return invalid_input_response(str(e))
    except Exception as e:
        logger.error("Error in agent.leases.terminate: %s", e, exc_info=True)
        return internal_error_response(f"Failed to terminate lease: {str(e)}")
    return {}
