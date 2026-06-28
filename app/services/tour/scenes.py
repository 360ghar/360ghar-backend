"""
Scene CRUD service functions.

Create, read, update, delete, reorder scenes, and schedule
background image processing.
"""

from __future__ import annotations

import asyncio
from uuid import uuid4

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import (
    BadRequestException,
    ForbiddenException,
    SceneNotFoundException,
)
from app.core.logging import get_logger
from app.models.tours import Scene
from app.schemas.tour import SceneCreate, SceneUpdate
from app.services.tour.helpers import (
    _ensure_scene_ownership,
    _ensure_tour_ownership,
    _register_scene_processing_task,
    _scene_processing_tasks,
)
from app.services.tour.tours import get_tour
from app.utils.validators import ValidationUtils

logger = get_logger(__name__)


async def get_scenes(db: AsyncSession, tour_id: str, user_id: int | None = None) -> list[Scene]:
    """Get all scenes for a tour."""
    # Verify tour access
    await get_tour(db, tour_id, user_id, include_scenes=False)

    query = (
        select(Scene)
        .where(Scene.tour_id == tour_id)
        .options(selectinload(Scene.hotspots))
        .order_by(Scene.order_index)
    )

    result = await db.execute(query)
    return list(result.scalars().all())


async def get_scene(db: AsyncSession, scene_id: str, user_id: int | None = None) -> Scene:
    """Get a single scene by ID."""
    query = (
        select(Scene)
        .where(Scene.id == scene_id)
        .options(selectinload(Scene.hotspots), selectinload(Scene.tour))
    )

    result = await db.execute(query)
    scene = result.scalar_one_or_none()

    if not scene:
        raise SceneNotFoundException()

    if user_id is not None and scene.tour.user_id != user_id:
        raise ForbiddenException(detail="You don't have access to this scene")

    return scene


async def create_scene(db: AsyncSession, tour_id: str, user_id: int, data: SceneCreate) -> Scene:
    """Create a new scene in a tour."""
    tour = await get_tour(db, tour_id, user_id, include_scenes=False)
    _ensure_tour_ownership(tour, user_id, "add scenes to")

    # Get max order_index
    max_order_query = select(func.max(Scene.order_index)).where(Scene.tour_id == tour_id)
    result = await db.execute(max_order_query)
    max_order = result.scalar() or -1

    image_url = data.image_url
    thumbnail_url = data.thumbnail_url

    if image_url and not ValidationUtils.is_absolute_url(image_url):
        logger.warning("Non-absolute image_url for scene in tour %s: %s", tour_id, image_url)
    if thumbnail_url and not ValidationUtils.is_absolute_url(thumbnail_url):
        logger.warning("Non-absolute thumbnail_url for scene in tour %s: %s", tour_id, thumbnail_url)

    scene = Scene(
        id=str(uuid4()),
        tour_id=tour_id,
        title=data.title,
        description=data.description,
        image_url=image_url,
        thumbnail_url=thumbnail_url,
        order_index=data.order_index if data.order_index is not None else max_order + 1,
        scene_metadata=data.metadata.model_dump() if data.metadata else None,
        is_processed=False,  # Will be set to True after background processing
    )

    db.add(scene)
    await db.commit()

    # Schedule background processing for thumbnail generation
    if data.image_url and not data.thumbnail_url:
        schedule_scene_processing(
            scene_id=scene.id,
            tour_id=tour_id,
            image_url=data.image_url,
            user_id=user_id,
        )
    else:
        # Mark as processed if thumbnail already provided
        scene.is_processed = True
        await db.commit()

    logger.info("Scene created: %s in tour %s", scene.id, tour_id)
    return await get_scene(db=db, scene_id=scene.id, user_id=user_id)


async def update_scene(db: AsyncSession, scene_id: str, user_id: int, data: SceneUpdate) -> Scene:
    """Update a scene."""
    scene = await get_scene(db, scene_id, user_id)
    _ensure_scene_ownership(scene, user_id, "update")

    update_data = data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        if field in ("image_url", "thumbnail_url") and value is not None and not ValidationUtils.is_absolute_url(value):
            logger.warning("Non-absolute %s for scene %s: %s", field, scene_id, value)
        if field == "metadata" and value is not None:
            value = value if isinstance(value, dict) else value.model_dump()
            scene.scene_metadata = value
        else:
            setattr(scene, field, value)

    await db.commit()

    logger.info("Scene updated: %s", scene_id)
    return await get_scene(db=db, scene_id=scene_id, user_id=user_id)


async def delete_scene(db: AsyncSession, scene_id: str, user_id: int) -> bool:
    """Delete a scene."""
    scene = await get_scene(db, scene_id, user_id)
    _ensure_scene_ownership(scene, user_id, "delete")

    await db.delete(scene)
    await db.commit()

    logger.info("Scene deleted: %s", scene_id)
    return True


