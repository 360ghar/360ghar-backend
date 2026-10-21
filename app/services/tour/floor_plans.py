"""
Floor plan CRUD service functions.

Create, read, update, delete floor plans, and update markers.
"""

import asyncio
from typing import Any
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BadRequestException, NotFoundException
from app.core.logging import get_logger
from app.models.enums import HotspotType
from app.models.tours import FloorPlan
from app.schemas.pagination import keyset_filter, trim_keyset_lookahead
from app.schemas.tour import FloorPlanCreate, FloorPlanMarkerIn, FloorPlanUpdate
from app.services.cloudinary import get_cloudinary_service
from app.services.tour.floorplan_layout import RoomInput, build_floor_plan_image
from app.services.tour.helpers import _ensure_tour_ownership
from app.services.tour.tours import get_tour
from app.utils.validators import ValidationUtils

logger = get_logger(__name__)


async def get_floor_plans_page(
    db: AsyncSession,
    tour_id: str,
    user_id: int,
    cursor_payload: dict[str, Any],
    limit: int,
    include_total: bool = False,
) -> tuple[list[FloorPlan], dict[str, Any] | None, int | None]:
    """One keyset page of a tour's floor plans, in floor_number order. total is set only with include_total."""
    await get_tour(db, tour_id, user_id, include_scenes=False)

    total: int | None = None
    if include_total:
        total = int(
            (
                await db.execute(
                    select(func.count(FloorPlan.id)).where(FloorPlan.tour_id == tour_id)
                )
            ).scalar_one()
        )
    query = select(FloorPlan).where(FloorPlan.tour_id == tour_id)
    predicate = keyset_filter(
        FloorPlan.floor_number, FloorPlan.id, cursor_payload, descending=False
    )
    if predicate is not None:
        query = query.where(predicate)
    query = query.order_by(FloorPlan.floor_number, FloorPlan.id).limit(limit + 1)

    rows = list((await db.execute(query)).scalars().all())
    items, next_payload = trim_keyset_lookahead(
        rows,
        limit=limit,
        sort_value=lambda plan: plan.floor_number,
        item_id=lambda plan: plan.id,
    )
    return items, next_payload, total


async def get_floor_plan(
    db: AsyncSession,
    floor_plan_id: str,
    user_id: int,
    tour_id: str | None = None,
) -> FloorPlan:
    """Get a floor plan by ID, optionally scoped to a specific tour."""
    query = select(FloorPlan).where(FloorPlan.id == floor_plan_id)
    if tour_id is not None:
        query = query.where(FloorPlan.tour_id == tour_id)
    result = await db.execute(query)
    floor_plan = result.scalar_one_or_none()

    if not floor_plan:
        raise NotFoundException(detail="Floor plan not found")

    # Verify tour ownership
    tour = await get_tour(db, floor_plan.tour_id, user_id, include_scenes=False)
    _ensure_tour_ownership(tour, user_id, "access floor plans in")

    return floor_plan


async def create_floor_plan(
    db: AsyncSession, tour_id: str, user_id: int, data: FloorPlanCreate
) -> FloorPlan:
    """Create a new floor plan for a tour."""
    tour = await get_tour(db, tour_id, user_id, include_scenes=False)
    _ensure_tour_ownership(tour, user_id, "add floor plans to")

    # Convert markers to list of dicts
    markers_data = [m.model_dump() for m in data.markers] if data.markers else []

    image_url = data.image_url
    if not ValidationUtils.is_absolute_url(image_url):
        logger.warning("Non-absolute floor plan image URL provided: %s", image_url)

    floor_plan = FloorPlan(
        id=str(uuid4()),
        tour_id=tour_id,
        name=data.name,
        image_url=image_url,
        floor_number=data.floor_number,
        markers=markers_data,
    )

    db.add(floor_plan)
    await db.commit()
    await db.refresh(floor_plan)

    logger.info("Floor plan created: %s in tour %s", floor_plan.id, tour_id)
    return floor_plan


async def update_floor_plan(
    db: AsyncSession,
    floor_plan_id: str,
    user_id: int,
    data: FloorPlanUpdate,
    tour_id: str | None = None,
) -> FloorPlan:
    """Update a floor plan."""
    floor_plan = await get_floor_plan(db, floor_plan_id, user_id, tour_id=tour_id)

    update_data = data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        if (
            field == "image_url"
            and value is not None
            and not ValidationUtils.is_absolute_url(value)
        ):
            logger.warning("Non-absolute floor plan image URL provided: %s", value)
        if field == "markers" and value is not None:
            # Convert markers to list of dicts
            value = [m if isinstance(m, dict) else m.model_dump() for m in value]
        setattr(floor_plan, field, value)

    await db.commit()
    await db.refresh(floor_plan)

    logger.info("Floor plan updated: %s", floor_plan_id)
    return floor_plan


