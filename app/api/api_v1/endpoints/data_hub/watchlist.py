"""Project watchlist endpoints for the current user.

Business logic lives in ``app/services/data_hub/watchlist.py`` and is imported
inside each endpoint, so this module imports even when the service lands later.
The endpoints own input validation: a project id that does not exist is a 404
before the service is called.

Gated on ``settings.HRERA_DATA_ENABLED`` like the rest of the HRERA surface.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.api_v1.dependencies.auth import get_current_active_user
from app.core.database import get_db
from app.models.data_hub import ProjectWatchlist, ReraProject, ReraProjectProfile
from app.schemas.data_hub import (
    ProjectSummaryResponse,
    WatchlistItemCreate,
    WatchlistItemResponse,
)
from app.schemas.user import User as UserSchema
from app.services.data_hub.provenance import get_public_provenance_summaries

from .projects import execute_safe, project_summary
from .rera import _require_hrera_enabled

router = APIRouter()

# A watchlist is bounded per user. The public contract types it as a plain list,
# so it carries a hard cap instead of a cursor.
WATCHLIST_LIMIT = 200


async def _projects_by_id(
    db: AsyncSession, project_ids: set[int]
) -> dict[int, ProjectSummaryResponse]:
    """Load the project cards for a set of ids in one query plus one provenance query."""
    if not project_ids:
        return {}
    rows = await execute_safe(
        db,
        select(ReraProject, ReraProjectProfile)
        .outerjoin(ReraProjectProfile, ReraProjectProfile.rera_project_id == ReraProject.id)
        .where(ReraProject.id.in_(project_ids), ReraProject.slug.isnot(None)),
    )
    summaries = await get_public_provenance_summaries(
        db, "rera_project", [project for project, _profile in rows]
    )
    return {
        project.id: project_summary(project, profile, summaries.get(project.id))
        for project, profile in rows
    }


def _item_response(
    row: ProjectWatchlist, project: ProjectSummaryResponse | None
) -> WatchlistItemResponse:
    return WatchlistItemResponse(
        id=row.id,
        project_id=row.rera_project_id,
        notes=row.notes,
        alert_prefs=row.alert_prefs,
        created_at=row.created_at,
        project=project,
    )


@router.post(
    "/watchlist",
    response_model=WatchlistItemResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add a project to the watchlist",
    responses={
        503: {"description": "HRERA surface turned off by configuration"},
        409: {"description": "The per-user watchlist ceiling is reached"},
    },
)
async def add_watchlist_item(
    payload: WatchlistItemCreate,
    db: AsyncSession = Depends(get_db),
    current_user: UserSchema = Depends(get_current_active_user),
):
    """Watch a project. Idempotent: watching twice returns the existing row.

    A project with no slug is refused along with an unknown one. Every other
    project route filters on ``slug IS NOT NULL`` because a slug is the public URL
    key, and a watched row exists to link to that page — accepting one here would
    store a row the list can only render as ``#<id>`` with no name, link or
    figures. Refusing it keeps the watchlist free of entries nothing can display.
    """
    _require_hrera_enabled()
    from app.services.data_hub.watchlist import add_to_watchlist

    project_id = await execute_safe(
        db,
        select(ReraProject.id).where(
            ReraProject.id == payload.project_id,
            ReraProject.slug.isnot(None),
        ),
        mode="one_or_none",
    )
    if project_id is None:
        raise HTTPException(status_code=404, detail="Project not found")

    try:
        row = await add_to_watchlist(
            db,
            user_id=current_user.id,
            project_id=payload.project_id,
            notes=payload.notes,
            alert_prefs=payload.alert_prefs,
        )
    except ValueError as exc:
        # The service raises WatchlistLimitExceeded (a ValueError) for a new pair
        # once the per-user ceiling is reached. That is a conflict, not a server fault.
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    # The service only flushes, so a server-generated created_at may still be
    # unloaded. Reload the row before serializing it.
    await db.refresh(row)
    projects = await _projects_by_id(db, {payload.project_id})
    return _item_response(row, projects.get(payload.project_id))


@router.get(
    "/watchlist",
    response_model=list[WatchlistItemResponse],
    summary="List my watchlist",
    responses={503: {"description": "HRERA surface turned off by configuration"}},
)
async def list_watchlist_items(
    db: AsyncSession = Depends(get_db),
    current_user: UserSchema = Depends(get_current_active_user),
):
    """List the current user's watched projects, newest first."""
    _require_hrera_enabled()
    from app.services.data_hub.watchlist import list_watchlist

    rows = await list_watchlist(db, user_id=current_user.id)
    rows = rows[:WATCHLIST_LIMIT]
    projects = await _projects_by_id(db, {row.rera_project_id for row in rows})
    return [_item_response(row, projects.get(row.rera_project_id)) for row in rows]


@router.delete(
    "/watchlist/{project_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove a project from the watchlist",
    responses={503: {"description": "HRERA surface turned off by configuration"}},
)
async def delete_watchlist_item(
    project_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: UserSchema = Depends(get_current_active_user),
):
    """Stop watching a project. 404 when it was not watched."""
    _require_hrera_enabled()
    from app.services.data_hub.watchlist import remove_from_watchlist

    removed = await remove_from_watchlist(
        db, user_id=current_user.id, project_id=project_id
    )
    if not removed:
        raise HTTPException(status_code=404, detail="Project is not on the watchlist")
    return None
