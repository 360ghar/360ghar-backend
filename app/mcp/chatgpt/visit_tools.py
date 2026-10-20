"""
Visit tools for ChatGPT App.

These tools enable property visit scheduling and management:
- Schedule a property visit
- List user's visits
- Get visit details
- Cancel a visit
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from app.core.database import AsyncSessionLocal
from app.core.logging import get_logger
from app.mcp.apps_sdk import (
    MCP_SECURITY_SCHEMES_OAUTH2_ONLY,
    AuthRequiredError,
    build_widget_tool_meta,
)
from app.mcp.chatgpt import get_widget_for_tool
from app.mcp.chatgpt.response_formatter import (
    format_auth_required_response,
    format_chatgpt_response,
    format_visit_summary,
    format_visits_list_summary,
)

# Import the user MCP server to register tools
from app.mcp.user.server import user_mcp
from app.mcp.utils import get_user_from_mcp_context, utc_iso
from app.models.enums import VisitStatus
from app.schemas.pagination import decode_cursor, encode_cursor
from app.schemas.visit import VisitCreate
from app.services.visit import get_user_visits

logger = get_logger(__name__)

# ChatGPT tool metadata for widget linkage
VISIT_SCHEDULER_META = build_widget_tool_meta(
    widget_uri="ui://widget/visitschedulerwidget.html",
    invoking="Scheduling your visit...",
    invoked="Visit scheduled",
)

VISIT_LIST_META = build_widget_tool_meta(
    widget_uri="ui://widget/visitlistwidget.html",
    invoking="Loading your visits...",
    invoked="Visits loaded",
)


async def _get_optional_user(db):
    """Get user if authenticated, None for guests."""
    return await get_user_from_mcp_context(db)


def _serialize_visit(visit) -> dict[str, Any]:
    """Serialize a visit object to a dictionary."""
    property_data = None
    if visit.property:
        property_data = {
            "id": visit.property.id,
            "title": visit.property.title,
            "locality": visit.property.locality,
            "city": visit.property.city,
            "main_image_url": visit.property.images[0].image_url if visit.property.images else None,
        }

    return {
        "id": visit.id,
        "property_id": visit.property_id,
        "property": property_data,
        "scheduled_date": utc_iso(visit.scheduled_date),
        "status": visit.status.value if hasattr(visit.status, "value") else visit.status,
        "notes": visit.notes,
        "created_at": utc_iso(visit.created_at),
    }


# ============================================================================
# Visit Tools (All require authentication)
# ============================================================================


# Upcoming visits are the statuses that have not ended yet.
_UPCOMING_STATUSES = {VisitStatus.requested, VisitStatus.confirmed, VisitStatus.reschedule_suggested}


# Accepted visits_list values: the stored VisitStatus values.
VisitStatusFilter = Literal[
    "requested",
    "confirmed",
    "completed",
    "cancelled",
    "reschedule_suggested",
]


def _visit_status_filter(status: str | None) -> VisitStatus | None:
    """Resolve a stored status value (``requested``). Unknown values give None."""
    if not status:
        return None
    try:
        return VisitStatus(status.strip())
    except ValueError:
        return None


async def _visit_status_counts(db: Any, user_id: int) -> dict[str, int]:
    """Per-status counts of every visit the user is party to, from one grouped query."""
    from sqlalchemy import func, or_, select

    from app.models.properties import Visit

    grouped = (
        await db.execute(
            select(Visit.status, func.count())
            .where(or_(Visit.user_id == user_id, Visit.counterparty_user_id == user_id))
            .group_by(Visit.status)
        )
    ).all()
    by_value: dict[str, int] = {}
    for status, count in grouped:
        value = str(getattr(status, "value", status))
        by_value[value] = by_value.get(value, 0) + int(count)
    upcoming = sum(by_value.get(member.value, 0) for member in _UPCOMING_STATUSES)
    return {
        "total": sum(by_value.values()),
        "upcoming": upcoming,
        "completed": by_value.get(VisitStatus.completed.value, 0),
        "cancelled": by_value.get(VisitStatus.cancelled.value, 0),
        "requested": by_value.get(VisitStatus.requested.value, 0),
        "confirmed": by_value.get(VisitStatus.confirmed.value, 0),
        "reschedule_suggested": by_value.get(VisitStatus.reschedule_suggested.value, 0),
    }


@user_mcp.tool(
    "visits_schedule",
    annotations={
        "title": "Schedule Property Visit",
        "readOnlyHint": False,
        "openWorldHint": False,
        "destructiveHint": False,
        "securitySchemes": MCP_SECURITY_SCHEMES_OAUTH2_ONLY,
    },
    meta=VISIT_SCHEDULER_META,
)
async def visits_schedule(
    property_id: int,
    scheduled_date: str,
    notes: str | None = None,
) -> dict[str, Any]:
    """Schedule a property visit.

    Schedule a visit to view a property. The scheduled date must be in the future.

    This tool requires authentication.

    Args:
        property_id: Property ID to schedule visit for
        scheduled_date: Visit date and time in ISO 8601 format with a UTC offset (e.g., "2025-02-15T14:00:00+05:30")
        notes: Optional notes for the visit (e.g., "Please call before arrival")

    Returns:
        Created visit details.
    """
    try:
        from app.services.property import get_property
        from app.services.visit import create_visit

        async with AsyncSessionLocal() as db:
            user = await _get_optional_user(db)

            if not user:
                return format_auth_required_response(
                    action="schedule_visit",
                    message="To schedule a property visit, please log in to your 360Ghar account.",
                    context={"property_id": property_id, "scheduled_date": scheduled_date},
                )

            # Parse scheduled date
            try:
                parsed_date = datetime.fromisoformat(scheduled_date.replace("Z", "+00:00"))
            except ValueError as e:
                return format_chatgpt_response(
                    data={"error": True, "code": "INVALID_DATE", "message": str(e)},
                    content_summary="Invalid date format. Please use ISO 8601 format like '2025-02-15T14:00:00+05:30'.",
                    widget_uri=get_widget_for_tool("visits_schedule"),
                )
            if parsed_date.tzinfo is None:
                # A naive time is local time for the user, not UTC. Ask for the offset.
                return format_chatgpt_response(
                    data={
                        "error": True,
                        "code": "INVALID_DATE",
                        "message": "scheduled_date must include a UTC offset.",
                    },
                    content_summary="The visit time needs a UTC offset, for example '2025-02-15T14:00:00+05:30'.",
                    widget_uri=get_widget_for_tool("visits_schedule"),
                )

            # Check if date is in the future
            now = datetime.now(timezone.utc)
            if parsed_date <= now:
                return format_chatgpt_response(
                    data={"error": True, "code": "PAST_DATE"},
                    content_summary="The scheduled date must be in the future. Please choose a future date and time.",
                    widget_uri=get_widget_for_tool("visits_schedule"),
                )

            # Verify property exists
            try:
                await get_property(db, property_id)
            except Exception:
                return format_chatgpt_response(
                    data={"error": True, "code": "NOT_FOUND", "property_id": property_id},
                    content_summary=f"Property with ID {property_id} was not found.",
                    widget_uri=get_widget_for_tool("visits_schedule"),
                )

            # Create visit
            visit_data = VisitCreate(
                property_id=property_id,
                scheduled_date=parsed_date,
                special_requirements=notes,
            )
            visit = await create_visit(db, user.id, visit_data)
            await db.commit()

            visit_dict = _serialize_visit(visit)

            return format_chatgpt_response(
                data={"visit": visit_dict},
                content_summary=format_visit_summary(visit_dict),
                widget_uri=get_widget_for_tool("visits_schedule"),
            )

    except AuthRequiredError:
        raise
    except Exception as e:
        logger.error("Error in visits.schedule: %s", e, exc_info=True)
        return format_chatgpt_response(
            data={"error": True, "message": str(e)},
            content_summary=f"Sorry, there was an error scheduling the visit: {str(e)}",
            widget_uri=get_widget_for_tool("visits_schedule"),
        )


@user_mcp.tool(
    "visits_list",
    annotations={
        "title": "List My Visits",
        "readOnlyHint": True,
        "openWorldHint": False,
        "destructiveHint": False,
        "securitySchemes": MCP_SECURITY_SCHEMES_OAUTH2_ONLY,
    },
    meta=VISIT_LIST_META,
)
async def visits_list(
    status: VisitStatusFilter | None = None,
    cursor: str | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    """List the user's property visits.

    Retrieves all visits scheduled by the user, with optional status filtering.

    This tool requires authentication.

    Args:
        status: Filter by status (requested, confirmed, completed, cancelled, reschedule_suggested)
        cursor: Opaque pagination cursor from a prior response's next_cursor
        limit: Results per page (max 50)

    Returns:
        List of visits with statistics.
    """
    try:
        limit = min(max(1, limit), 50)
        status_key = _visit_status_filter(status)
        filters = {"status": status_key.value if status_key is not None else None}
        cursor_payload = decode_cursor(cursor, filters) if cursor else {}

        async with AsyncSessionLocal() as db:
            user = await _get_optional_user(db)

            if not user:
                return format_auth_required_response(
                    action="list_visits",
                    message="To view your property visits, please log in to your 360Ghar account.",
                )

            # Get user's visits (paginated via cursor). Status filtering is
            # applied server-side by get_user_visits, so the page and the
            # reported total are accurate for the requested status.
            status_enum = _visit_status_filter(status)
            if status and status_enum is None:
                valid = sorted(m.value for m in VisitStatus)
                return format_chatgpt_response(
                    data={
                        "error": True,
                        "code": "INVALID_STATUS",
                        "message": f"Invalid status: {status}. Valid values: {valid}",
                    },
                    content_summary=f"Invalid visit status '{status}'. Valid values are: {', '.join(valid)}.",
                    widget_uri=get_widget_for_tool("visits_list"),
                )
            rows, next_payload, total_count = await get_user_visits(
                db,
                user.id,
                cursor_payload=cursor_payload,
                limit=limit,
                with_total=True,
                status=status_enum,
            )

            all_visits = rows

            # Per-status counts of every visit the user is party to (not the page).
            counts = await _visit_status_counts(db, user.id)

            # Serialize visits
            visits = [_serialize_visit(v) for v in all_visits]

            return format_chatgpt_response(
                data={
                    "items": visits,
                    "next_cursor": encode_cursor(next_payload, filters) if next_payload else None,
                    "has_more": next_payload is not None,
                    "limit": limit,
                    "counts": counts,
                },
                content_summary=format_visits_list_summary(visits, counts),
                widget_uri=get_widget_for_tool("visits_list"),
            )

    except AuthRequiredError:
        raise
    except Exception as e:
        logger.error("Error in visits.list: %s", e, exc_info=True)
        return format_chatgpt_response(
            data={"error": True, "message": str(e)},
            content_summary=f"Sorry, there was an error loading your visits: {str(e)}",
            widget_uri=get_widget_for_tool("visits_list"),
        )


@user_mcp.tool(
    "visits_get",
    annotations={
        "title": "Get Visit Details",
        "readOnlyHint": True,
        "openWorldHint": False,
        "destructiveHint": False,
        "securitySchemes": MCP_SECURITY_SCHEMES_OAUTH2_ONLY,
    },
    meta=VISIT_LIST_META,
)
async def visits_get(
    visit_id: int,
) -> dict[str, Any]:
    """Get details of a specific visit.

    Retrieves full details of a property visit including property information.

    This tool requires authentication.

    Args:
        visit_id: Visit ID to retrieve

    Returns:
        Visit details.
    """
    try:
        from app.services.visit import get_visit

        async with AsyncSessionLocal() as db:
            user = await _get_optional_user(db)

            if not user:
                return format_auth_required_response(
                    action="get_visit",
                    message="To view visit details, please log in to your 360Ghar account.",
                )

            # Get visit
            visit = await get_visit(db, visit_id)

            if not visit:
                return format_chatgpt_response(
                    data={"error": True, "code": "NOT_FOUND", "visit_id": visit_id},
                    content_summary=f"Visit with ID {visit_id} was not found.",
                    widget_uri=get_widget_for_tool("visits_get"),
                )

            # Check ownership
            if visit.user_id != user.id:
                return format_chatgpt_response(
                    data={"error": True, "code": "FORBIDDEN"},
                    content_summary="You don't have permission to view this visit.",
                    widget_uri=get_widget_for_tool("visits_get"),
                )

            visit_dict = _serialize_visit(visit)

            return format_chatgpt_response(
                data={"visit": visit_dict},
                content_summary=format_visit_summary(visit_dict),
                widget_uri=get_widget_for_tool("visits_get"),
            )

    except AuthRequiredError:
        raise
    except Exception as e:
        logger.error("Error in visits.get: %s", e, exc_info=True)
        return format_chatgpt_response(
            data={"error": True, "message": str(e)},
            content_summary=f"Sorry, there was an error loading the visit: {str(e)}",
            widget_uri=get_widget_for_tool("visits_get"),
        )


@user_mcp.tool(
    "visits_cancel",
    annotations={
        "title": "Cancel Visit",
        "readOnlyHint": False,
        "openWorldHint": False,
        "destructiveHint": True,
        "securitySchemes": MCP_SECURITY_SCHEMES_OAUTH2_ONLY,
    },
    meta={
        "openai/toolInvocation/invoking": "Cancelling visit...",
        "openai/toolInvocation/invoked": "Visit cancelled",
    },
)
async def visits_cancel(
    visit_id: int,
    reason: str | None = None,
) -> dict[str, Any]:
    """Cancel a scheduled property visit.

    Cancels a visit that has not yet been completed. Only upcoming visits can be cancelled.

    This tool requires authentication.

    Args:
        visit_id: Visit ID to cancel
        reason: Optional reason for cancellation

    Returns:
        Confirmation of cancellation.
    """
    try:
        from app.services.visit import cancel_visit, get_visit

        async with AsyncSessionLocal() as db:
            user = await _get_optional_user(db)

            if not user:
                return format_auth_required_response(
                    action="cancel_visit",
                    message="To cancel a visit, please log in to your 360Ghar account.",
                )

            # Get visit
            visit = await get_visit(db, visit_id)

            if not visit:
                return format_chatgpt_response(
                    data={"error": True, "code": "NOT_FOUND", "visit_id": visit_id},
                    content_summary=f"Visit with ID {visit_id} was not found.",
                    widget_uri=get_widget_for_tool("visits_cancel"),
                )

            # Check ownership
            if visit.user_id != user.id:
                return format_chatgpt_response(
                    data={"error": True, "code": "FORBIDDEN"},
                    content_summary="You don't have permission to cancel this visit.",
                    widget_uri=get_widget_for_tool("visits_cancel"),
                )

            # Check if already cancelled or completed
            status = visit.status.value if hasattr(visit.status, "value") else visit.status
            if status in ("cancelled", "completed"):
                return format_chatgpt_response(
                    data={"error": True, "code": "INVALID_STATUS", "current_status": status},
                    content_summary=f"This visit has already been {status} and cannot be cancelled.",
                    widget_uri=get_widget_for_tool("visits_cancel"),
                )

            # Cancel visit
            await cancel_visit(db, visit_id, reason or "")
            await db.commit()

            return format_chatgpt_response(
                data={"visit_id": visit_id, "status": "cancelled"},
                content_summary=f"Your visit has been cancelled.{' Reason: ' + reason if reason else ''}",
                widget_uri=get_widget_for_tool("visits_cancel"),
            )

    except AuthRequiredError:
        raise
    except Exception as e:
        logger.error("Error in visits.cancel: %s", e, exc_info=True)
        return format_chatgpt_response(
            data={"error": True, "message": str(e)},
            content_summary=f"Sorry, there was an error cancelling the visit: {str(e)}",
            widget_uri=get_widget_for_tool("visits_cancel"),
        )
