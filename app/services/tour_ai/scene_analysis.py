"""Scene analysis and description generation for tour AI operations.

Provides AI-powered scene analysis (room type, quality scoring) and
description generation for individual scenes and entire tours.
"""
from __future__ import annotations

import asyncio
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_bg_session_factory
from app.core.exceptions import BadRequestException, ForbiddenException
from app.core.logging import get_logger
from app.models.tours import AIJob
from app.services.ai import AIMessage, AIProviderError, AIRole, VisionInput

from .helpers import (
    SCENE_ANALYSIS_PROMPT,
    _complete_json_with_retry,
    _download_image_as_base64,
    _get_ai_provider_safe,
    _run_with_semaphore,
)
from .jobs import create_ai_job, update_job_status

logger = get_logger(__name__)


# ====================
# Scene Analysis
# ====================

async def analyze_scene(
    db: AsyncSession,
    scene_id: str,
    user_id: int
) -> AIJob:
    """Analyze a single scene using AI."""
    from app.services.tour import get_scene

    scene = await get_scene(db, scene_id, user_id)

    if scene.tour.user_id != user_id:
        raise ForbiddenException(detail="Access denied")

    # Create job
    job = await create_ai_job(db, user_id, "analyze_scene", scene_id=scene_id)

    # Run analysis in background - pass only IDs, not ORM objects
    asyncio.create_task(_run_with_semaphore(_run_scene_analysis(job.id, scene_id, scene.image_url)))

    return job


async def analyze_tour_scenes(
    db: AsyncSession,
    tour_id: str,
    user_id: int
) -> AIJob:
    """Analyze all scenes in a tour using AI."""
    from app.services.tour import get_tour

    tour = await get_tour(db, tour_id, user_id, include_scenes=True)

    if tour.user_id != user_id:
        raise ForbiddenException(detail="Access denied")

    if not tour.scenes:
        raise BadRequestException(detail="Tour has no scenes to analyze")

    # Create job
    job = await create_ai_job(db, user_id, "analyze_scenes", tour_id=tour_id)

    # Run analysis in background - pass only tour_id
    asyncio.create_task(_run_with_semaphore(_run_tour_analysis(job.id, tour_id)))

    return job


async def _run_scene_analysis(job_id: str, scene_id: str, image_url: str):
    """Run AI analysis on a single scene.

    Creates its own database session for the background task.
    """

    session_factory = get_bg_session_factory()
    async with session_factory() as db:
        try:
            await update_job_status(db, job_id, "processing", 10)

            provider = await _get_ai_provider_safe()

            # Download and encode image
            image_base64, mime_type = await _download_image_as_base64(image_url)
            vision_input = VisionInput(image_base64=image_base64, mime_type=mime_type)

            await update_job_status(db, job_id, "processing", 30)

            messages = [
                AIMessage(role=AIRole.SYSTEM, content=SCENE_ANALYSIS_PROMPT),
                AIMessage(role=AIRole.USER, content="Analyze this 360° panorama image.")
            ]

            await update_job_status(db, job_id, "processing", 50)

            # Use retry wrapper for AI call
            result = await _complete_json_with_retry(provider, messages, vision_input)

            # Add scene_id to result
            result["scene_id"] = scene_id

            await update_job_status(db, job_id, "completed", 100, result={"analysis": [result]})
            await db.commit()
            logger.info("Scene analysis completed for scene %s", scene_id)

        except AIProviderError as e:
            logger.error("AI provider error during scene analysis after retries: %s", e, exc_info=True)
            await update_job_status(db, job_id, "failed", error_message=str(e), increment_retry=True)
            await db.commit()
        except Exception as e:
            logger.error("Error during scene analysis: %s", e, exc_info=True)
            await update_job_status(db, job_id, "failed", error_message=str(e))
            await db.commit()


async def _run_tour_analysis(job_id: str, tour_id: str):
    """Run AI analysis on all scenes in a tour.

    Creates its own database session for the background task.
    """
    from app.models.tours import Scene, Tour

    session_factory = get_bg_session_factory()
    async with session_factory() as db:
        try:
            await update_job_status(db, job_id, "processing", 5)

            # Re-fetch tour with scenes in this session
            result = await db.execute(
                select(Tour).where(Tour.id == tour_id)
            )
            tour = result.scalar_one_or_none()
            if not tour:
                await update_job_status(db, job_id, "failed", error_message="Tour not found")
                await db.commit()
                return

            # Fetch scenes
            scenes_result = await db.execute(
                select(Scene).where(Scene.tour_id == tour_id).order_by(Scene.order_index)
            )
            scenes = list(scenes_result.scalars().all())

            provider = await _get_ai_provider_safe()

            total_scenes = len(scenes)
            analysis_results = []

            for i, scene in enumerate(scenes):
                progress = int(5 + (90 * (i + 1) / total_scenes))

                try:
                    # Download and encode image
                    image_base64, mime_type = await _download_image_as_base64(scene.image_url)
                    vision_input = VisionInput(image_base64=image_base64, mime_type=mime_type)

                    messages = [
                        AIMessage(role=AIRole.SYSTEM, content=SCENE_ANALYSIS_PROMPT),
                        AIMessage(role=AIRole.USER, content="Analyze this 360° panorama image.")
                    ]

                    result = await _complete_json_with_retry(provider, messages, vision_input)
                    result["scene_id"] = scene.id
                    analysis_results.append(result)

                except Exception as e:
                    logger.error("Error analyzing scene %s: %s", scene.id, e, exc_info=True)
                    analysis_results.append({
                        "scene_id": scene.id,
                        "error": str(e)
                    })

                await update_job_status(db, job_id, "processing", progress)

            await update_job_status(db, job_id, "completed", 100, result={"analysis": analysis_results})
            await db.commit()
            logger.info("Tour analysis completed for tour %s", tour_id)

        except Exception as e:
            logger.error("Error during tour analysis: %s", e, exc_info=True)
            await update_job_status(db, job_id, "failed", error_message=str(e))
            await db.commit()


