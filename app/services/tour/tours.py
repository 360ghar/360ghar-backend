"""
Tour CRUD service functions.

Create, read, update, delete, publish, unpublish, and duplicate tours.
"""
from __future__ import annotations

from uuid import uuid4

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import (
    BadRequestException,
    ForbiddenException,
    TourNotFoundException,
)
from app.core.logging import get_logger
from app.core.utils import utc_now
from app.models.enums import TourStatus, TourVisibility
from app.models.tours import Scene, Tour
from app.schemas.pagination import keyset_filter, keyset_payload, keyset_sort_value
from app.schemas.tour import TourCreate, TourUpdate
from app.services.tour.helpers import _ensure_tour_ownership

logger = get_logger(__name__)


async def get_tours(
    db: AsyncSession,
    user_id: int,
    cursor_payload: dict,
    limit: int = 20,
    with_total: bool = False,
    status_filter: str | None = None,
    search: str | None = None,
) -> tuple[list, dict | None, int | None]:
    """Get cursor-paginated list of tours for a user."""
    stmt = select(Tour).where(and_(Tour.user_id == user_id, Tour.deleted_at.is_(None)))

    if status_filter:
        stmt = stmt.where(Tour.status == status_filter)

    if search:
        search_term = f"%{search}%"
        stmt = stmt.where(or_(Tour.title.ilike(search_term), Tour.description.ilike(search_term)))

    count_total = None
    if with_total:
        count_total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()

    predicate = keyset_filter(Tour.created_at, Tour.id, cursor_payload, descending=True)
    if predicate is not None:
        stmt = stmt.where(predicate)

    scene_counts = (
        select(
            Scene.tour_id.label("tour_id"),
            func.count(Scene.id).label("scene_count"),
        )
        .group_by(Scene.tour_id)
        .subquery()
    )

    stmt = (
        stmt.outerjoin(scene_counts, scene_counts.c.tour_id == Tour.id)
        .add_columns(func.coalesce(scene_counts.c.scene_count, 0).label("scene_count"))
        .order_by(Tour.created_at.desc(), Tour.id.desc())
        .limit(limit + 1)
    )

    rows = (await db.execute(stmt)).all()

    next_payload = None
    if len(rows) > limit:
        rows = rows[:limit]
        last_tour, _ = rows[-1]
        next_payload = keyset_payload(keyset_sort_value(last_tour.created_at), last_tour.id)

    tours = []
    for tour, scene_count in rows:
        tours.append({
            "id": tour.id,
            "user_id": tour.user_id,
            "title": tour.title,
            "description": tour.description,
            "status": tour.status,
            "is_public": tour.is_public,
            "settings": tour.settings,
            "is_featured": tour.is_featured,
            "view_count": tour.view_count,
            "like_count": tour.like_count,
            "share_count": tour.share_count,
            "thumbnail_url": tour.thumbnail_url,
            "published_at": tour.published_at,
            "archived_at": tour.archived_at,
            "created_at": tour.created_at,
            "updated_at": tour.updated_at,
            "deleted_at": tour.deleted_at,
            "scene_count": int(scene_count or 0),
            "scenes": None,
            "visibility": tour.visibility,
        })

    return tours, next_payload, count_total


async def get_tour(
    db: AsyncSession, tour_id: str, user_id: int | None = None, include_scenes: bool = True
) -> Tour:
    """Get a single tour by ID."""
    query = select(Tour).where(and_(Tour.id == tour_id, Tour.deleted_at.is_(None)))

    if include_scenes:
        query = query.options(selectinload(Tour.scenes).selectinload(Scene.hotspots))

    result = await db.execute(query)
    tour = result.scalar_one_or_none()

    if not tour:
        raise TourNotFoundException()

    is_owner = user_id is not None and tour.user_id == user_id
    is_publicly_accessible = (
        tour.status == TourStatus.published
        and tour.visibility != TourVisibility.private
    )

    if not is_owner and not is_publicly_accessible:
        if user_id is not None:
            raise ForbiddenException(detail="You don't have access to this tour")
        else:
            raise TourNotFoundException()

    return tour


async def create_tour(db: AsyncSession, user_id: int, data: TourCreate) -> Tour:
    """Create a new tour."""
    # Determine visibility - prefer explicit visibility, fall back to is_public for backward compat
    visibility = (
        data.visibility
        if data.visibility
        else (TourVisibility.public if data.is_public else TourVisibility.private)
    )
    # Keep is_public in sync for backward compatibility
    is_public = visibility == TourVisibility.public

    tour = Tour(
        id=str(uuid4()),
        user_id=user_id,
        title=data.title,
        description=data.description,
        status=data.status or TourStatus.draft,
        is_public=is_public,
        visibility=visibility,
        settings=data.settings.model_dump() if data.settings else None,
    )

    db.add(tour)
    await db.commit()

    logger.info("Tour created: %s by user %s", tour.id, user_id)
    return await get_tour(db=db, tour_id=tour.id, user_id=user_id, include_scenes=True)


