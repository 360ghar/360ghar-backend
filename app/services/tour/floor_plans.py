"""
Floor plan CRUD service functions.

Create, read, update, delete floor plans, and update markers.
"""

from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundException
from app.core.logging import get_logger
from app.models.tours import FloorPlan
from app.schemas.tour import FloorPlanCreate, FloorPlanUpdate
from app.services.tour.helpers import _ensure_tour_ownership
from app.services.tour.tours import get_tour
from app.utils.validators import ValidationUtils

logger = get_logger(__name__)


async def get_floor_plans(db: AsyncSession, tour_id: str, user_id: int) -> list[FloorPlan]:
    """Get all floor plans for a tour."""
    # Verify tour access
    await get_tour(db, tour_id, user_id, include_scenes=False)

    query = select(FloorPlan).where(FloorPlan.tour_id == tour_id).order_by(FloorPlan.floor_number)

    result = await db.execute(query)
    return list(result.scalars().all())


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
        if field == "image_url" and value is not None and not ValidationUtils.is_absolute_url(value):
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
