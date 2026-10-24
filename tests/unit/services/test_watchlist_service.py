"""Watchlist service tests: idempotency, the limit, removal, and eager loading."""

from __future__ import annotations

import pytest

from app.models.data_hub import ProjectWatchlist, ReraProject
from app.services.data_hub import watchlist as watchlist_service
from app.services.data_hub.watchlist import (
    WatchlistLimitExceeded,
    add_to_watchlist,
    list_watchlist,
    remove_from_watchlist,
    users_watching_project,
    watched_project_ids,
)


async def _project(db_session, *, rera_number: str, name: str) -> ReraProject:
    project = ReraProject(rera_number=rera_number, project_name=name, slug=rera_number.lower())
    db_session.add(project)
    await db_session.flush()
    return project


@pytest.mark.asyncio
async def test_add_to_watchlist_is_idempotent_and_does_not_duplicate(db_session, test_user):
    project = await _project(db_session, rera_number="RERA-A-1", name="Alpha Heights")

    first = await add_to_watchlist(db_session, user_id=test_user.id, project_id=project.id)
    second = await add_to_watchlist(
        db_session,
        user_id=test_user.id,
        project_id=project.id,
        notes="Watching the price",
    )

    assert first.id == second.id
    assert second.notes == "Watching the price"
    rows = (await list_watchlist(db_session, user_id=test_user.id))
    assert [row.id for row in rows] == [first.id]


@pytest.mark.asyncio
async def test_second_add_only_touches_the_arguments_that_are_not_none(
    db_session, test_user
):
    project = await _project(db_session, rera_number="RERA-A-2", name="Beta Towers")
    await add_to_watchlist(
        db_session,
        user_id=test_user.id,
        project_id=project.id,
        notes="keep me",
        alert_prefs={"watchlist_price_change": False},
    )

    updated = await add_to_watchlist(db_session, user_id=test_user.id, project_id=project.id)

    assert updated.notes == "keep me"
    assert updated.alert_prefs == {"watchlist_price_change": False}


@pytest.mark.asyncio
async def test_limit_raises_only_for_a_new_pair(db_session, test_user, monkeypatch):
    monkeypatch.setattr(watchlist_service, "DEFAULT_WATCHLIST_LIMIT", 2)
    first = await _project(db_session, rera_number="RERA-L-1", name="One")
    second = await _project(db_session, rera_number="RERA-L-2", name="Two")
    third = await _project(db_session, rera_number="RERA-L-3", name="Three")

    await add_to_watchlist(db_session, user_id=test_user.id, project_id=first.id)
    await add_to_watchlist(db_session, user_id=test_user.id, project_id=second.id)

    # Re-adding a pair the user already has must still succeed at the limit.
    again = await add_to_watchlist(db_session, user_id=test_user.id, project_id=first.id)
    assert again.rera_project_id == first.id

    with pytest.raises(WatchlistLimitExceeded):
        await add_to_watchlist(db_session, user_id=test_user.id, project_id=third.id)


@pytest.mark.asyncio
async def test_remove_returns_false_for_an_unwatched_pair(db_session, test_user):
    project = await _project(db_session, rera_number="RERA-R-1", name="Gamma")

    assert await remove_from_watchlist(db_session, user_id=test_user.id, project_id=project.id) is False

    await add_to_watchlist(db_session, user_id=test_user.id, project_id=project.id)
    assert await remove_from_watchlist(db_session, user_id=test_user.id, project_id=project.id) is True
    assert await remove_from_watchlist(db_session, user_id=test_user.id, project_id=project.id) is False


@pytest.mark.asyncio
async def test_list_watchlist_is_newest_first_and_eager_loads_the_project(db_session, test_user):
    older = await _project(db_session, rera_number="RERA-O-1", name="Older")
    newer = await _project(db_session, rera_number="RERA-O-2", name="Newer")

    await add_to_watchlist(db_session, user_id=test_user.id, project_id=older.id)
    await add_to_watchlist(db_session, user_id=test_user.id, project_id=newer.id)

    rows = await list_watchlist(db_session, user_id=test_user.id)

    assert [row.rera_project_id for row in rows] == [newer.id, older.id]
    # The relationship is eager-loaded, so this access needs no extra query.
    assert rows[0].rera_project.project_name == "Newer"


@pytest.mark.asyncio
async def test_watched_ids_and_watchers_round_trip(db_session, test_user, test_user_2):
    project = await _project(db_session, rera_number="RERA-W-1", name="Shared")
    other = await _project(db_session, rera_number="RERA-W-2", name="Other")
    await add_to_watchlist(db_session, user_id=test_user.id, project_id=project.id)
    await add_to_watchlist(db_session, user_id=test_user.id, project_id=other.id)
    await add_to_watchlist(db_session, user_id=test_user_2.id, project_id=project.id)

    assert await watched_project_ids(db_session, user_id=test_user.id) == {project.id, other.id}
    assert set(await users_watching_project(db_session, project_id=project.id)) == {
        test_user.id,
        test_user_2.id,
    }


@pytest.mark.asyncio
async def test_the_relationship_used_for_eager_loading_is_attached(db_session):
    assert hasattr(ProjectWatchlist, "rera_project")


@pytest.mark.asyncio
async def test_a_partial_alert_prefs_update_keeps_the_other_stored_switches(
    db_session, test_user
):
    project = await _project(db_session, rera_number="RERA-A-9", name="Gamma Towers")
    await add_to_watchlist(
        db_session,
        user_id=test_user.id,
        project_id=project.id,
        alert_prefs={"watchlist_price_change": False, "watchlist_new_filing": False},
    )

    updated = await add_to_watchlist(
        db_session,
        user_id=test_user.id,
        project_id=project.id,
        alert_prefs={"watchlist_price_change": True},
    )

    assert updated.alert_prefs == {
        "watchlist_price_change": True,
        "watchlist_new_filing": False,
    }


@pytest.mark.asyncio
async def test_a_new_watch_starts_with_an_alert_baseline(db_session, test_user):
    project = await _project(db_session, rera_number="RERA-A-10", name="Delta Towers")

    watch = await add_to_watchlist(db_session, user_id=test_user.id, project_id=project.id)

    assert watch.alert_baseline is not None
    assert watch.alert_baseline["documents"] == []
