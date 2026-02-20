"""
AI Services for 360 Virtual Tour Operations.

This module provides AI-powered features for scene analysis,
hotspot suggestions, and description generation using the Gemini AI provider.
"""
import asyncio
import base64
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from uuid import uuid4

import httpx
from fastapi import HTTPException, status
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    before_sleep_log,
    RetryError,
)

from app.core.database import get_async_session_factory
from app.core.logging import get_logger
from app.core.websocket import manager as ws_manager
from app.models.enums import HotspotType, TourStatus
from app.models.tours import AIJob, Hotspot, Scene, Tour
from app.services.ai import AIMessage, AIProviderError, AIRole, VisionInput, get_ai_provider

logger = get_logger(__name__)

# Retry configuration
MAX_RETRIES = 3
MIN_WAIT_SECONDS = 2
MAX_WAIT_SECONDS = 30


def _create_retry_decorator():
    """Create a retry decorator for AI provider calls."""
    return retry(
        stop=stop_after_attempt(MAX_RETRIES),
        wait=wait_exponential(multiplier=1, min=MIN_WAIT_SECONDS, max=MAX_WAIT_SECONDS),
        retry=retry_if_exception_type(AIProviderError),
        before_sleep=before_sleep_log(logger, log_level=30),  # WARNING level
        reraise=True,
    )


@_create_retry_decorator()
async def _call_ai_with_retry(
    ai_provider,
    messages: List[AIMessage],
    vision_inputs: Optional[List[VisionInput]] = None,
) -> str:
    """
    Call AI provider with automatic retry on AIProviderError.

    Args:
        ai_provider: The AI provider instance
        messages: List of AI messages
        vision_inputs: Optional vision inputs for image analysis

    Returns:
        The AI response content

    Raises:
        AIProviderError: After all retries are exhausted
    """
    return await ai_provider.generate(messages=messages, vision_inputs=vision_inputs)


@_create_retry_decorator()
async def _complete_json_with_retry(
    ai_provider,
    messages: List[AIMessage],
    vision_input: Optional[VisionInput] = None,
) -> Dict[str, Any]:
    """
    Call AI provider's complete_json with automatic retry on AIProviderError.

    Args:
        ai_provider: The AI provider instance
        messages: List of AI messages
        vision_input: Optional vision input for image analysis

    Returns:
        The parsed JSON response

    Raises:
        AIProviderError: After all retries are exhausted
    """
    return await ai_provider.complete_json(messages, vision_input)


# Room type mappings for scene analysis
ROOM_TYPES = [
    "living_room", "bedroom", "bathroom", "kitchen", "dining_room",
    "home_office", "hallway", "entrance", "balcony", "terrace",
    "garden", "garage", "basement", "attic", "pool_area",
    "gym", "laundry_room", "storage", "exterior", "other"
]

# Scene analysis prompt template
SCENE_ANALYSIS_PROMPT = """You are an expert real estate photographer and interior designer.
Analyze this 360° panorama image and provide detailed information about the room.
Respond in JSON format with the following structure:
{
    "room_type": "one of: living_room, bedroom, bathroom, kitchen, dining_room, home_office, hallway, entrance, balcony, terrace, garden, garage, basement, attic, pool_area, gym, laundry_room, storage, exterior, other",
    "room_confidence": 0.0 to 1.0,
    "suggested_title": "A descriptive title for this scene (e.g., 'Spacious Master Bedroom')",
    "suggested_description": "A 2-3 sentence description highlighting key features",
    "quality_score": 0 to 100 (integer, based on image quality, lighting, composition),
    "quality_issues": ["list of any quality issues found"],
    "features_detected": ["list of notable features like 'hardwood floors', 'large windows', 'fireplace']
}"""


