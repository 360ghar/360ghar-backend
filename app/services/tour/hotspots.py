"""
Hotspot CRUD service functions.

Create, read, update, delete hotspots, and update positions. Content is
validated against the hotspot type by app.schemas.tour.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import BadRequestException, ForbiddenException, HotspotNotFoundException
from app.core.logging import get_logger
from app.models.enums import HotspotType
from app.models.tours import Hotspot, Scene
from app.schemas.pagination import keyset_filter, trim_keyset_lookahead
from app.schemas.tour import HotspotCreate, HotspotPositionUpdate, HotspotUpdate, content_to_storage
from app.services.tour.helpers import _ensure_scene_ownership
from app.services.tour.scenes import get_scene

logger = get_logger(__name__)


async def get_hotspots(
    db: AsyncSession, scene_id: str, user_id: int | None = None
) -> list[Hotspot]:
    """Get all hotspots for a scene."""
    items, _, _ = await get_hotspots_page(db, scene_id, user_id, {}, limit=10_000)
    return items


async def get_hotspots_page(
    db: AsyncSession,
    scene_id: str,
    user_id: int | None,
    cursor_payload: dict[str, Any],
    limit: int,
    include_total: bool = False,
) -> tuple[list[Hotspot], dict[str, Any] | None, int | None]:
    """One keyset page of a scene's hotspots, in order_index order. total is set only with include_total."""
    await get_scene(db, scene_id, user_id)

    total: int | None = None
    if include_total:
        total = int(
            (
                await db.execute(select(func.count(Hotspot.id)).where(Hotspot.scene_id == scene_id))
            ).scalar_one()
        )
    query = select(Hotspot).where(Hotspot.scene_id == scene_id)
    predicate = keyset_filter(Hotspot.order_index, Hotspot.id, cursor_payload, descending=False)
    if predicate is not None:
        query = query.where(predicate)
    query = query.order_by(Hotspot.order_index, Hotspot.id).limit(limit + 1)

    rows = list((await db.execute(query)).scalars().all())
    items, next_payload = trim_keyset_lookahead(
        rows,
        limit=limit,
        sort_value=lambda hotspot: hotspot.order_index,
        item_id=lambda hotspot: hotspot.id,
    )
    return items, next_payload, total


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


async def _check_navigation_target(
    db: AsyncSession, scene: Scene, target_scene_id: str | None, user_id: int
) -> None:
    if not target_scene_id:
        raise BadRequestException(detail="Navigation hotspots require target_scene_id")
    target_scene = await get_scene(db, target_scene_id, user_id)
    if target_scene.tour_id != scene.tour_id:
        raise BadRequestException(detail="Navigation hotspots must target a scene in the same tour")


async def create_hotspot(
    db: AsyncSession, scene_id: str, user_id: int, data: HotspotCreate
) -> Hotspot:
    """Create a new hotspot in a scene."""
    scene = await get_scene(db, scene_id, user_id)
    _ensure_scene_ownership(scene, user_id, "add hotspots to")

    if data.type == HotspotType.navigation:
        await _check_navigation_target(db, scene, data.target_scene_id, user_id)

    # Content is already typed by the schema. Storage keeps only the declared keys.
    stored_content = content_to_storage(data.type, data.content)

    max_order_query = select(func.max(Hotspot.order_index)).where(Hotspot.scene_id == scene_id)
    result = await db.execute(max_order_query)
    max_order = result.scalar()
    max_order = -1 if max_order is None else max_order  # 0 is a real order, not "empty"

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
        icon_size=data.icon_size,
        content=stored_content,
        custom_data=data.custom_data,
        order_index=max_order + 1,  # server-owned
    )

    db.add(hotspot)
    await db.commit()
    await db.refresh(hotspot)

    logger.info("Hotspot created: %s in scene %s", hotspot.id, scene_id)
    return hotspot


async def update_hotspot(
    db: AsyncSession, hotspot_id: str, user_id: int, data: HotspotUpdate
) -> Hotspot:
    """Update a hotspot. Explicit nulls clear nullable fields."""
    hotspot = await get_hotspot(db, hotspot_id, user_id)
    scene = hotspot.scene  # Already eager-loaded by get_hotspot
    sent = data.model_fields_set

    next_type: HotspotType = (
        data.type if (data.type is not None and "type" in sent) else hotspot.type
    )
    type_changed = next_type != hotspot.type

    if next_type == HotspotType.navigation:
        next_target = data.target_scene_id if "target_scene_id" in sent else hotspot.target_scene_id
        await _check_navigation_target(db, scene, next_target, user_id)
    else:
        next_target = None

    # Content: the sent value, else the stored value when the type did not change.
    if "content" in sent:
        content_source: Any = data.content
    elif type_changed:
        content_source = None
    else:
        # Rows written before the typed contract may carry a server-added "kind" key.
        content_source = {k: v for k, v in (hotspot.content or {}).items() if k != "kind"} or None
    stored_content = content_to_storage(next_type, content_source)

    if "type" in sent:
        hotspot.type = next_type
    if "position" in sent and data.position is not None:
        hotspot.position = data.position.model_dump()
    hotspot.target_scene_id = next_target
    for field in ("title", "description", "icon", "icon_name", "icon_color", "custom_data"):
        if field in sent:
            setattr(hotspot, field, getattr(data, field))
    if "icon_size" in sent and data.icon_size is not None:
        hotspot.icon_size = data.icon_size
    if "is_active" in sent and data.is_active is not None:
        hotspot.is_active = data.is_active
    hotspot.content = stored_content

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


__all__ = [
    "create_hotspot",
    "delete_hotspot",
    "get_hotspot",
    "get_hotspots",
    "get_hotspots_page",
    "update_hotspot",
    "update_hotspot_position",
]
