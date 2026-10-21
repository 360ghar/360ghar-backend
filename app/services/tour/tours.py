"""
Tour CRUD service functions.

Create, read, update, delete, publish, unpublish, and duplicate tours.
Status changes go through publish, unpublish and delete only.
"""

from __future__ import annotations

import secrets
from typing import Any
from uuid import uuid4

from pydantic import ValidationError
from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import (
    BadRequestException,
    TourNotFoundException,
    client_input_error,
)
from app.core.logging import get_logger
from app.core.utils import utc_now
from app.models.enums import TourStatus, TourVisibility
from app.models.tours import FloorPlan, Hotspot, Scene, Tour
from app.schemas.pagination import keyset_filter, keyset_payload, keyset_sort_value
from app.schemas.tour import (
    PublicScene,
    PublicTourWithScenes,
    TourCreate,
    TourSettings,
    TourUpdate,
)
from app.services.tour.helpers import _ensure_tour_ownership, drop_keys, merge_json

logger = get_logger(__name__)

# Unambiguous lowercase alphabet for short share codes (no 0/o/1/l/i).
_SHORT_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"
_SHORT_CODE_LENGTH = 6
_SHORT_CODE_MAX_ATTEMPTS = 5


async def generate_short_code(db: AsyncSession) -> str:
    """Generate a unique 6-char short share code for a tour.

    Retries up to 5 times on collision (checked via SELECT; the partial
    unique index on tours.short_code is the hard guarantee).
    """
    for _ in range(_SHORT_CODE_MAX_ATTEMPTS):
        code = "".join(secrets.choice(_SHORT_ALPHABET) for _ in range(_SHORT_CODE_LENGTH))
        exists = (
            await db.execute(select(Tour.id).where(Tour.short_code == code))
        ).scalar_one_or_none()
        if exists is None:
            return code
    raise RuntimeError("Could not generate a unique tour short code after 5 attempts")


def _tour_row(tour: Tour, scene_count: int) -> dict[str, Any]:
    """Row dict for a list item. Keeps list and detail responses on the same fields."""
    return {
        "id": tour.id,
        "user_id": tour.user_id,
        "title": tour.title,
        "description": tour.description,
        "status": tour.status,
        "is_public": tour.is_public,
        "visibility": tour.visibility,
        "short_code": tour.short_code,
        "is_featured": tour.is_featured,
        "view_count": tour.view_count,
        "like_count": tour.like_count,
        "share_count": tour.share_count,
        "settings": tour.settings,
        "thumbnail_url": tour.thumbnail_url,
        "published_at": tour.published_at,
        "archived_at": tour.archived_at,
        "created_at": tour.created_at,
        "updated_at": tour.updated_at,
        "deleted_at": tour.deleted_at,
        "scene_count": scene_count,
    }


async def get_tours(
    db: AsyncSession,
    user_id: int,
    cursor_payload: dict,
    limit: int = 20,
    with_total: bool = False,
    status_filter: TourStatus | None = None,
    search: str | None = None,
) -> tuple[list[dict[str, Any]], dict | None, int | None]:
    """Get cursor-paginated list of tours for a user."""
    stmt = select(Tour).where(and_(Tour.user_id == user_id, Tour.deleted_at.is_(None)))

    if status_filter is not None:
        stmt = stmt.where(Tour.status == status_filter)

    if search:
        search_term = f"%{search}%"
        stmt = stmt.where(or_(Tour.title.ilike(search_term), Tour.description.ilike(search_term)))

    count_total = None
    if with_total:
        count_total = (
            await db.execute(select(func.count()).select_from(stmt.subquery()))
        ).scalar_one()

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

    tours = [_tour_row(tour, int(scene_count or 0)) for tour, scene_count in rows]
    return tours, next_payload, count_total