def _build_hotspot_suggestion_prompt(scene_context: str, full_format: bool = True) -> str:
    """Build the system prompt for hotspot suggestions."""
    if full_format:
        return f"""You are an expert virtual tour designer.
Analyze this 360° panorama and suggest optimal hotspot placements.
Hotspots can be navigation points to other rooms or information points for notable features.

Available scenes to link to:
{scene_context}

Respond in JSON format with an array of hotspot suggestions:
{{
    "hotspots": [
        {{
            "type": "navigation" or "info",
            "yaw": horizontal angle in degrees (-180 to 180, where 0 is center of view),
            "pitch": vertical angle in degrees (-90 to 90, where 0 is horizon),
            "target_scene_id": "scene ID if type is navigation, null otherwise",
            "suggested_title": "title for the hotspot",
            "reasoning": "brief explanation of why this hotspot is suggested",
            "confidence": 0.0 to 1.0
        }}
    ]
}}

Focus on:
1. Doorways and passages that likely lead to other rooms
2. Notable features worth highlighting (fireplaces, views, art, furniture)
3. Logical flow between connected spaces"""
    else:
        return f"""You are an expert virtual tour designer.
Analyze this 360° panorama and suggest optimal hotspot placements.

Available scenes to link to:
{scene_context}

Respond in JSON format:
{{
    "hotspots": [
        {{
            "type": "navigation" or "info",
            "yaw": -180 to 180,
            "pitch": -90 to 90,
            "target_scene_id": "scene ID if navigation",
            "suggested_title": "title",
            "reasoning": "why this hotspot",
            "confidence": 0.0 to 1.0
        }}
    ]
}}"""


async def _ensure_navigation_hotspots(
    db: AsyncSession,
    tour: Tour,
) -> List[Hotspot]:
    """Create basic navigation hotspots for scenes lacking them."""
    scenes = sorted(tour.scenes or [], key=lambda s: s.order_index)
    if len(scenes) < 2:
        return []

    created: List[Hotspot] = []
    for index, scene in enumerate(scenes[:-1]):
        next_scene = scenes[index + 1]
        # Skip if navigation hotspot already exists for this target.
        existing = any(
            hotspot.type == HotspotType.navigation and hotspot.target_scene_id == next_scene.id
            for hotspot in (scene.hotspots or [])
        )
        if existing:
            continue

        hotspot = Hotspot(
            id=str(uuid4()),
            scene_id=scene.id,
            type=HotspotType.navigation,
            position={"yaw": 0, "pitch": 0, "radius": None},
            target_scene_id=next_scene.id,
            title=next_scene.title or "Next",
            description=None,
            icon=None,
            icon_name=None,
            icon_color=None,
            icon_size=32,
            content=None,
            custom_data={"auto_generated": True},
            order_index=0,
            is_active=True,
        )
        db.add(hotspot)
        created.append(hotspot)

    if created:
        await db.commit()
        for hotspot in created:
            await db.refresh(hotspot)

    return created


async def _download_image_as_base64(url: str) -> tuple[str, str]:
    """Download an image and convert to base64."""
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(url)
        response.raise_for_status()

        content_type = response.headers.get("content-type", "image/jpeg")
        if ";" in content_type:
            content_type = content_type.split(";")[0].strip()

        image_base64 = base64.b64encode(response.content).decode("utf-8")
        return image_base64, content_type


async def _get_ai_provider_safe():
    """Get AI provider with error handling."""
    try:
        return get_ai_provider()
    except ValueError as e:
        logger.error(f"Failed to get AI provider: {e}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AI service is not configured. Please set GOOGLE_API_KEY."
        )


# ====================
# AI Job Management
# ====================

async def create_ai_job(
    db: AsyncSession,
    user_id: int,
    job_type: str,
    tour_id: Optional[str] = None,
    scene_id: Optional[str] = None
) -> AIJob:
    """Create a new AI processing job."""
    job = AIJob(
        id=str(uuid4()),
        user_id=user_id,
        tour_id=tour_id,
        scene_id=scene_id,
        job_type=job_type,
        status="pending",
        progress=0
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)
    logger.info(f"AI job created: {job.id} (type: {job_type})")
    return job