async def update_floor_plan_markers(
    db: AsyncSession,
    floor_plan_id: str,
    user_id: int,
    markers: list[dict],
    tour_id: str | None = None,
) -> FloorPlan:
    """Update only the markers of a floor plan."""
    floor_plan = await get_floor_plan(db, floor_plan_id, user_id, tour_id=tour_id)

    floor_plan.markers = markers
    await db.commit()
    await db.refresh(floor_plan)

    logger.info("Floor plan markers updated: %s", floor_plan_id)
    return floor_plan


async def delete_floor_plan(
    db: AsyncSession,
    floor_plan_id: str,
    user_id: int,
    tour_id: str | None = None,
) -> bool:
    """Delete a floor plan."""
    floor_plan = await get_floor_plan(db, floor_plan_id, user_id, tour_id=tour_id)

    await db.delete(floor_plan)
    await db.commit()

    logger.info("Floor plan deleted: %s", floor_plan_id)
    return True


GENERATED_FLOOR_PLAN_NAME = "Estimated layout (AI)"


async def generate_floor_plan(db: AsyncSession, tour_id: str, user_id: int) -> FloorPlan:
    """Build a schematic floor plan from the tour's analyzed scenes and doorway links.

    Deterministic and instant: room types and navigation hotspots already exist,
    so no AI call happens here. Re-running replaces the previous generated
    plan's image and markers instead of creating a duplicate row.
    """
    tour = await get_tour(db, tour_id, user_id, include_scenes=True)
    _ensure_tour_ownership(tour, user_id, "generate floor plans for")

    scenes = sorted(tour.scenes or [], key=lambda s: s.order_index)
    if len(scenes) < 2:
        raise BadRequestException(
            detail="A floor plan needs at least two scenes. Add panoramas or rooms first."
        )

    scene_ids = {s.id for s in scenes}
    rooms = [
        RoomInput(
            scene_id=s.id,
            title=s.title or f"Scene {index + 1}",
            room_type=(s.scene_metadata or {}).get("room_type"),
            order_index=s.order_index if s.order_index is not None else index,
        )
        for index, s in enumerate(scenes)
    ]
    edges: list[tuple[str, str]] = []
    for s in scenes:
        for hotspot in s.hotspots or []:
            target = hotspot.target_scene_id
            if (
                hotspot.type == HotspotType.navigation
                and hotspot.is_active
                and target is not None
                and target in scene_ids
                and target != s.id
            ):
                edges.append((s.id, target))

    start_scene_id = (tour.settings or {}).get("initial_scene_id")

    png_bytes, markers = await asyncio.to_thread(
        build_floor_plan_image, rooms, edges, start_scene_id, tour.title
    )

    upload_result = await asyncio.to_thread(
        get_cloudinary_service().upload_file,
        file_bytes=png_bytes,
        public_id=f"{uuid4().hex[:10]}_floor_plan",
        folder=f"tours/{tour_id}/floor-plans",
        content_type="image/png",
        is_image=True,
    )
    image_url: str = upload_result["secure_url"]
    marker_models = [FloorPlanMarkerIn(**marker) for marker in markers]

    existing = (
        (
            await db.execute(
                select(FloorPlan).where(
                    FloorPlan.tour_id == tour_id,
                    FloorPlan.name == GENERATED_FLOOR_PLAN_NAME,
                )
            )
        )
        .scalars()
        .first()
    )

    if existing is not None:
        return await update_floor_plan(
            db,
            floor_plan_id=existing.id,
            user_id=user_id,
            data=FloorPlanUpdate(image_url=image_url, markers=marker_models),
            tour_id=tour_id,
        )

    highest_floor = (
        await db.execute(
            select(func.max(FloorPlan.floor_number)).where(FloorPlan.tour_id == tour_id)
        )
    ).scalar() or 0

    return await create_floor_plan(
        db,
        tour_id=tour_id,
        user_id=user_id,
        data=FloorPlanCreate(
            name=GENERATED_FLOOR_PLAN_NAME,
            image_url=image_url,
            floor_number=max(1, highest_floor + 1),
            markers=marker_models,
        ),
    )