async def reorder_scenes(
    db: AsyncSession, tour_id: str, user_id: int, scene_ids: list[str]
) -> list[Scene]:
    """Reorder scenes in a tour."""
    tour = await get_tour(db, tour_id, user_id, include_scenes=False)
    _ensure_tour_ownership(tour, user_id, "reorder scenes in")

    # Validation: Check for duplicates
    if len(scene_ids) != len(set(scene_ids)):
        raise BadRequestException(detail="Duplicate scene_ids found in reorder request")

    # Get all existing scenes for this tour
    existing_scenes_query = select(Scene.id).where(Scene.tour_id == tour_id)
    result = await db.execute(existing_scenes_query)
    existing_scene_ids = set(result.scalars().all())

    # Validation: Check all provided scene_ids exist and belong to this tour
    provided_scene_ids = set(scene_ids)
    invalid_scene_ids = provided_scene_ids - existing_scene_ids
    if invalid_scene_ids:
        raise BadRequestException(
            detail=f"Invalid scene_ids: {list(invalid_scene_ids)}. Scenes must exist and belong to this tour."
        )

    # Validation: Check all scenes in the tour are included
    missing_scene_ids = existing_scene_ids - provided_scene_ids
    if missing_scene_ids:
        raise BadRequestException(
            detail=f"Missing scene_ids: {list(missing_scene_ids)}. All tour scenes must be included in reorder request."
        )

    # Update order_index for each scene
    for index, scene_id in enumerate(scene_ids):
        query = select(Scene).where(and_(Scene.id == scene_id, Scene.tour_id == tour_id))
        result = await db.execute(query)
        scene_obj = result.scalar_one_or_none()

        if scene_obj is not None and hasattr(scene_obj, 'order_index'):
            scene_obj.order_index = index

    await db.commit()

    # Return reordered scenes
    return await get_scenes(db, tour_id, user_id)


# ---------------------------------------------------------------------------
# Scene image processing (background tasks)
# ---------------------------------------------------------------------------


async def process_scene_image_background(
    scene_id: str,
    tour_id: str,
    image_url: str,
    user_id: int,
) -> None:
    """
    Background task to process a scene image and generate thumbnails.

    This function runs asynchronously after scene creation to generate
    thumbnails and extract metadata without blocking the API response.

    Args:
        scene_id: The scene ID
        tour_id: The tour ID
        image_url: URL of the scene image
        user_id: User ID for user-scoped storage paths
    """
    from app.core.database import get_bg_session_factory
    from app.services.storage import storage_service

    try:
        logger.info("Starting background processing for scene %s", scene_id)

        # Process the image with user-scoped path
        result = await storage_service.process_existing_scene_image(
            image_url=image_url,
            tour_id=tour_id,
            scene_id=scene_id,
            user_id=user_id,
        )

        # Create a new database session for the background task
        session_factory = get_bg_session_factory()
        async with session_factory() as db:
            # Update the scene with the processed data
            query = select(Scene).where(Scene.id == scene_id)
            db_result = await db.execute(query)
            scene = db_result.scalar_one_or_none()

            if scene:
                if result.get("thumbnail_url"):
                    scene.thumbnail_url = result["thumbnail_url"]

                # Update metadata with EXIF info
                current_metadata = scene.scene_metadata or {}
                if result.get("exif"):
                    current_metadata["exif"] = result["exif"]
                if result.get("width") and result.get("height"):
                    current_metadata["dimensions"] = {
                        "width": result["width"],
                        "height": result["height"],
                    }
                if result.get("is_panorama") is not None:
                    current_metadata["is_panorama"] = result["is_panorama"]

                scene.scene_metadata = current_metadata
                scene.is_processed = True

                await db.commit()
                logger.info("Scene %s processed successfully", scene_id)
            else:
                logger.warning("Scene %s not found during processing", scene_id)

    except Exception as e:
        logger.error("Failed to process scene %s: %s", scene_id, e)
        # Mark scene as failed
        try:
            session_factory = get_bg_session_factory()
            async with session_factory() as db:
                query = select(Scene).where(Scene.id == scene_id)
                db_result = await db.execute(query)
                scene = db_result.scalar_one_or_none()
                if scene:
                    scene.is_processed = True
                    scene.processing_error = str(e)
                    await db.commit()
        except Exception as inner_e:
            logger.error("Failed to update scene processing error: %s", inner_e)
    finally:
        # Clean up task registry
        _scene_processing_tasks.pop(scene_id, None)


def schedule_scene_processing(
    scene_id: str,
    tour_id: str,
    image_url: str,
    user_id: int,
) -> None:
    """
    Schedule a scene for background processing.

    Args:
        scene_id: The scene ID
        tour_id: The tour ID
        image_url: URL of the scene image
        user_id: User ID for user-scoped storage paths
    """
    if not image_url:
        logger.warning("No image URL provided for scene %s", scene_id)
        return

    # Avoid duplicate processing
    if scene_id in _scene_processing_tasks:
        logger.info("Scene %s already being processed", scene_id)
        return

    # Schedule the background task
    task = asyncio.create_task(
        process_scene_image_background(
            scene_id=scene_id,
            tour_id=tour_id,
            image_url=image_url,
            user_id=user_id,
        )
    )
    _register_scene_processing_task(scene_id, task)
    logger.info("Scheduled processing for scene %s", scene_id)