async def update_job_status(
    db: AsyncSession,
    job_id: str,
    status: str,
    progress: int = 0,
    result: Optional[Dict[str, Any]] = None,
    error_message: Optional[str] = None,
    increment_retry: bool = False
) -> AIJob:
    """Update an AI job's status and broadcast via WebSocket."""
    query = select(AIJob).where(AIJob.id == job_id)
    db_result = await db.execute(query)
    job = db_result.scalar_one_or_none()

    if not job:
        raise HTTPException(status_code=404, detail="AI job not found")

    job.status = status
    job.progress = progress

    if increment_retry:
        job.retry_count = (job.retry_count or 0) + 1

    if status == "processing" and not job.started_at:
        job.started_at = datetime.utcnow()

    if status in ("completed", "failed", "cancelled"):
        job.completed_at = datetime.utcnow()

    if result:
        job.result = result

    if error_message:
        job.error_message = error_message

    await db.commit()
    await db.refresh(job)

    # Broadcast update via WebSocket
    try:
        ws_update = {
            "status": status,
            "progress": progress,
            "result": result,
            "error_message": error_message,
        }
        await ws_manager.send_job_update(job_id, ws_update)

        # Send completion/error notifications to user
        if status == "completed" and result:
            await ws_manager.broadcast_job_completion(job_id, job.user_id, result)
        elif status == "failed" and error_message:
            await ws_manager.broadcast_job_error(job_id, job.user_id, error_message)
    except Exception as e:
        # Don't fail the job update if WebSocket broadcast fails
        logger.warning(f"Failed to broadcast job update via WebSocket: {e}")

    return job


async def get_ai_job(
    db: AsyncSession,
    job_id: str,
    user_id: Optional[int] = None
) -> AIJob:
    """Get an AI job by ID."""
    query = select(AIJob).where(AIJob.id == job_id)

    if user_id is not None:
        query = query.where(AIJob.user_id == user_id)

    result = await db.execute(query)
    job = result.scalar_one_or_none()

    if not job:
        raise HTTPException(status_code=404, detail="AI job not found")

    return job


async def get_user_ai_jobs(
    db: AsyncSession,
    user_id: int,
    status_filter: Optional[str] = None,
    limit: int = 20,
    offset: int = 0
) -> dict:
    """Get AI jobs for a user."""
    query = select(AIJob).where(AIJob.user_id == user_id)

    if status_filter:
        query = query.where(AIJob.status == status_filter)

    # Count total
    count_query = select(func.count()).select_from(query.subquery())
    count_result = await db.execute(count_query)
    total = count_result.scalar() or 0

    # Fetch jobs
    query = query.order_by(AIJob.created_at.desc()).offset(offset).limit(limit)
    result = await db.execute(query)
    jobs = list(result.scalars().all())

    return {"jobs": jobs, "total": total}


async def cancel_ai_job(
    db: AsyncSession,
    job_id: str,
    user_id: int
) -> bool:
    """Cancel an AI job."""
    job = await get_ai_job(db, job_id, user_id)

    if job.status in ("completed", "failed", "cancelled"):
        return False

    job.status = "cancelled"
    job.completed_at = datetime.utcnow()
    await db.commit()

    logger.info(f"AI job cancelled: {job_id}")
    return True


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
        raise HTTPException(status_code=403, detail="Access denied")

    # Create job
    job = await create_ai_job(db, user_id, "analyze_scene", scene_id=scene_id)

    # Run analysis in background - pass only IDs, not ORM objects
    asyncio.create_task(_run_scene_analysis(job.id, scene_id, scene.image_url))

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
        raise HTTPException(status_code=403, detail="Access denied")

    if not tour.scenes:
        raise HTTPException(status_code=400, detail="Tour has no scenes to analyze")

    # Create job
    job = await create_ai_job(db, user_id, "analyze_scenes", tour_id=tour_id)

    # Run analysis in background - pass only tour_id
    asyncio.create_task(_run_tour_analysis(job.id, tour_id))

    return job