async def get_tour(
    db: AsyncSession, tour_id: str, user_id: int | None = None, include_scenes: bool = True
) -> Tour:
    """Get a single tour by ID. With include_scenes, loads scenes, hotspots and floor plans."""
    query = select(Tour).where(and_(Tour.id == tour_id, Tour.deleted_at.is_(None)))

    if include_scenes:
        query = query.options(
            selectinload(Tour.scenes).selectinload(Scene.hotspots),
            selectinload(Tour.floor_plans),
        )

    result = await db.execute(query)
    tour = result.scalar_one_or_none()

    if not tour:
        raise TourNotFoundException()

    is_owner = user_id is not None and tour.user_id == user_id
    is_publicly_accessible = (
        tour.status == TourStatus.published and tour.visibility != TourVisibility.private
    )

    # A tour the caller cannot see is 404, whether or not it exists (no existence leak).
    if not is_owner and not is_publicly_accessible:
        raise TourNotFoundException()

    return tour


def active_hotspots_only(scene: PublicScene) -> PublicScene:
    """A public scene with only its active hotspots. Viewers do not get inactive hotspots."""
    return scene.model_copy(update={"hotspots": [h for h in scene.hotspots if h.is_active]})


def public_tour_view(tour: Tour) -> PublicTourWithScenes:
    """The viewer shape of a tour: no user_id, and scenes with active hotspots only."""
    view = PublicTourWithScenes.model_validate(tour)
    return view.model_copy(update={"scenes": [active_hotspots_only(s) for s in view.scenes]})


def _apply_publish_state(tour: Tour) -> None:
    """Set the publish fields. An unlisted tour stays unlisted. Any other tour becomes public."""
    tour.status = TourStatus.published
    tour.published_at = utc_now()
    if tour.visibility != TourVisibility.unlisted:
        tour.visibility = TourVisibility.public
    tour.is_public = tour.visibility == TourVisibility.public


def _stored_settings(settings: TourSettings | None) -> dict[str, Any] | None:
    """Settings as stored in tours.settings: typed, with None fields left out."""
    return settings.model_dump(exclude_none=True) if settings is not None else None


async def create_tour(db: AsyncSession, user_id: int, data: TourCreate) -> Tour:
    """Create a new tour as a draft."""
    visibility = data.visibility or TourVisibility.private
    # Keep is_public in sync for backward compatibility
    is_public = visibility == TourVisibility.public

    tour = Tour(
        id=str(uuid4()),
        user_id=user_id,
        title=data.title,
        description=data.description,
        status=TourStatus.draft,
        is_public=is_public,
        visibility=visibility,
        settings=_stored_settings(data.settings),
    )

    db.add(tour)
    await db.commit()

    logger.info("Tour created: %s by user %s", tour.id, user_id)
    return await get_tour(db=db, tour_id=tour.id, user_id=user_id, include_scenes=True)


