"""Runs the tour migrations on test rows (BE-tours fix round 2, review items 1, 6, 17).

The SQL files run inside the db_session transaction, which is rolled back at the end.
The ORM schema from conftest stands in for the migrated schema. Only the tables the
migrations touch are needed.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import select, text

from app.models.enums import TourStatus, TourVisibility
from app.models.tours import FloorPlan, Hotspot, Scene, Tour
from app.schemas.tour import FloorPlanResponse

MIGRATIONS = Path(__file__).resolve().parents[3] / "supabase" / "migrations"
FLOOR_PLAN_MIGRATION = MIGRATIONS / "20261014006000_floor_plans_single_source.sql"
ORDER_INDEX_MIGRATION = MIGRATIONS / "20261014006004_order_index_not_null.sql"
_IMG = "https://res.cloudinary.com/demo/image/upload/plan.png"


def _tour(user, settings: dict | None) -> Tour:
    return Tour(
        id=str(uuid.uuid4()),
        user_id=user.id,
        title="Legacy",
        status=TourStatus.draft,
        is_public=False,
        visibility=TourVisibility.private,
        settings=settings,
    )


async def _plans_for(db_session, tour_id: str) -> list[FloorPlan]:
    result = await db_session.execute(select(FloorPlan).where(FloorPlan.tour_id == tour_id))
    return list(result.scalars().all())


# Review item 1 and 6: only valid markers are copied, and a re-run adds no rows.
@pytest.mark.asyncio
async def test_floor_plan_migration_copies_valid_markers_and_is_rerun_safe(db_session, test_user):
    tour_a = _tour(
        test_user,
        {
            "auto_rotate": True,
            "floor_plans": [
                {
                    "id": "fp-good",
                    "name": "Ground",
                    "image_url": _IMG,
                    "floor_number": 1,
                    "markers": [
                        {"scene_id": "s1", "x": 10, "y": 20, "label": "Kitchen"},
                        {"x": 10, "y": 20},
                        {"scene_id": "", "x": 1, "y": 1},
                        {"scene_id": "s2", "x": "10", "y": 5},
                        {"scene_id": "s3", "x": 150, "y": 5},
                        {"scene_id": "s4", "x": 5, "y": 5, "label": 7},
                    ],
                },
                {
                    "id": "fp-big",
                    "name": "Big",
                    "image_url": _IMG,
                    "floor_number": "2147483648",
                    "markers": [{"x": 10, "y": 20}],
                },
                {"name": "No id", "image_url": _IMG, "floor_number": 2, "markers": None},
                {"name": "No image", "markers": []},
            ],
        },
    )
    tour_b = _tour(
        test_user,
        {"floor_plans": [{"id": "fp-b1", "name": "Only", "image_url": _IMG, "markers": []}]},
    )
    db_session.add_all([tour_a, tour_b])
    await db_session.flush()

    sql = FLOOR_PLAN_MIGRATION.read_text()
    await db_session.execute(text(sql))

    plans = {plan.id: plan for plan in await _plans_for(db_session, tour_a.id)}
    good = plans["fp-good"]
    assert good.markers == [
        {"scene_id": "s1", "x": 10, "y": 20, "label": "Kitchen"},
        {"scene_id": "s4", "x": 5, "y": 5},
    ]
    assert plans["fp-big"].floor_number == 1
    assert plans["fp-big"].markers == []
    id_less = [plan for plan in plans.values() if plan.name == "No id"]
    assert len(id_less) == 1 and id_less[0].floor_number == 2

    # The copied rows validate as the API response, so the owner view does not fail.
    for plan in plans.values():
        FloorPlanResponse.model_validate(
            {
                "id": plan.id,
                "tour_id": plan.tour_id,
                "name": plan.name,
                "image_url": plan.image_url,
                "floor_number": plan.floor_number,
                "markers": plan.markers,
                "created_at": datetime.now(UTC),
                "updated_at": datetime.now(UTC),
            }
        )

    # Tour A keeps its settings key: the 'No image' plan could not be copied.
    settings_a = (
        await db_session.execute(select(Tour.settings).where(Tour.id == tour_a.id))
    ).scalar_one()
    assert "floor_plans" in settings_a
    # Tour B's only plan is a row now, so the key is removed.
    settings_b = (
        await db_session.execute(select(Tour.settings).where(Tour.id == tour_b.id))
    ).scalar_one()
    assert "floor_plans" not in settings_b

    # Second run: no duplicate of the id-less plan, no error.
    count_before = len(await _plans_for(db_session, tour_a.id))
    await db_session.execute(text(sql))
    assert len(await _plans_for(db_session, tour_a.id)) == count_before


# Review item 17: scenes.order_index and hotspots.order_index are backfilled, then NOT NULL.
@pytest.mark.asyncio
async def test_order_index_migration_backfills_after_the_highest_value(db_session, test_user):
    tour = _tour(test_user, None)
    db_session.add(tour)
    await db_session.flush()
    base = datetime(2026, 10, 1, tzinfo=UTC)
    scenes = [
        Scene(id=str(uuid.uuid4()), tour_id=tour.id, image_url=_IMG, order_index=3),
        Scene(id=str(uuid.uuid4()), tour_id=tour.id, image_url=_IMG, order_index=0),
        Scene(id=str(uuid.uuid4()), tour_id=tour.id, image_url=_IMG, order_index=0),
    ]
    db_session.add_all(scenes)
    await db_session.flush()
    await db_session.execute(text("ALTER TABLE scenes ALTER COLUMN order_index DROP NOT NULL"))
    await db_session.execute(
        text("UPDATE scenes SET order_index = NULL, created_at = :ts WHERE id = :id"),
        [
            {"id": scenes[1].id, "ts": base + timedelta(minutes=2)},
            {"id": scenes[2].id, "ts": base + timedelta(minutes=1)},
        ],
    )
    # Keep the highest-valued scene as is; the NULL rows get 4 and 5 in created_at order.
    await db_session.execute(text(ORDER_INDEX_MIGRATION.read_text()))

    values = dict(
        (
            await db_session.execute(
                text("SELECT id, order_index FROM scenes WHERE tour_id = :t"), {"t": tour.id}
            )
        ).all()
    )
    assert values[scenes[0].id] == 3
    assert values[scenes[2].id] == 4
    assert values[scenes[1].id] == 5
    nullable = (
        await db_session.execute(
            text(
                "SELECT is_nullable FROM information_schema.columns "
                "WHERE table_name = 'scenes' AND column_name = 'order_index'"
            )
        )
    ).scalar_one()
    assert nullable == "NO"

    # Hotspots: the NULL row in a scene gets the next index after that scene's highest one.
    hotspots = [
        Hotspot(
            id=str(uuid.uuid4()),
            scene_id=scenes[0].id,
            type="info",
            position={"yaw": 0.0, "pitch": 0.0},
            order_index=2,
            is_active=True,
        ),
        Hotspot(
            id=str(uuid.uuid4()),
            scene_id=scenes[0].id,
            type="info",
            position={"yaw": 0.0, "pitch": 0.0},
            order_index=0,
            is_active=True,
        ),
    ]
    db_session.add_all(hotspots)
    await db_session.flush()
    await db_session.execute(text("ALTER TABLE hotspots ALTER COLUMN order_index DROP NOT NULL"))
    await db_session.execute(
        text("UPDATE hotspots SET order_index = NULL, created_at = :ts WHERE id = :id"),
        [{"id": hotspots[1].id, "ts": base}],
    )
    await db_session.execute(text(ORDER_INDEX_MIGRATION.read_text()))
    hotspot_values = dict(
        (
            await db_session.execute(
                text("SELECT id, order_index FROM hotspots WHERE scene_id = :s"),
                {"s": scenes[0].id},
            )
        ).all()
    )
    assert hotspot_values[hotspots[0].id] == 2
    assert hotspot_values[hotspots[1].id] == 3


# A settings value that is not a plan list must not abort the migration (review item 6).
@pytest.mark.asyncio
async def test_floor_plan_migration_skips_non_list_and_non_object_plans(db_session, test_user):
    tour_object = _tour(test_user, {"floor_plans": {"name": "not a list"}})
    tour_mixed = _tour(test_user, {"floor_plans": ["text", {"name": "x", "image_url": _IMG}]})
    db_session.add_all([tour_object, tour_mixed])
    await db_session.flush()

    await db_session.execute(text(FLOOR_PLAN_MIGRATION.read_text()))

    assert await _plans_for(db_session, tour_object.id) == []
    # The object element is copied. The text element is not a plan, so it keeps the key.
    assert [plan.name for plan in await _plans_for(db_session, tour_mixed.id)] == ["x"]
    settings_object = (
        await db_session.execute(select(Tour.settings).where(Tour.id == tour_object.id))
    ).scalar_one()
    settings_mixed = (
        await db_session.execute(select(Tour.settings).where(Tour.id == tour_mixed.id))
    ).scalar_one()
    assert "floor_plans" in settings_object
    assert "floor_plans" in settings_mixed