async def update_tour(db: AsyncSession, tour_id: str, user_id: int, data: TourUpdate) -> Tour:
    """Update a tour."""
    tour = await get_tour(db, tour_id, user_id, include_scenes=False)
    _ensure_tour_ownership(tour, user_id, "update")

    # Update fields
    update_data = data.model_dump(exclude_unset=True)

    # Handle visibility/is_public sync for backward compatibility
    if "visibility" in update_data:
        # If visibility is set, sync is_public
        update_data["is_public"] = update_data["visibility"] == TourVisibility.public
    elif "is_public" in update_data:
        # If only is_public is set (legacy), derive visibility
        update_data["visibility"] = (
            TourVisibility.public if update_data["is_public"] else TourVisibility.private
        )

    for field, value in update_data.items():
        if field == "settings" and value is not None:
            value = value if isinstance(value, dict) else value.model_dump()
        setattr(tour, field, value)

    await db.commit()

    logger.info("Tour updated: %s", tour_id)
    return await get_tour(db=db, tour_id=tour_id, user_id=user_id, include_scenes=True)


async def delete_tour(db: AsyncSession, tour_id: str, user_id: int) -> bool:
    """Soft delete a tour."""
    tour = await get_tour(db, tour_id, user_id, include_scenes=False)
    _ensure_tour_ownership(tour, user_id, "delete")

    tour.deleted_at = utc_now()
    tour.status = TourStatus.archived
    await db.commit()

    logger.info("Tour deleted: %s", tour_id)
    return True


async def publish_tour(db: AsyncSession, tour_id: str, user_id: int) -> Tour:
    """Publish a tour."""
    tour = await get_tour(db, tour_id, user_id, include_scenes=True)
    _ensure_tour_ownership(tour, user_id, "publish")

    # Check if tour has scenes
    if not tour.scenes:
        raise BadRequestException(detail="Cannot publish a tour without scenes")

    tour.status = TourStatus.published
    tour.published_at = utc_now()
    tour.visibility = TourVisibility.public
    tour.is_public = True

    await db.commit()

    logger.info("Tour published: %s", tour_id)
    return await get_tour(db=db, tour_id=tour_id, user_id=user_id, include_scenes=True)


async def unpublish_tour(db: AsyncSession, tour_id: str, user_id: int) -> Tour:
    """Unpublish a tour (set to draft)."""
    tour = await get_tour(db, tour_id, user_id, include_scenes=False)
    _ensure_tour_ownership(tour, user_id, "unpublish")

    tour.status = TourStatus.draft
    tour.visibility = TourVisibility.private
    tour.is_public = False

    await db.commit()

    logger.info("Tour unpublished: %s", tour_id)
    return await get_tour(db=db, tour_id=tour_id, user_id=user_id, include_scenes=True)


async def duplicate_tour(db: AsyncSession, tour_id: str, user_id: int) -> Tour:
    """Duplicate a tour with all its scenes and hotspots."""
    original = await get_tour(db, tour_id, user_id, include_scenes=True)
    _ensure_tour_ownership(original, user_id, "duplicate")

    # Create new tour
    new_tour = Tour(
        id=str(uuid4()),
        user_id=user_id,
        title=f"{original.title} (Copy)",
        description=original.description,
        status=TourStatus.draft,
        is_public=False,
        visibility=original.visibility,
        settings=original.settings,
        thumbnail_url=original.thumbnail_url,
    )
    db.add(new_tour)

    # Map old scene IDs to new scene IDs for hotspot targets
    scene_id_map = {}

    # Duplicate scenes
    for scene in original.scenes or []:
        new_scene_id = str(uuid4())
        scene_id_map[scene.id] = new_scene_id

        new_scene = Scene(
            id=new_scene_id,
            tour_id=new_tour.id,
            title=scene.title,
            description=scene.description,
            image_url=scene.image_url,
            thumbnail_url=scene.thumbnail_url,
            order_index=scene.order_index,
            scene_metadata=scene.scene_metadata,
            is_processed=scene.is_processed,
        )
        db.add(new_scene)

    await db.flush()

    # Duplicate hotspots
    for scene in original.scenes or []:
        for hotspot in scene.hotspots or []:
            new_target_scene_id = None
            if hotspot.target_scene_id:
                new_target_scene_id = scene_id_map.get(hotspot.target_scene_id)

            from app.models.tours import Hotspot

            new_hotspot = Hotspot(
                id=str(uuid4()),
                scene_id=scene_id_map[scene.id],
                type=hotspot.type,
                position=hotspot.position,
                target_scene_id=new_target_scene_id,
                title=hotspot.title,
                description=hotspot.description,
                icon=hotspot.icon,
                icon_name=hotspot.icon_name,
                icon_color=hotspot.icon_color,
                icon_size=hotspot.icon_size,
                content=hotspot.content,
                custom_data=hotspot.custom_data,
                order_index=hotspot.order_index,
                is_active=hotspot.is_active,
            )
            db.add(new_hotspot)

    await db.commit()

    # Reload with scenes
    return await get_tour(db, new_tour.id, user_id, include_scenes=True)