# ====================
# Description Generation
# ====================

async def generate_scene_description(
    db: AsyncSession,
    scene_id: str,
    user_id: int,
    options: dict[str, Any] | None = None
) -> AIJob:
    """Generate AI description for a scene."""
    from app.services.tour import get_scene

    scene = await get_scene(db, scene_id, user_id)

    if scene.tour.user_id != user_id:
        raise ForbiddenException(detail="Access denied")

    # Create job
    job = await create_ai_job(db, user_id, "generate_description", scene_id=scene_id)

    # Run generation in background - pass only IDs and options
    asyncio.create_task(_run_with_semaphore(_run_description_generation(job.id, scene_id, scene.image_url, options or {})))

    return job


async def generate_tour_descriptions(
    db: AsyncSession,
    tour_id: str,
    user_id: int,
    options: dict[str, Any] | None = None
) -> AIJob:
    """Generate AI descriptions for all scenes in a tour."""
    from app.services.tour import get_tour

    tour = await get_tour(db, tour_id, user_id, include_scenes=True)

    if tour.user_id != user_id:
        raise ForbiddenException(detail="Access denied")

    if not tour.scenes:
        raise BadRequestException(detail="Tour has no scenes")

    # Create job
    job = await create_ai_job(db, user_id, "generate_descriptions", tour_id=tour_id)

    # Run generation in background - pass only tour_id
    asyncio.create_task(_run_with_semaphore(_run_tour_description_generation(job.id, tour_id, options or {})))

    return job


async def _run_description_generation(job_id: str, scene_id: str, image_url: str, options: dict[str, Any]):
    """Generate description for a scene.

    Creates its own database session for the background task.
    """
    session_factory = get_bg_session_factory()
    async with session_factory() as db:
        try:
            await update_job_status(db, job_id, "processing", 10)

            provider = await _get_ai_provider_safe()

            # Download and encode image
            image_base64, mime_type = await _download_image_as_base64(image_url)
            vision_input = VisionInput(image_base64=image_base64, mime_type=mime_type)

            await update_job_status(db, job_id, "processing", 30)

            # Build prompt based on options
            tone = options.get("tone", "professional")
            length = options.get("length", "medium")
            include_features = options.get("include_features", True)
            target_audience = options.get("target_audience", "home buyers")

            length_guide = {
                "short": "1-2 sentences",
                "medium": "2-4 sentences",
                "long": "4-6 sentences"
            }

            system_prompt = f"""You are a professional real estate copywriter.
Write a compelling description for this room/space in a {tone} tone.
Target audience: {target_audience}
Length: {length_guide.get(length, "2-4 sentences")}
{"Include specific features you observe." if include_features else "Focus on the atmosphere and feel."}

Respond in JSON format:
{{
    "description": "your description here"
}}"""

            messages = [
                AIMessage(role=AIRole.SYSTEM, content=system_prompt),
                AIMessage(role=AIRole.USER, content="Write a description for this 360° panorama.")
            ]

            await update_job_status(db, job_id, "processing", 60)

            result = await _complete_json_with_retry(provider, messages, vision_input)

            descriptions = {scene_id: result.get("description", "")}

            await update_job_status(db, job_id, "completed", 100, result={"descriptions": descriptions})
            await db.commit()
            logger.info("Description generated for scene %s", scene_id)

        except AIProviderError as e:
            logger.error("AI provider error during description generation: %s", e, exc_info=True)
            await update_job_status(db, job_id, "failed", error_message=str(e))
            await db.commit()
        except Exception as e:
            logger.error("Error during description generation: %s", e, exc_info=True)
            await update_job_status(db, job_id, "failed", error_message=str(e))
            await db.commit()


async def _run_tour_description_generation(job_id: str, tour_id: str, options: dict[str, Any]):
    """Generate descriptions for all scenes in a tour.

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

            descriptions = {}

            for i, scene in enumerate(scenes):
                progress = int(5 + (90 * (i + 1) / len(scenes)))

                try:
                    provider = await _get_ai_provider_safe()

                    # Download and encode image
                    image_base64, mime_type = await _download_image_as_base64(scene.image_url)
                    vision_input = VisionInput(image_base64=image_base64, mime_type=mime_type)

                    tone = options.get("tone", "professional")
                    length = options.get("length", "medium")

                    length_guide = {"short": "1-2 sentences", "medium": "2-4 sentences", "long": "4-6 sentences"}

                    system_prompt = f"""You are a professional real estate copywriter.
Write a compelling description in a {tone} tone.
Length: {length_guide.get(length, "2-4 sentences")}

Respond in JSON format:
{{
    "description": "your description here"
}}"""

                    messages = [
                        AIMessage(role=AIRole.SYSTEM, content=system_prompt),
                        AIMessage(role=AIRole.USER, content="Write a description for this 360° panorama.")
                    ]

                    result = await _complete_json_with_retry(provider, messages, vision_input)
                    descriptions[scene.id] = result.get("description", "")

                except Exception as e:
                    logger.error("Error generating description for scene %s: %s", scene.id, e, exc_info=True)
                    descriptions[scene.id] = ""

                await update_job_status(db, job_id, "processing", progress)

            await update_job_status(db, job_id, "completed", 100, result={"descriptions": descriptions})
            await db.commit()
            logger.info("Tour descriptions generated for tour %s", tour_id)

        except Exception as e:
            logger.error("Error during tour description generation: %s", e, exc_info=True)
            await update_job_status(db, job_id, "failed", error_message=str(e))
            await db.commit()
