"""AI hotspot suggestion functions for tour operations.

Provides AI-powered hotspot placement suggestions for individual scenes
and entire tours, including navigation and information hotspot generation.
"""
from __future__ import annotations

import asyncio
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_bg_session_factory
from app.core.exceptions import BadRequestException, ForbiddenException
from app.core.logging import get_logger
from app.models.tours import AIJob
from app.services.ai import AIMessage, AIProviderError, AIRole, VisionInput

from .helpers import (
    _build_hotspot_suggestion_prompt,
    _complete_json_with_retry,
    _download_image_as_base64,
    _get_ai_provider_safe,
    _run_with_semaphore,
)
from .jobs import create_ai_job, update_job_status

logger = get_logger(__name__)


async def suggest_scene_hotspots(
    db: AsyncSession,
    scene_id: str,
    user_id: int
) -> AIJob:
    """Suggest hotspots for a scene using AI."""
    from app.services.tour import get_scene, get_scenes

    scene = await get_scene(db, scene_id, user_id)

    if scene.tour.user_id != user_id:
        raise ForbiddenException(detail="Access denied")

    # Get all scenes in the tour for navigation suggestions
    await get_scenes(db, scene.tour_id, user_id)

    # Create job
    job = await create_ai_job(db, user_id, "suggest_hotspots", scene_id=scene_id)

    # Run suggestion in background - pass only IDs and required data
    asyncio.create_task(_run_with_semaphore(_run_hotspot_suggestions(job.id, scene_id, scene.tour_id)))

    return job


async def suggest_tour_hotspots(
    db: AsyncSession,
    tour_id: str,
    user_id: int
) -> AIJob:
    """Suggest hotspots for all scenes in a tour using AI."""
    from app.services.tour import get_tour

    tour = await get_tour(db, tour_id, user_id, include_scenes=True)

    if tour.user_id != user_id:
        raise ForbiddenException(detail="Access denied")

    if not tour.scenes or len(tour.scenes) < 2:
        raise BadRequestException(detail="Tour needs at least 2 scenes for hotspot suggestions")

    # Create job
    job = await create_ai_job(db, user_id, "suggest_tour_hotspots", tour_id=tour_id)

    # Run suggestion in background - pass only tour_id
    asyncio.create_task(_run_with_semaphore(_run_tour_hotspot_suggestions(job.id, tour_id)))

    return job


async def _run_hotspot_suggestions(job_id: str, scene_id: str, tour_id: str):
    """Generate hotspot suggestions for a scene.

    Creates its own database session for the background task.
    """
    from app.models.tours import Scene

    session_factory = get_bg_session_factory()
    async with session_factory() as db:
        try:
            await update_job_status(db, job_id, "processing", 10)

            # Re-fetch scene in this session
            scene_result = await db.execute(
                select(Scene).where(Scene.id == scene_id)
            )
            scene = scene_result.scalar_one_or_none()
            if not scene:
                await update_job_status(db, job_id, "failed", error_message="Scene not found")
                await db.commit()
                return

            # Fetch all scenes in the tour
            scenes_result = await db.execute(
                select(Scene).where(Scene.tour_id == tour_id).order_by(Scene.order_index)
            )
            all_scenes = list(scenes_result.scalars().all())

            provider = await _get_ai_provider_safe()

            # Download and encode image
            image_base64, mime_type = await _download_image_as_base64(scene.image_url)
            vision_input = VisionInput(image_base64=image_base64, mime_type=mime_type)

            await update_job_status(db, job_id, "processing", 30)

            # Build scene context
            other_scenes = [s for s in all_scenes if s.id != scene.id]
            scene_context = "\n".join([
                f"- {s.title or f'Scene {i+1}'} (ID: {s.id})"
                for i, s in enumerate(other_scenes)
            ])

            system_prompt = _build_hotspot_suggestion_prompt(scene_context, full_format=True)

            messages = [
                AIMessage(role=AIRole.SYSTEM, content=system_prompt),
                AIMessage(role=AIRole.USER, content="Suggest hotspot placements for this 360° panorama.")
            ]

            await update_job_status(db, job_id, "processing", 60)

            result = await _complete_json_with_retry(provider, messages, vision_input)

            # Process hotspots and add IDs
            hotspots = result.get("hotspots", [])
            for hotspot in hotspots:
                hotspot["id"] = str(uuid4())
                hotspot["position"] = {
                    "yaw": hotspot.pop("yaw", 0),
                    "pitch": hotspot.pop("pitch", 0)
                }

            await update_job_status(db, job_id, "completed", 100, result={"hotspots": hotspots})
            await db.commit()
            logger.info("Hotspot suggestions completed for scene %s", scene_id)

        except AIProviderError as e:
            logger.error("AI provider error during hotspot suggestions: %s", e, exc_info=True)
            await update_job_status(db, job_id, "failed", error_message=str(e))
            await db.commit()
        except Exception as e:
            logger.error("Error during hotspot suggestions: %s", e, exc_info=True)
            await update_job_status(db, job_id, "failed", error_message=str(e))
            await db.commit()


async def _run_tour_hotspot_suggestions(job_id: str, tour_id: str):
    """Generate hotspot suggestions for all scenes in a tour.

    Creates its own database session for the background task.
    """
    from app.models.tours import Scene

    session_factory = get_bg_session_factory()
    async with session_factory() as db:
        try:
            await update_job_status(db, job_id, "processing", 5)

            # Fetch scenes in this session
            scenes_result = await db.execute(
                select(Scene).where(Scene.tour_id == tour_id).order_by(Scene.order_index)
            )
            scenes = list(scenes_result.scalars().all())

            all_hotspots = []

            for i, scene in enumerate(scenes):
                progress = int(5 + (90 * (i + 1) / len(scenes)))

                try:
                    provider = await _get_ai_provider_safe()

                    # Download and encode image
                    image_base64, mime_type = await _download_image_as_base64(scene.image_url)
                    vision_input = VisionInput(image_base64=image_base64, mime_type=mime_type)

                    # Build scene context
                    other_scenes = [s for s in scenes if s.id != scene.id]
                    scene_context = "\n".join([
                        f"- {s.title or f'Scene {j+1}'} (ID: {s.id})"
                        for j, s in enumerate(other_scenes)
                    ])

                    system_prompt = _build_hotspot_suggestion_prompt(scene_context, full_format=False)

                    messages = [
                        AIMessage(role=AIRole.SYSTEM, content=system_prompt),
                        AIMessage(role=AIRole.USER, content="Suggest hotspot placements for this 360° panorama.")
                    ]

                    result = await _complete_json_with_retry(provider, messages, vision_input)

                    hotspots = result.get("hotspots", [])
                    for hotspot in hotspots:
                        hotspot["id"] = str(uuid4())
                        hotspot["scene_id"] = scene.id
                        hotspot["position"] = {
                            "yaw": hotspot.pop("yaw", 0),
                            "pitch": hotspot.pop("pitch", 0)
                        }
                        all_hotspots.append(hotspot)

                except Exception as e:
                    logger.error("Error suggesting hotspots for scene %s: %s", scene.id, e, exc_info=True)

                await update_job_status(db, job_id, "processing", progress)

            await update_job_status(db, job_id, "completed", 100, result={"hotspots": all_hotspots})
            await db.commit()
            logger.info("Tour hotspot suggestions completed for tour %s", tour_id)

        except Exception as e:
            logger.error("Error during tour hotspot suggestions: %s", e, exc_info=True)
            await update_job_status(db, job_id, "failed", error_message=str(e))
            await db.commit()
