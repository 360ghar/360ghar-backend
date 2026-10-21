"""Run the wave 3d drift migrations on test rows, inside the test transaction.

The test schema is built from the models, which already carry the target state. Each test
puts the columns back to the state the migration starts from, runs the migration file, and
reads the result. The transaction is rolled back after each test.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from app.models.agents import AgentInteraction
from app.models.tours import AIJob, CustomDomain, FloorPlan, Hotspot, MediaFile, Scene, Tour
from app.models.users import UserSearchHistory
from tests.fixtures.factories import (
    AgentFactory,
    BookingFactory,
    PropertyFactory,
    SwipeFactory,
    UserFactory,
    VisitFactory,
)
from tests.unit.models.test_schema_drift_types import NOT_NULL_COLUMNS

pytestmark = pytest.mark.asyncio

MIGRATIONS = Path(__file__).resolve().parents[3] / "supabase" / "migrations"
DOUBLE_MIGRATION = "20261015002001_drift_real_to_double.sql"
NOT_NULL_MIGRATION = "20261015002002_drift_not_null_backfill.sql"
_IMG = "https://res.cloudinary.com/demo/image/upload/pano.jpg"


async def _run(db_session, name: str) -> None:
    conn = await db_session.connection()
    await conn.exec_driver_sql((MIGRATIONS / name).read_text())


async def _query(db_session, sql: str):
    conn = await db_session.connection()
    return (await conn.exec_driver_sql(sql)).all()


async def _one(db_session, table: str, pk: str, value, columns: list[str]) -> tuple:
    rows = await _query(
        db_session, f"SELECT {', '.join(columns)} FROM {table} WHERE {pk} = '{value}'"
    )
    assert len(rows) == 1, f"{table} row {value} not found"
    return tuple(rows[0])


async def _data_type(db_session, table: str, column: str) -> str:
    rows = await _query(
        db_session,
        "SELECT data_type FROM information_schema.columns "
        f"WHERE table_schema = 'public' AND table_name = '{table}' AND column_name = '{column}'",
    )
    return rows[0][0]


async def _is_nullable(db_session, table: str, column: str) -> str:
    rows = await _query(
        db_session,
        "SELECT is_nullable FROM information_schema.columns "
        f"WHERE table_schema = 'public' AND table_name = '{table}' AND column_name = '{column}'",
    )
    return rows[0][0]


async def _make_rows(db) -> dict:
    """One row per touched table, plus a control agent and tour that already hold values."""
    user = await UserFactory.create(db)
    prop = await PropertyFactory.create(db, owner_id=user.id)
    agent = await AgentFactory.create(db, name="Null Flags")
    control_agent = await AgentFactory.create(db, name="Control", is_active=True, is_available=True)
    tour = Tour(id=str(uuid.uuid4()), user_id=user.id, title="Null Tour")
    control_tour = Tour(
        id=str(uuid.uuid4()),
        user_id=user.id,
        title="Control Tour",
        is_public=True,
        is_featured=True,
    )
    db.add_all([tour, control_tour])
    await db.flush()
    scene = Scene(id=str(uuid.uuid4()), tour_id=tour.id, image_url=_IMG)
    db.add(scene)
    await db.flush()
    hotspot = Hotspot(id=str(uuid.uuid4()), scene_id=scene.id, position={"yaw": 0, "pitch": 0})
    plan = FloorPlan(id=str(uuid.uuid4()), tour_id=tour.id, name="Ground", image_url=_IMG)
    domain = CustomDomain(id=str(uuid.uuid4()), user_id=user.id, domain="tours.example.com")
    media = MediaFile(
        id=str(uuid.uuid4()),
        user_id=user.id,
        filename="a.jpg",
        file_url=_IMG,
        file_size=10,
        mime_type="image/jpeg",
    )
    job = AIJob(id=str(uuid.uuid4()), user_id=user.id, job_type="analyze_scenes")
    interaction = AgentInteraction(
        agent_id=agent.id, user_id=user.id, interaction_type="chat", message="hi"
    )
    history = UserSearchHistory(user_id=user.id)
    db.add_all([hotspot, plan, domain, media, job, interaction, history])
    await db.flush()
    swipe = await SwipeFactory.create(db, user=user, property_obj=prop)
    booking = await BookingFactory.create(db, user=user, property_obj=prop)
    visit = await VisitFactory.create(db, user=user, property_obj=prop)
    return {
        "agents": ("id", agent.id),
        "control_agent": control_agent,
        "agent_interactions": ("id", interaction.id),
        "ai_jobs": ("id", job.id),
        "bookings": ("id", booking.id),
        "custom_domains": ("id", domain.id),
        "floor_plans": ("id", plan.id),
        "hotspots": ("id", hotspot.id),
        "media_files": ("id", media.id),
        "scenes": ("id", scene.id),
        "tours": ("id", tour.id),
        "control_tour": control_tour,
        "user_search_history": ("id", history.id),
        "user_swipes": ("id", swipe.id),
        "visits": ("id", visit.id),
    }


async def test_not_null_migration_backfills_and_sets_not_null_on_every_declared_column(db_session):
    rows = await _make_rows(db_session)

    # Pre-migration state: every column nullable and NULL.
    by_table: dict[str, list[str]] = {}
    for ref in NOT_NULL_COLUMNS:
        table, column = ref.split(".")
        by_table.setdefault(table, []).append(column)
    conn = await db_session.connection()
    for table, columns in by_table.items():
        await conn.exec_driver_sql(
            f"ALTER TABLE {table} " + ", ".join(f"ALTER COLUMN {c} DROP NOT NULL" for c in columns)
        )
        pk, value = rows[table]
        await conn.exec_driver_sql(
            f"UPDATE {table} SET "
            + ", ".join(f"{c} = NULL" for c in columns)
            + f" WHERE {pk} = '{value}'"
        )
        nulls = await _one(db_session, table, pk, value, columns)
        assert all(v is None for v in nulls), f"{table} was not put back to NULL"

    await _run(db_session, NOT_NULL_MIGRATION)

    for ref in NOT_NULL_COLUMNS:
        table, column = ref.split(".")
        assert await _is_nullable(db_session, table, column) == "NO", ref

    def stored(table: str, columns: list[str]):
        pk, value = rows[table]
        return _one(db_session, table, pk, value, columns)

    # Flags that expose a row become FALSE, so the migration activates and publishes nothing.
    assert await stored("agents", ["is_active", "is_available"]) == (False, False)
    assert await stored("agents", ["total_users_assigned", "user_satisfaction_rating"]) == (0, 0.0)
    assert await stored("hotspots", ["is_active"]) == (False,)
    assert await stored("tours", ["is_public", "is_featured"]) == (False, False)
    assert await stored("tours", ["like_count", "share_count", "view_count"]) == (0, 0, 0)
    # Safe defaults.
    assert await stored("media_files", ["visibility", "is_processed"]) == ("private", False)
    assert await stored("scenes", ["is_processed"]) == (False,)
    assert await stored("ai_jobs", ["progress", "retry_count"]) == (0, 0)
    assert await stored("bookings", ["early_check_in", "late_check_out"]) == (False, False)
    assert await stored("visits", ["follow_up_required", "status"]) == (False, "requested")
    assert await stored("floor_plans", ["floor_number"]) == (1,)
    # Timestamps take now(); custom_domains.updated_at follows created_at.
    for table in (
        "agents",
        "agent_interactions",
        "bookings",
        "custom_domains",
        "user_search_history",
        "user_swipes",
        "visits",
    ):
        (created,) = await stored(table, ["created_at"])
        assert created is not None, table
    created, updated = await stored("custom_domains", ["created_at", "updated_at"])
    assert updated == created

    # Rows that already hold values are not touched.
    control_agent = rows["control_agent"]
    assert await _one(
        db_session, "agents", "id", control_agent.id, ["is_active", "is_available"]
    ) == (True, True)
    control_tour = rows["control_tour"]
    assert await _one(db_session, "tours", "id", control_tour.id, ["is_public", "is_featured"]) == (
        True,
        True,
    )


@pytest.mark.parametrize("migration", [DOUBLE_MIGRATION, NOT_NULL_MIGRATION])
async def test_drift_migrations_are_safe_to_run_on_a_conforming_database(db_session, migration):
    await _make_rows(db_session)
    await _run(db_session, migration)
    await _run(db_session, migration)


async def test_real_columns_become_double_precision_without_binary_noise(db_session):
    rows = await _make_rows(db_session)
    history_id = rows["user_search_history"][1]
    agent_id = rows["agents"][1]

    conn = await db_session.connection()
    await conn.exec_driver_sql("ALTER TABLE agents ALTER COLUMN user_satisfaction_rating TYPE REAL")
    await conn.exec_driver_sql(
        "ALTER TABLE user_search_history "
        "ALTER COLUMN user_location_lat TYPE REAL, ALTER COLUMN user_location_lng TYPE REAL"
    )
    await conn.exec_driver_sql(
        f"UPDATE agents SET user_satisfaction_rating = 4.3 WHERE id = {agent_id}"
    )
    await conn.exec_driver_sql(
        "UPDATE user_search_history SET user_location_lat = 28.613939, "
        f"user_location_lng = 77.209023 WHERE id = {history_id}"
    )
    assert await _data_type(db_session, "agents", "user_satisfaction_rating") == "real"

    await _run(db_session, DOUBLE_MIGRATION)

    for table, column in (
        ("agents", "user_satisfaction_rating"),
        ("user_search_history", "user_location_lat"),
        ("user_search_history", "user_location_lng"),
    ):
        assert await _data_type(db_session, table, column) == "double precision"
    # REAL prints the shortest decimal that round-trips, so no 4.300000190734863.
    assert await _one(db_session, "agents", "id", agent_id, ["user_satisfaction_rating"]) == (4.3,)
    # A REAL holds about 7 digits: 28.613939 was already stored as 28.61394.
    assert await _one(
        db_session,
        "user_search_history",
        "id",
        history_id,
        ["user_location_lat", "user_location_lng"],
    ) == (28.61394, 77.20902)