async def _run_scene_analysis(job_id: str, scene_id: str, image_url: str):
    """Run AI analysis on a single scene.

    Creates its own database session for the background task.
    """
    session_factory = get_async_session_factory()
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
            logger.info(f"Scene analysis completed for scene {scene_id}")

        except AIProviderError as e:
            logger.error(f"AI provider error during scene analysis after retries: {e}")
            await update_job_status(db, job_id, "failed", error_message=str(e), increment_retry=True)
            await db.commit()
        except Exception as e:
            logger.error(f"Error during scene analysis: {e}")
            await update_job_status(db, job_id, "failed", error_message=str(e))
            await db.commit()


async def _run_tour_analysis(job_id: str, tour_id: str):
    """Run AI analysis on all scenes in a tour.

    Creates its own database session for the background task.
    """
    session_factory = get_async_session_factory()
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
                    logger.error(f"Error analyzing scene {scene.id}: {e}")
                    analysis_results.append({
                        "scene_id": scene.id,
                        "error": str(e)
                    })

                await update_job_status(db, job_id, "processing", progress)

            await update_job_status(db, job_id, "completed", 100, result={"analysis": analysis_results})
            await db.commit()
            logger.info(f"Tour analysis completed for tour {tour_id}")

        except Exception as e:
            logger.error(f"Error during tour analysis: {e}")
            await update_job_status(db, job_id, "failed", error_message=str(e))
            await db.commit()


# ====================
# Hotspot Suggestions
# ====================

async def suggest_scene_hotspots(
    db: AsyncSession,
    scene_id: str,
    user_id: int
) -> AIJob:
    """Suggest hotspots for a scene using AI."""
    from app.services.tour import get_scene, get_scenes

    scene = await get_scene(db, scene_id, user_id)

    if scene.tour.user_id != user_id:
        raise HTTPException(status_code=403, detail="Access denied")

    # Get all scenes in the tour for navigation suggestions
    scenes = await get_scenes(db, scene.tour_id, user_id)

    # Create job
    job = await create_ai_job(db, user_id, "suggest_hotspots", scene_id=scene_id)

    # Run suggestion in background - pass only IDs and required data
    asyncio.create_task(_run_hotspot_suggestions(job.id, scene_id, scene.tour_id))

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
        raise HTTPException(status_code=403, detail="Access denied")

    if not tour.scenes or len(tour.scenes) < 2:
        raise HTTPException(status_code=400, detail="Tour needs at least 2 scenes for hotspot suggestions")

    # Create job
    job = await create_ai_job(db, user_id, "suggest_tour_hotspots", tour_id=tour_id)

    # Run suggestion in background - pass only tour_id
    asyncio.create_task(_run_tour_hotspot_suggestions(job.id, tour_id))

    return job


async def _run_hotspot_suggestions(job_id: str, scene_id: str, tour_id: str):
    """Generate hotspot suggestions for a scene.

    Creates its own database session for the background task.
    """
    session_factory = get_async_session_factory()
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
            logger.info(f"Hotspot suggestions completed for scene {scene_id}")

        except AIProviderError as e:
            logger.error(f"AI provider error during hotspot suggestions: {e}")
            await update_job_status(db, job_id, "failed", error_message=str(e))
            await db.commit()
        except Exception as e:
            logger.error(f"Error during hotspot suggestions: {e}")
            await update_job_status(db, job_id, "failed", error_message=str(e))
            await db.commit()


async def _run_tour_hotspot_suggestions(job_id: str, tour_id: str):
    """Generate hotspot suggestions for all scenes in a tour.

    Creates its own database session for the background task.
    """
    session_factory = get_async_session_factory()
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
                    logger.error(f"Error suggesting hotspots for scene {scene.id}: {e}")

                await update_job_status(db, job_id, "processing", progress)

            await update_job_status(db, job_id, "completed", 100, result={"hotspots": all_hotspots})
            await db.commit()
            logger.info(f"Tour hotspot suggestions completed for tour {tour_id}")

        except Exception as e:
            logger.error(f"Error during tour hotspot suggestions: {e}")
            await update_job_status(db, job_id, "failed", error_message=str(e))
            await db.commit()


