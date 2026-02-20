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
from typing import Any, Dict, Optional

from app.core.database import AsyncSessionLocal
from app.core.logging import get_logger
from app.mcp.apps_sdk import AuthRequiredError, MCP_SECURITY_SCHEMES_MIXED, build_widget_tool_meta
from app.mcp.chatgpt.response_formatter import (
    format_chatgpt_response,
    format_auth_required_response,
    format_visit_summary,
    format_visits_list_summary,
)
from app.mcp.utils import get_user_from_mcp_context
from app.schemas.visit import VisitCreate

# Import the user MCP server to register tools
from app.mcp.user_server import user_mcp

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


def _serialize_visit(visit) -> Dict[str, Any]:
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
        "scheduled_date": visit.scheduled_date.isoformat() if visit.scheduled_date else None,
        "status": visit.status.value if hasattr(visit.status, "value") else visit.status,
        "notes": visit.notes,
        "created_at": visit.created_at.isoformat() if visit.created_at else None,
    }


# ============================================================================
# Visit Tools (All require authentication)
# ============================================================================


@user_mcp.tool(
    "visits_schedule",
    annotations={
        "title": "Schedule Property Visit",
        "readOnlyHint": False,
        "securitySchemes": MCP_SECURITY_SCHEMES_MIXED,
    },
    meta=VISIT_SCHEDULER_META,
)
async def visits_schedule(
    property_id: int,
    scheduled_date: str,
    notes: Optional[str] = None,
) -> Dict[str, Any]:
    """Schedule a property visit.

    Schedule a visit to view a property. The scheduled date must be in the future.

    This tool requires authentication.

    Args:
        property_id: Property ID to schedule visit for
        scheduled_date: Visit date and time in ISO 8601 format (e.g., "2025-02-15T14:00:00")
        notes: Optional notes for the visit (e.g., "Please call before arrival")

    Returns:
        Created visit details.
    """
    try:
        from app.services.visit import create_visit
        from app.services.property import get_property

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
                if parsed_date.tzinfo is None:
                    parsed_date = parsed_date.replace(tzinfo=timezone.utc)
            except ValueError as e:
                return format_chatgpt_response(
                    data={"error": True, "code": "INVALID_DATE", "message": str(e)},
                    content_summary="Invalid date format. Please use ISO 8601 format like '2025-02-15T14:00:00'.",
                )

            # Check if date is in the future
            now = datetime.now(timezone.utc)
            if parsed_date <= now:
                return format_chatgpt_response(
                    data={"error": True, "code": "PAST_DATE"},
                    content_summary="The scheduled date must be in the future. Please choose a future date and time.",
                )

            # Verify property exists
            try:
                await get_property(db, property_id)
            except Exception:
                return format_chatgpt_response(
                    data={"error": True, "code": "NOT_FOUND", "property_id": property_id},
                    content_summary=f"Property with ID {property_id} was not found.",
                )

            # Create visit
            visit_data = VisitCreate(
                property_id=property_id,
                scheduled_date=parsed_date,
                notes=notes,
            )
            visit = await create_visit(db, user.id, visit_data)
            await db.commit()

            visit_dict = _serialize_visit(visit)

            return format_chatgpt_response(
                data={"visit": visit_dict},
                content_summary=format_visit_summary(visit_dict),
            )

    except AuthRequiredError:
        raise
    except Exception as e:
        logger.error(f"Error in visits.schedule: {e}", exc_info=True)
        return format_chatgpt_response(
            data={"error": True, "message": str(e)},
            content_summary=f"Sorry, there was an error scheduling the visit: {str(e)}",
        )


