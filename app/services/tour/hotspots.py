"""
Hotspot CRUD service functions.

Create, read, update, delete hotspots, and update positions.
"""

from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import BadRequestException, ForbiddenException, HotspotNotFoundException
from app.core.logging import get_logger
from app.models.enums import HotspotType
from app.models.tours import Hotspot, Scene
from app.schemas.tour import HotspotCreate, HotspotPositionUpdate, HotspotUpdate
from app.services.tour.helpers import (
    _ensure_scene_ownership,
    _normalize_hotspot_content,
)
from app.services.tour.scenes import get_scene

logger = get_logger(__name__)


async def get_hotspots(
    db: AsyncSession, scene_id: str, user_id: int | None = None
) -> list[Hotspot]:
    """Get all hotspots for a scene."""
    # Verify scene access
    await get_scene(db, scene_id, user_id)

    query = select(Hotspot).where(Hotspot.scene_id == scene_id).order_by(Hotspot.order_index)
    result = await db.execute(query)
    return list(result.scalars().all())


async def get_hotspot(db: AsyncSession, hotspot_id: str, user_id: int | None = None) -> Hotspot:
    """Get a single hotspot by ID."""
    query = (
        select(Hotspot)
        .where(Hotspot.id == hotspot_id)
        .options(selectinload(Hotspot.scene).selectinload(Scene.tour))
    )

    result = await db.execute(query)
    hotspot = result.scalar_one_or_none()

    if not hotspot:
        raise HotspotNotFoundException()

    if user_id is not None and hotspot.scene.tour.user_id != user_id:
        raise ForbiddenException(detail="You don't have access to this hotspot")

    return hotspot


async def create_hotspot(
    db: AsyncSession, scene_id: str, user_id: int, data: HotspotCreate
) -> Hotspot:
    """Create a new hotspot in a scene."""
    scene = await get_scene(db, scene_id, user_id)
    _ensure_scene_ownership(scene, user_id, "add hotspots to")

    if data.type == HotspotType.navigation:
        if not data.target_scene_id:
            raise BadRequestException(detail="Navigation hotspots require target_scene_id")
        target_scene = await get_scene(db, data.target_scene_id, user_id)
        if target_scene.tour_id != scene.tour_id:
            raise BadRequestException(
                detail="Navigation hotspots must target a scene in the same tour"
            )

    normalized_content = _normalize_hotspot_content(data.type, data.content)

    # Get max order_index
    max_order_query = select(func.max(Hotspot.order_index)).where(Hotspot.scene_id == scene_id)
    result = await db.execute(max_order_query)
    max_order = result.scalar() or -1

    hotspot = Hotspot(
        id=str(uuid4()),
        scene_id=scene_id,
        type=data.type,
        position=data.position.model_dump(),
        target_scene_id=data.target_scene_id if data.type == HotspotType.navigation else None,
        title=data.title,
        description=data.description,
        icon=data.icon,
        icon_name=data.icon_name,
        icon_color=data.icon_color,
        icon_size=data.icon_size or 32,
        content=normalized_content,
        custom_data=data.custom_data,
        order_index=max_order + 1,
    )

    db.add(hotspot)
    await db.commit()
    await db.refresh(hotspot)

    logger.info("Hotspot created: %s in scene %s", hotspot.id, scene_id)
    return hotspot


async def update_hotspot(
    db: AsyncSession, hotspot_id: str, user_id: int, data: HotspotUpdate
) -> Hotspot:
    """Update a hotspot."""
    hotspot = await get_hotspot(db, hotspot_id, user_id)
    scene = hotspot.scene  # Already eager-loaded by get_hotspot

    update_data = data.model_dump(exclude_unset=True)

    next_type = data.type or hotspot.type
    next_target_scene_id = (
        data.target_scene_id if "target_scene_id" in update_data else hotspot.target_scene_id
    )
    next_content = data.content if "content" in update_data else hotspot.content

    if next_type == HotspotType.navigation:
        if not next_target_scene_id:
            raise BadRequestException(detail="Navigation hotspots require target_scene_id")
        target_scene = await get_scene(db, next_target_scene_id, user_id)
        if target_scene.tour_id != scene.tour_id:
            raise BadRequestException(
                detail="Navigation hotspots must target a scene in the same tour"
            )
    else:
        next_target_scene_id = None

    normalized_content = _normalize_hotspot_content(next_type, next_content)

    for field, value in update_data.items():
        if field == "position" and value is not None:
            value = value if isinstance(value, dict) else value.model_dump()
        if field == "content":
            value = normalized_content
        if field == "target_scene_id":
            value = next_target_scene_id
        setattr(hotspot, field, value)

    if "content" not in update_data and normalized_content != hotspot.content:
        hotspot.content = normalized_content
    if "target_scene_id" not in update_data and next_target_scene_id != hotspot.target_scene_id:
        hotspot.target_scene_id = next_target_scene_id

    await db.commit()
    await db.refresh(hotspot)

    logger.info("Hotspot updated: %s", hotspot_id)
    return hotspot


async def delete_hotspot(db: AsyncSession, hotspot_id: str, user_id: int) -> bool:
    """Delete a hotspot."""
    hotspot = await get_hotspot(db, hotspot_id, user_id)

    await db.delete(hotspot)
    await db.commit()

    logger.info("Hotspot deleted: %s", hotspot_id)
    return True


async def update_hotspot_position(
    db: AsyncSession, hotspot_id: str, user_id: int, position: HotspotPositionUpdate
) -> Hotspot:
    """Update only the position of a hotspot."""
    hotspot = await get_hotspot(db, hotspot_id, user_id)

    # Update position while preserving radius if it exists
    current_position = hotspot.position or {}
    hotspot.position = {
        "yaw": position.yaw,
        "pitch": position.pitch,
        "radius": current_position.get("radius"),
    }

    await db.commit()
    await db.refresh(hotspot)

    logger.info("Hotspot position updated: %s", hotspot_id)
    return hotspot