# ====================
# Description Generation
# ====================

async def generate_scene_description(
    db: AsyncSession,
    scene_id: str,
    user_id: int,
    options: Optional[Dict[str, Any]] = None
) -> AIJob:
    """Generate AI description for a scene."""
    from app.services.tour import get_scene

    scene = await get_scene(db, scene_id, user_id)

    if scene.tour.user_id != user_id:
        raise HTTPException(status_code=403, detail="Access denied")

    # Create job
    job = await create_ai_job(db, user_id, "generate_description", scene_id=scene_id)

    # Run generation in background - pass only IDs and options
    asyncio.create_task(_run_description_generation(job.id, scene_id, scene.image_url, options or {}))

    return job


async def generate_tour_descriptions(
    db: AsyncSession,
    tour_id: str,
    user_id: int,
    options: Optional[Dict[str, Any]] = None
) -> AIJob:
    """Generate AI descriptions for all scenes in a tour."""
    from app.services.tour import get_tour

    tour = await get_tour(db, tour_id, user_id, include_scenes=True)

    if tour.user_id != user_id:
        raise HTTPException(status_code=403, detail="Access denied")

    if not tour.scenes:
        raise HTTPException(status_code=400, detail="Tour has no scenes")

    # Create job
    job = await create_ai_job(db, user_id, "generate_descriptions", tour_id=tour_id)

    # Run generation in background - pass only tour_id
    asyncio.create_task(_run_tour_description_generation(job.id, tour_id, options or {}))

    return job


async def _run_description_generation(job_id: str, scene_id: str, image_url: str, options: Dict[str, Any]):
    """Generate description for a scene.

    Creates its own database session for the background task.
    """
    session_factory = get_async_session_factory()
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
            logger.info(f"Description generated for scene {scene_id}")

        except AIProviderError as e:
            logger.error(f"AI provider error during description generation: {e}")
            await update_job_status(db, job_id, "failed", error_message=str(e))
            await db.commit()
        except Exception as e:
            logger.error(f"Error during description generation: {e}")
            await update_job_status(db, job_id, "failed", error_message=str(e))
            await db.commit()


async def _run_tour_description_generation(job_id: str, tour_id: str, options: Dict[str, Any]):
    """Generate descriptions for all scenes in a tour.

    Creates its own database session for the background task.
    """
    session_factory = get_async_session_factory()
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
                    logger.error(f"Error generating description for scene {scene.id}: {e}")
                    descriptions[scene.id] = ""

                await update_job_status(db, job_id, "processing", progress)

            await update_job_status(db, job_id, "completed", 100, result={"descriptions": descriptions})
            await db.commit()
            logger.info(f"Tour descriptions generated for tour {tour_id}")

        except Exception as e:
            logger.error(f"Error during tour description generation: {e}")
            await update_job_status(db, job_id, "failed", error_message=str(e))
            await db.commit()


# ====================
# Apply Suggestions
# ====================

async def apply_scene_analysis(
    db: AsyncSession,
    tour_id: str,
    user_id: int,
    suggestions: List[Dict[str, Any]]
) -> int:
    """Apply AI scene analysis suggestions (update titles/descriptions)."""
    from app.services.tour import get_tour, get_scene

    tour = await get_tour(db, tour_id, user_id, include_scenes=False)

    if tour.user_id != user_id:
        raise HTTPException(status_code=403, detail="Access denied")

    updated_count = 0

    for suggestion in suggestions:
        scene_id = suggestion.get("scene_id")
        apply_title = suggestion.get("apply_title", False)
        apply_description = suggestion.get("apply_description", False)

        if not scene_id or (not apply_title and not apply_description):
            continue

        try:
            scene = await get_scene(db, scene_id, user_id)

            if apply_title and suggestion.get("suggested_title"):
                scene.title = suggestion["suggested_title"]

            if apply_description and suggestion.get("suggested_description"):
                scene.description = suggestion["suggested_description"]

            updated_count += 1

        except Exception as e:
            logger.error(f"Error applying suggestion for scene {scene_id}: {e}")

    await db.commit()
    logger.info(f"Applied {updated_count} scene analysis suggestions for tour {tour_id}")
    return updated_count