@user_mcp.tool(
    "visits_list",
    annotations={
        "title": "List My Visits",
        "readOnlyHint": True,
        "securitySchemes": MCP_SECURITY_SCHEMES_MIXED,
    },
    meta=VISIT_LIST_META,
)
async def visits_list(
    status: Optional[str] = None,
    page: int = 1,
    limit: int = 20,
) -> Dict[str, Any]:
    """List the user's property visits.

    Retrieves all visits scheduled by the user, with optional status filtering.

    This tool requires authentication.

    Args:
        status: Filter by status (scheduled, confirmed, completed, cancelled, rescheduled)
        page: Page number for pagination
        limit: Results per page (max 50)

    Returns:
        List of visits with statistics.
    """
    try:
        from app.services.visit import get_user_visits

        limit = min(max(1, limit), 50)
        page = max(1, page)

        async with AsyncSessionLocal() as db:
            user = await _get_optional_user(db)

            if not user:
                return format_auth_required_response(
                    action="list_visits",
                    message="To view your property visits, please log in to your 360Ghar account.",
                )

            # Get user's visits
            result = await get_user_visits(db, user.id)

            all_visits = result.get("visits", [])
            counts = {
                "total": result.get("total", 0),
                "upcoming": result.get("upcoming", 0),
                "completed": result.get("completed", 0),
                "cancelled": result.get("cancelled", 0),
            }

            # Filter by status if provided
            if status:
                all_visits = [v for v in all_visits if (v.status.value if hasattr(v.status, "value") else v.status) == status]

            # Paginate
            total = len(all_visits)
            start = (page - 1) * limit
            end = start + limit
            paginated_visits = all_visits[start:end]

            # Serialize visits
            visits = [_serialize_visit(v) for v in paginated_visits]

            return format_chatgpt_response(
                data={
                    "visits": visits,
                    "total": total,
                    "page": page,
                    "limit": limit,
                    "total_pages": (total + limit - 1) // limit if total else 0,
                    "counts": counts,
                },
                content_summary=format_visits_list_summary(visits, counts),
            )

    except AuthRequiredError:
        raise
    except Exception as e:
        logger.error(f"Error in visits.list: {e}", exc_info=True)
        return format_chatgpt_response(
            data={"error": True, "message": str(e)},
            content_summary=f"Sorry, there was an error loading your visits: {str(e)}",
        )


@user_mcp.tool(
    "visits_get",
    annotations={
        "title": "Get Visit Details",
        "readOnlyHint": True,
        "securitySchemes": MCP_SECURITY_SCHEMES_MIXED,
    },
    meta=VISIT_LIST_META,
)
async def visits_get(
    visit_id: int,
) -> Dict[str, Any]:
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
                )

            # Check ownership
            if visit.user_id != user.id:
                return format_chatgpt_response(
                    data={"error": True, "code": "FORBIDDEN"},
                    content_summary="You don't have permission to view this visit.",
                )

            visit_dict = _serialize_visit(visit)

            return format_chatgpt_response(
                data={"visit": visit_dict},
                content_summary=format_visit_summary(visit_dict),
            )

    except AuthRequiredError:
        raise
    except Exception as e:
        logger.error(f"Error in visits.get: {e}", exc_info=True)
        return format_chatgpt_response(
            data={"error": True, "message": str(e)},
            content_summary=f"Sorry, there was an error loading the visit: {str(e)}",
        )


@user_mcp.tool(
    "visits_cancel",
    annotations={
        "title": "Cancel Visit",
        "readOnlyHint": False,
        "destructiveHint": True,
        "securitySchemes": MCP_SECURITY_SCHEMES_MIXED,
    },
    meta={
        "openai/toolInvocation/invoking": "Cancelling visit...",
        "openai/toolInvocation/invoked": "Visit cancelled",
    },
)
async def visits_cancel(
    visit_id: int,
    reason: Optional[str] = None,
) -> Dict[str, Any]:
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
        from app.services.visit import get_visit, cancel_visit

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
                )

            # Check ownership
            if visit.user_id != user.id:
                return format_chatgpt_response(
                    data={"error": True, "code": "FORBIDDEN"},
                    content_summary="You don't have permission to cancel this visit.",
                )

            # Check if already cancelled or completed
            status = visit.status.value if hasattr(visit.status, "value") else visit.status
            if status in ("cancelled", "completed"):
                return format_chatgpt_response(
                    data={"error": True, "code": "INVALID_STATUS", "current_status": status},
                    content_summary=f"This visit has already been {status} and cannot be cancelled.",
                )

            # Cancel visit
            await cancel_visit(db, visit_id, reason)
            await db.commit()

            return format_chatgpt_response(
                data={"success": True, "visit_id": visit_id, "status": "cancelled"},
                content_summary=f"Your visit has been cancelled.{' Reason: ' + reason if reason else ''}",
            )

    except AuthRequiredError:
        raise
    except Exception as e:
        logger.error(f"Error in visits.cancel: {e}", exc_info=True)
        return format_chatgpt_response(
            data={"error": True, "message": str(e)},
            content_summary=f"Sorry, there was an error cancelling the visit: {str(e)}",
        )