async def update_tour(db: AsyncSession, tour_id: str, user_id: int, data: TourUpdate) -> Tour:
    """Update a tour. Only the fields the client sent change. Settings are deep-merged."""
    tour = await get_tour(db, tour_id, user_id, include_scenes=False)
    _ensure_tour_ownership(tour, user_id, "update")

    update_data = data.model_dump(exclude_unset=True)
    update_data.pop("settings", None)

    # Handle visibility/is_public sync for backward compatibility
    if "visibility" in update_data:
        update_data["is_public"] = update_data["visibility"] == TourVisibility.public
    elif "is_public" in update_data:
        update_data["visibility"] = (
            TourVisibility.public if update_data["is_public"] else TourVisibility.private
        )

    for field, value in update_data.items():
        setattr(tour, field, value)

    if "settings" in data.model_fields_set:
        if data.settings is None:
            tour.settings = None
        else:
            patch = data.settings.model_dump(exclude_unset=True)
            merged = merge_json(drop_keys(tour.settings, set(TourSettings.model_fields)), patch)
            try:
                tour.settings = TourSettings.model_validate(merged).model_dump(exclude_none=True)
            except ValidationError as exc:
                raise client_input_error(exc, "body", "settings") from exc

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
    """Publish a tour. An unlisted tour stays unlisted. Any other tour becomes public."""
    tour = await get_tour(db, tour_id, user_id, include_scenes=True)
    _ensure_tour_ownership(tour, user_id, "publish")

    # Check if tour has scenes
    if not tour.scenes:
        raise BadRequestException(detail="Cannot publish a tour without scenes")

    _apply_publish_state(tour)

    # Assign a short share code on first publish; never cleared on unpublish
    # so existing /v/{code} links keep working after a republish.
    if not tour.short_code:
        tour.short_code = await generate_short_code(db)
    try:
        await db.commit()
    except IntegrityError:
        # Race on short_code unique index: regenerate once and retry.
        await db.rollback()
        tour = await get_tour(db, tour_id, user_id, include_scenes=True)
        _apply_publish_state(tour)
        tour.short_code = await generate_short_code(db)
        await db.commit()

    logger.info("Tour published: %s", tour_id)
    return await get_tour(db=db, tour_id=tour_id, user_id=user_id, include_scenes=True)


async def unpublish_tour(db: AsyncSession, tour_id: str, user_id: int) -> Tour:
    """Unpublish a tour (set to draft). An unlisted tour stays unlisted; any other becomes private."""
    tour = await get_tour(db, tour_id, user_id, include_scenes=False)
    _ensure_tour_ownership(tour, user_id, "unpublish")

    tour.status = TourStatus.draft
    if tour.visibility != TourVisibility.unlisted:
        tour.visibility = TourVisibility.private
    tour.is_public = tour.visibility == TourVisibility.public

    await db.commit()

    logger.info("Tour unpublished: %s", tour_id)
    return await get_tour(db=db, tour_id=tour_id, user_id=user_id, include_scenes=True)


async def duplicate_tour(db: AsyncSession, tour_id: str, user_id: int) -> Tour:
    """Duplicate a tour with its scenes, hotspots and floor plans."""
    original = await get_tour(db, tour_id, user_id, include_scenes=True)
    _ensure_tour_ownership(original, user_id, "duplicate")

    new_tour = Tour(
        id=str(uuid4()),
        user_id=user_id,
        title=f"{original.title} (Copy)",
        description=original.description,
        status=TourStatus.draft,
        is_public=original.visibility == TourVisibility.public,
        visibility=original.visibility,
        settings=original.settings,
        thumbnail_url=original.thumbnail_url,
    )
    db.add(new_tour)

    # Map old scene IDs to new scene IDs for hotspot targets
    scene_id_map: dict[str, str] = {}

    for scene in original.scenes or []:
        new_scene_id = str(uuid4())
        scene_id_map[scene.id] = new_scene_id
        db.add(
            Scene(
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
        )

    await db.flush()

    for scene in original.scenes or []:
        for hotspot in scene.hotspots or []:
            db.add(
                Hotspot(
                    id=str(uuid4()),
                    scene_id=scene_id_map[scene.id],
                    type=hotspot.type,
                    position=hotspot.position,
                    target_scene_id=scene_id_map.get(hotspot.target_scene_id or ""),
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
            )

    for plan in original.floor_plans or []:
        db.add(
            FloorPlan(
                id=str(uuid4()),
                tour_id=new_tour.id,
                name=plan.name,
                image_url=plan.image_url,
                floor_number=plan.floor_number,
                markers=[dict(marker) for marker in (plan.markers or [])],
            )
        )

    await db.commit()

    return await get_tour(db, new_tour.id, user_id, include_scenes=True)


__all__: list[str] = [
    "create_tour",
    "delete_tour",
    "duplicate_tour",
    "generate_short_code",
    "get_tour",
    "get_tours",
    "publish_tour",
    "unpublish_tour",
    "update_tour",
]