async def apply_hotspot_suggestions(
    db: AsyncSession,
    scene_id: str,
    user_id: int,
    suggestion_ids: List[str],
    job_id: Optional[str] = None
) -> List[Hotspot]:
    """Apply AI hotspot suggestions by creating hotspots."""
    from app.services.tour import get_scene, create_hotspot

    scene = await get_scene(db, scene_id, user_id)

    if scene.tour.user_id != user_id:
        raise HTTPException(status_code=403, detail="Access denied")

    # Get suggestions from job result if job_id provided
    hotspot_suggestions = []
    if job_id:
        job = await get_ai_job(db, job_id, user_id)
        if job.result and "hotspots" in job.result:
            hotspot_suggestions = job.result["hotspots"]

    # Filter to requested suggestions
    suggestions_to_apply = [s for s in hotspot_suggestions if s.get("id") in suggestion_ids]

    created_hotspots = []

    for suggestion in suggestions_to_apply:
        try:
            from app.schemas.tour import HotspotCreate, HotspotPosition

            hotspot_type = HotspotType.navigation if suggestion.get("type") == "navigation" else HotspotType.info
            position = suggestion.get("position", {})

            hotspot_data = HotspotCreate(
                type=hotspot_type,
                position=HotspotPosition(
                    yaw=position.get("yaw", 0),
                    pitch=position.get("pitch", 0)
                ),
                target_scene_id=suggestion.get("target_scene_id"),
                title=suggestion.get("suggested_title"),
                description=suggestion.get("reasoning")
            )

            hotspot = await create_hotspot(db, scene_id, user_id, hotspot_data)
            created_hotspots.append(hotspot)

        except Exception as e:
            logger.error(f"Error creating hotspot from suggestion: {e}")

    logger.info(f"Applied {len(created_hotspots)} hotspot suggestions for scene {scene_id}")
    return created_hotspots


# ====================
# Tour Generation
# ====================

async def generate_tour(
    db: AsyncSession,
    user_id: int,
    data: Any,
) -> Tuple[AIJob, Tour, List[str]]:
    """Create a new tour from scene inputs and run AI enhancements."""
    scenes_input = data.scenes or []
    if not scenes_input and data.image_urls:
        scenes_input = [
            {
                "image_url": url,
                "order_index": index,
            }
            for index, url in enumerate(data.image_urls)
        ]

    if not scenes_input:
        raise HTTPException(status_code=400, detail="At least one scene image is required")

    tour = Tour(
        id=str(uuid4()),
        user_id=user_id,
        title=data.title,
        description=data.description,
        status=data.status or TourStatus.draft,
        is_public=data.is_public or False,
        settings=data.settings.model_dump() if data.settings else None,
    )
    db.add(tour)
    await db.flush()

    scene_ids: List[str] = []
    for index, scene_input in enumerate(scenes_input):
        if isinstance(scene_input, dict):
            scene_payload = scene_input
        else:
            scene_payload = scene_input.model_dump(by_alias=True)

        scene_id = str(uuid4())
        scene_ids.append(scene_id)

        image_url = scene_payload.get("image_url")
        if not image_url:
            raise HTTPException(status_code=400, detail="Scene image_url is required")

        metadata = scene_payload.get("metadata") or scene_payload.get("scene_metadata")
        if metadata and not isinstance(metadata, dict):
            metadata = metadata.model_dump()

        scene = Scene(
            id=scene_id,
            tour_id=tour.id,
            title=scene_payload.get("title"),
            description=scene_payload.get("description"),
            image_url=image_url,
            thumbnail_url=scene_payload.get("thumbnail_url"),
            order_index=scene_payload.get("order_index")
            if scene_payload.get("order_index") is not None
            else index,
            scene_metadata=metadata,
        )
        db.add(scene)

    await db.commit()
    await db.refresh(tour)

    job = await create_ai_job(db, user_id, "generate_tour", tour_id=tour.id)
    asyncio.create_task(
        _run_tour_generation(
            job.id,
            tour.id,
            user_id,
            {
                "generate_titles": data.generate_titles,
                "generate_descriptions": data.generate_descriptions,
                "suggest_hotspots": data.suggest_hotspots,
                "apply_to_scenes": data.apply_to_scenes,
                "language": data.language,
            },
        )
    )

    return job, tour, scene_ids


