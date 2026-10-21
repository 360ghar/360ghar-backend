from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.api_v1.dependencies.auth import (
    get_current_active_user,
    get_current_cached_active_user,
)
from app.api.api_v1.endpoints.properties import build_property_filters
from app.core.database import get_db
from app.core.db_resilience import raise_read_service_unavailable
from app.core.exceptions import ValidationException
from app.core.logging import get_logger
from app.schemas.pagination import CursorPage, CursorParams, build_cursor_page
from app.schemas.property import (
    Property,
    UnifiedPropertyFilter,
)
from app.schemas.swipe import (
    BatchRemoveRequest,
    BatchRemoveResult,
    SwipeCreate,
    SwipeOut,
    SwipeStats,
)
from app.schemas.user import User as UserSchema
from app.services.auth_user_cache import AuthUserSnapshot
from app.services.property import attach_owner_agents
from app.services.swipe import (
    batch_unswipe,
    get_swipe_history,
    get_swipe_stats,
    toggle_swipe,
    undo_last_swipe,
    upsert_property_swipe,
)
from app.services.visibility import mask_owner_contacts

logger = get_logger(__name__)

router = APIRouter()


@router.post(
    "",
    response_model=SwipeOut,
    summary="Swipe property",
    responses={
        201: {"description": "Swipe created", "model": SwipeOut},
        200: {"description": "Swipe updated", "model": SwipeOut},
    },
)
async def swipe_property(
    swipe: SwipeCreate,
    response: Response,
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Record a property swipe (like or pass). Returns the stored swipe.

    Returns 201 when the swipe is new and 200 when it replaces an earlier swipe.
    """
    row, created = await upsert_property_swipe(
        db, current_user.id, swipe.property_id, swipe.is_liked
    )
    response.status_code = 201 if created else 200
    logger.debug(
        "Property swipe recorded",
        extra={
            "user_id": current_user.id,
            "property_id": swipe.property_id,
            "action": "liked" if swipe.is_liked else "passed",
        },
    )
    return SwipeOut(id=row.id, property_id=swipe.property_id, is_liked=row.is_liked)


@router.get("", response_model=CursorPage[Property], summary="List swipe history")
async def get_user_swipe_history(
    # Every property filter key of GET /properties, from the shared builder.
    filters: UnifiedPropertyFilter = Depends(build_property_filters),
    # Swipe-specific filter
    is_liked: bool | None = Query(None, description="Filter by liked (true) or disliked (false)"),
    # Cursor pagination
    page: CursorParams = Depends(),
    current_user: AuthUserSnapshot = Depends(get_current_cached_active_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Get user's swipe history with the same filters as GET /properties.

    Swipe-only filter: `is_liked`. `semantic_search` and `exclude_swiped` do not apply
    to the swipe feed and give 422 when true.
    Cursor-based pagination, bound to the filters above.
    """
    if filters.semantic_search or filters.exclude_swiped:
        raise ValidationException(
            detail="semantic_search and exclude_swiped do not apply to the swipe feed"
        )
    filter_binding = {**filters.model_dump(mode="json", exclude_none=True), "is_liked": is_liked}
    cursor_payload = page.decoded(filter_binding)

    # Log search request
    logger.info(
        "Swipe history search request - user: %s, filters: %s",
        current_user.id,
        len(
            [
                f
                for f in [
                    filters.search_query,
                    filters.latitude,
                    filters.longitude,
                    filters.property_type,
                    filters.city,
                ]
                if f
            ]
        ),
    )

    try:
        swipes, next_payload, total = await get_swipe_history(
            db,
            current_user.id,
            filters,
            cursor_payload=cursor_payload,
            limit=page.limit,
            is_liked=is_liked,
            with_total=page.include_total,
        )

        logger.info("Swipe history search completed - returning %s properties", len(swipes))

        # Extract properties from swipe objects
        props = []
        for swipe in swipes:
            if swipe.property:
                swipe.property.liked = swipe.is_liked
                props.append(Property.model_validate(swipe.property))

        await attach_owner_agents(db, props)
        return build_cursor_page(
            mask_owner_contacts(props, current_user),
            limit=page.limit,
            next_payload=next_payload,
            total=total,
            filters=filter_binding,
        )
    except Exception as e:
        raise_read_service_unavailable(
            e,
            endpoint="swipe_history",
            detail="Swipe history is temporarily unavailable. Please retry shortly.",
            extra={"user": current_user.id},
        )
        logger.error("Swipe history search failed for user %s: %s", current_user.id, e)
        raise


@router.delete("/undo", status_code=204, summary="Undo last swipe")
async def undo_last_swipe_endpoint(
    current_user: UserSchema = Depends(get_current_active_user), db: AsyncSession = Depends(get_db)
):
    """Undo the last swipe for the user. Returns 204, or 404 when there is nothing to undo."""
    undone_swipe = await undo_last_swipe(db, current_user.id)

    if not undone_swipe:
        raise HTTPException(status_code=404, detail="No swipes to undo")

    return Response(status_code=204)


@router.put("/{swipe_id}/toggle", response_model=SwipeOut, summary="Toggle swipe like")
async def toggle_swipe_like(
    swipe_id: int,
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Toggle the like status of one of the user's swipes. Other users' swipes return 404."""
    result = await toggle_swipe(db, swipe_id, current_user.id)

    if not result:
        raise HTTPException(status_code=404, detail="Swipe not found or does not belong to user")
    return SwipeOut(
        id=result["id"], property_id=result["property_id"], is_liked=result["new_status"]
    )


@router.get("/stats", response_model=SwipeStats, summary="Get swipe statistics")
async def get_user_swipe_statistics(
    current_user: AuthUserSnapshot = Depends(get_current_cached_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Get user's swipe statistics"""
    try:
        return SwipeStats(**await get_swipe_stats(db, current_user.id))
    except Exception as exc:
        raise_read_service_unavailable(
            exc,
            endpoint="swipe_stats",
            detail="Swipe statistics are temporarily unavailable. Please retry shortly.",
            extra={"user": current_user.id},
        )
        raise


@router.post("/batch-remove", response_model=BatchRemoveResult, summary="Batch remove swipes")
async def batch_remove_swipes(
    payload: BatchRemoveRequest,
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Remove the user's swipes for many properties in one request.

    Lists the requested property ids that had no swipe to remove.
    """
    removed = await batch_unswipe(db, current_user.id, payload.property_ids)
    removed_set = set(removed)
    requested = list(dict.fromkeys(payload.property_ids))
    return BatchRemoveResult(
        removed_count=len(removed),
        failed_property_ids=[pid for pid in requested if pid not in removed_set],
    )
