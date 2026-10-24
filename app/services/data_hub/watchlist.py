"""Watchlist service for RERA projects.

A watchlist row is a user's saved project plus the alert switches they chose for
it (``notes`` and ``alert_prefs``). The functions here own no transaction: the
caller opens the session, calls one of these, and commits. They only ``flush`` so
the caller sees generated ids inside its own unit of work.

Alert switches live in ``ProjectWatchlist.alert_prefs``. The default is opt-in:
a key that is absent means the user wants that alert, and only a key explicitly
set to ``False`` turns it off. See ``watchlist_alerts`` for the keys.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import relationship, selectinload

from app.models.data_hub import ProjectWatchlist, ReraProject

DEFAULT_WATCHLIST_LIMIT = 100

# First key of the two-key advisory lock that serializes one user's watchlist adds.
_WATCHLIST_LOCK_KEY = 4_217

# Name of the relationship attached at import time (see ``_ensure_project_relationship``).
_PROJECT_RELATIONSHIP = "rera_project"


class WatchlistLimitExceeded(ValueError):
    """Raised when a user tries to watch more than ``DEFAULT_WATCHLIST_LIMIT`` projects."""


def _ensure_project_relationship() -> None:
    """Attach a read-only ``rera_project`` relationship used for eager loading.

    ``ProjectWatchlist`` does not declare this relationship and the model is
    frozen, so it is attached here once at import. That lets ``list_watchlist``
    eager-load the project with ``selectinload`` instead of issuing one query per
    row. ``hasattr`` keeps it idempotent if the relationship is ever added to the
    model itself.
    """
    if not hasattr(ProjectWatchlist, _PROJECT_RELATIONSHIP):
        setattr(  # noqa: B010 - the attribute is attached to a class, not an instance
            ProjectWatchlist, _PROJECT_RELATIONSHIP, relationship(ReraProject, viewonly=True)
        )


_ensure_project_relationship()


async def add_to_watchlist(
    db: AsyncSession,
    *,
    user_id: int,
    project_id: int,
    notes: str | None = None,
    alert_prefs: dict | None = None,
) -> ProjectWatchlist:
    """Watch a project, or update an existing watch.

    Idempotent on the ``(user_id, project_id)`` pair: when the pair is already
    watched the existing row is returned with only the non-``None`` arguments
    applied. ``alert_prefs`` is merged into the stored switches, so a key the
    caller leaves out keeps its stored value. The per-user limit raises
    ``WatchlistLimitExceeded`` only for a new pair, so re-adding an entry the
    user already has always succeeds.

    Adds for one user are serialized with a transaction-scoped advisory lock, so
    two concurrent requests cannot both pass the limit check. A concurrent insert
    of the same pair is caught in a savepoint and resolved to the stored row.
    """
    await db.execute(select(func.pg_advisory_xact_lock(_WATCHLIST_LOCK_KEY, user_id)))

    existing = await _get_watch(db, user_id=user_id, project_id=project_id)
    if existing is not None:
        return await _apply_update(db, existing, notes=notes, alert_prefs=alert_prefs)

    count = (
        await db.execute(
            select(func.count())
            .select_from(ProjectWatchlist)
            .where(ProjectWatchlist.user_id == user_id)
        )
    ).scalar_one()
    if count >= DEFAULT_WATCHLIST_LIMIT:
        raise WatchlistLimitExceeded(
            f"Watchlist limit of {DEFAULT_WATCHLIST_LIMIT} projects reached"
        )

    project = await db.get(ReraProject, project_id)
    # Start the alert baseline at what the user sees now, so the first alert run
    # reports only changes made after the user started watching.
    from app.services.data_hub.watchlist_alerts import current_alert_snapshot

    baseline = await current_alert_snapshot(db, project) if project is not None else None
    watch = ProjectWatchlist(
        user_id=user_id,
        rera_project_id=project_id,
        notes=notes,
        alert_prefs=alert_prefs,
        alert_baseline=baseline,
    )
    try:
        async with db.begin_nested():
            db.add(watch)
            await db.flush()
    except IntegrityError:
        # Another session inserted the same pair first. Use its row.
        existing = await _get_watch(db, user_id=user_id, project_id=project_id)
        if existing is None:
            raise
        return await _apply_update(db, existing, notes=notes, alert_prefs=alert_prefs)
    return watch


async def _get_watch(
    db: AsyncSession, *, user_id: int, project_id: int
) -> ProjectWatchlist | None:
    return (
        await db.execute(
            select(ProjectWatchlist).where(
                ProjectWatchlist.user_id == user_id,
                ProjectWatchlist.rera_project_id == project_id,
            )
        )
    ).scalar_one_or_none()


async def _apply_update(
    db: AsyncSession,
    watch: ProjectWatchlist,
    *,
    notes: str | None,
    alert_prefs: dict | None,
) -> ProjectWatchlist:
    if notes is not None:
        watch.notes = notes
    if alert_prefs is not None:
        watch.alert_prefs = {**(watch.alert_prefs or {}), **alert_prefs}
    await db.flush()
    return watch


async def list_watchlist(db: AsyncSession, *, user_id: int) -> list[ProjectWatchlist]:
    """Return the user's watches, newest first, with the project eager-loaded.

    ``selectinload`` loads every related ``ReraProject`` in one extra query, so a
    caller can read ``watch.rera_project`` for the whole list without an N+1.
    """
    result = await db.execute(
        select(ProjectWatchlist)
        .where(ProjectWatchlist.user_id == user_id)
        .order_by(ProjectWatchlist.created_at.desc(), ProjectWatchlist.id.desc())
        .options(selectinload(getattr(ProjectWatchlist, _PROJECT_RELATIONSHIP)))
    )
    return list(result.scalars().all())


async def remove_from_watchlist(db: AsyncSession, *, user_id: int, project_id: int) -> bool:
    """Delete a watch. ``False`` when the pair was not watched, ``True`` when deleted."""
    watch = (
        await db.execute(
            select(ProjectWatchlist).where(
                ProjectWatchlist.user_id == user_id,
                ProjectWatchlist.rera_project_id == project_id,
            )
        )
    ).scalar_one_or_none()
    if watch is None:
        return False
    await db.delete(watch)
    await db.flush()
    return True


async def watched_project_ids(db: AsyncSession, *, user_id: int) -> set[int]:
    """Return the ids of every project the user watches."""
    result = await db.execute(
        select(ProjectWatchlist.rera_project_id).where(ProjectWatchlist.user_id == user_id)
    )
    return {row[0] for row in result.all()}


async def users_watching_project(db: AsyncSession, *, project_id: int) -> list[int]:
    """Return the ids of every user watching a project."""
    result = await db.execute(
        select(ProjectWatchlist.user_id).where(ProjectWatchlist.rera_project_id == project_id)
    )
    return [row[0] for row in result.all()]