async def _run_tour_generation(
    job_id: str,
    tour_id: str,
    user_id: int,
    options: Dict[str, Any],
) -> None:
    """Run AI-driven enhancements for a generated tour.

    Creates its own database session for the background task.
    """
    session_factory = get_async_session_factory()
    async with session_factory() as db:
        try:
            await update_job_status(db, job_id, "processing", 5, result={"tour_id": tour_id})
            from app.services.tour import get_tour

            tour = await get_tour(db, tour_id, user_id, include_scenes=True)
            provider = await _get_ai_provider_safe()

            scenes = tour.scenes or []
            total_scenes = len(scenes)
            generated: List[Dict[str, Any]] = []
            apply_to_scenes = bool(options.get("apply_to_scenes", True))
            generate_titles = bool(options.get("generate_titles", True))
            generate_descriptions = bool(options.get("generate_descriptions", True))
            language = options.get("language") or "English"

            for index, scene in enumerate(scenes):
                progress = int(5 + (70 * (index + 1) / max(total_scenes, 1)))

                if generate_titles or generate_descriptions:
                    image_base64, mime_type = await _download_image_as_base64(scene.image_url)
                    vision_input = VisionInput(image_base64=image_base64, mime_type=mime_type)

                    system_prompt = f"""You are a virtual tour creator.
Generate a concise scene title and description in {language} for the provided panorama.
Respond in JSON with:
{{
  "title": "Scene title",
  "description": "2-3 sentence description",
  "room_type": "one of: {', '.join(ROOM_TYPES)}"
}}"""

                    messages = [
                        AIMessage(role=AIRole.SYSTEM, content=system_prompt),
                        AIMessage(role=AIRole.USER, content="Create a scene title and description."),
                    ]

                    result = await _complete_json_with_retry(provider, messages, vision_input)
                    generated.append({"scene_id": scene.id, **result})

                    if apply_to_scenes:
                        if generate_titles and result.get("title") and not scene.title:
                            scene.title = result["title"]
                        if generate_descriptions and result.get("description") and not scene.description:
                            scene.description = result["description"]

                await update_job_status(db, job_id, "processing", progress)

            created_hotspots: List[str] = []
            if options.get("suggest_hotspots"):
                created = await _ensure_navigation_hotspots(db, tour)
                created_hotspots = [hotspot.id for hotspot in created]

            await db.commit()
            await update_job_status(
                db,
                job_id,
                "completed",
                100,
                result={
                    "tour_id": tour_id,
                    "generated": generated,
                    "created_hotspots": created_hotspots,
                },
            )
            await db.commit()
            logger.info(f"Tour generation completed for tour {tour_id}")

        except AIProviderError as e:
            logger.error(f"AI provider error during tour generation: {e}")
            await update_job_status(db, job_id, "failed", error_message=str(e))
            await db.commit()
        except Exception as e:
            logger.error(f"Error during tour generation: {e}")
            await update_job_status(db, job_id, "failed", error_message=str(e))
            await db.commit()


# ====================
# Tour Optimization
# ====================

async def optimize_tour(
    db: AsyncSession,
    tour_id: str,
    user_id: int,
    options: Optional[Dict[str, Any]] = None,
) -> AIJob:
    """Optimize an existing tour using AI."""
    from app.services.tour import get_tour

    tour = await get_tour(db, tour_id, user_id, include_scenes=True)

    if tour.user_id != user_id:
        raise HTTPException(status_code=403, detail="Access denied")

    job = await create_ai_job(db, user_id, "optimize_tour", tour_id=tour_id)

    asyncio.create_task(
        _run_tour_optimization(
            job.id,
            tour.id,
            user_id,
            options or {},
        )
    )
    return job


async def _run_tour_optimization(
    job_id: str,
    tour_id: str,
    user_id: int,
    options: Dict[str, Any],
) -> None:
    """Run AI optimization for a tour.

    Creates its own database session for the background task.
    """
    session_factory = get_async_session_factory()
    async with session_factory() as db:
        try:
            await update_job_status(db, job_id, "processing", 5, result={"tour_id": tour_id})
            from app.services.tour import get_tour

            tour = await get_tour(db, tour_id, user_id, include_scenes=True)
            provider = await _get_ai_provider_safe()

            scenes = tour.scenes or []
            total_scenes = len(scenes)
            suggestions: List[Dict[str, Any]] = []
            update_titles = bool(options.get("update_titles"))
            update_descriptions = bool(options.get("update_descriptions"))
            language = options.get("language") or "English"

            for index, scene in enumerate(scenes):
                progress = int(5 + (70 * (index + 1) / max(total_scenes, 1)))

                image_base64, mime_type = await _download_image_as_base64(scene.image_url)
                vision_input = VisionInput(image_base64=image_base64, mime_type=mime_type)

                system_prompt = f"""You are a virtual tour optimization assistant.
Analyze this panorama and suggest improvements. Respond in JSON:
{{
  "scene_id": "{scene.id}",
  "quality_score": 0-100,
  "quality_issues": ["list of issues"],
  "suggested_title": "Improved title in {language}",
  "suggested_description": "Improved description in {language}",
  "recommendations": ["list of optimization ideas"]
}}"""

                messages = [
                    AIMessage(role=AIRole.SYSTEM, content=system_prompt),
                    AIMessage(role=AIRole.USER, content="Optimize this tour scene."),
                ]

                result = await _complete_json_with_retry(provider, messages, vision_input)
                suggestions.append(result)

                if update_titles and result.get("suggested_title"):
                    scene.title = result["suggested_title"]
                if update_descriptions and result.get("suggested_description"):
                    scene.description = result["suggested_description"]

                await update_job_status(db, job_id, "processing", progress)

            created_hotspots: List[str] = []
            if options.get("suggest_hotspots"):
                created = await _ensure_navigation_hotspots(db, tour)
                created_hotspots = [hotspot.id for hotspot in created]

            overview = {
                "scene_count": len(scenes),
                "missing_titles": sum(1 for scene in scenes if not scene.title),
                "missing_descriptions": sum(1 for scene in scenes if not scene.description),
                "hotspot_count": sum(len(scene.hotspots or []) for scene in scenes),
            }

            try:
                prompt = (
                    "Provide concise optimization recommendations for this tour summary in JSON: "
                    '{"recommendations": ["..."]}'
                )
                messages = [
                    AIMessage(role=AIRole.SYSTEM, content=prompt),
                    AIMessage(
                        role=AIRole.USER,
                        content=f"Tour summary: {overview}. Focus areas: {options.get('focus_areas')}.",
                    ),
                ]
                overview_result = await _complete_json_with_retry(provider, messages)
            except Exception as e:
                logger.warning(f"Failed to generate overview recommendations: {e}")
                overview_result = {"recommendations": []}

            await db.commit()
            await update_job_status(
                db,
                job_id,
                "completed",
                100,
                result={
                    "tour_id": tour_id,
                    "overview": overview,
                    "overview_recommendations": overview_result.get("recommendations", []),
                    "scene_suggestions": suggestions,
                    "created_hotspots": created_hotspots,
                },
            )
            await db.commit()
            logger.info(f"Tour optimization completed for tour {tour_id}")

        except AIProviderError as e:
            logger.error(f"AI provider error during tour optimization: {e}")
            await update_job_status(db, job_id, "failed", error_message=str(e))
            await db.commit()
        except Exception as e:
            logger.error(f"Error during tour optimization: {e}")
            await update_job_status(db, job_id, "failed", error_message=str(e))
            await db.commit()
