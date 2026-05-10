"""
Background task runners and apply-suggestion functions for tour AI operations.

Contains tour generation, tour optimization background runners,
and functions to apply AI-generated suggestions to scenes/hotspots.
"""
import asyncio
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_bg_session_factory
from app.core.exceptions import BadRequestException, ForbiddenException
from app.core.logging import get_logger
from app.models.enums import TourStatus
from app.models.tours import AIJob, Hotspot, Scene, Tour
from app.schemas.tour import TourGenerationRequest, TourGenerationSceneInput
from app.services.ai import AIMessage, AIProviderError, AIRole, VisionInput

from .helpers import (
    ROOM_TYPES,
    _complete_json_with_retry,
    _download_image_as_base64,
    _ensure_navigation_hotspots,
    _get_ai_provider_safe,
    _run_with_semaphore,
)
from .jobs import create_ai_job, get_ai_job, update_job_status

logger = get_logger(__name__)


# ====================
# Apply Suggestions
# ====================

async def apply_scene_analysis(
    db: AsyncSession,
    tour_id: str,
    user_id: int,
    suggestions: list[dict[str, Any]]
) -> int:
    """Apply AI scene analysis suggestions (update titles/descriptions)."""
    from app.services.tour import get_scene, get_tour

    tour = await get_tour(db, tour_id, user_id, include_scenes=False)

    if tour.user_id != user_id:
        raise ForbiddenException(detail="Access denied")

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
            logger.error("Error applying suggestion for scene %s: %s", scene_id, e, exc_info=True)

    await db.commit()
    logger.info("Applied %s scene analysis suggestions for tour %s", updated_count, tour_id)
    return updated_count


async def apply_hotspot_suggestions(
    db: AsyncSession,
    scene_id: str,
    user_id: int,
    suggestion_ids: list[str],
    job_id: str | None = None
) -> list[Hotspot]:
    """Apply AI hotspot suggestions by creating hotspots."""
    from app.services.tour import create_hotspot, get_scene

    scene = await get_scene(db, scene_id, user_id)

    if scene.tour.user_id != user_id:
        raise ForbiddenException(detail="Access denied")

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
            from app.models.enums import HotspotType as HT
            from app.schemas.tour import HotspotCreate, HotspotPosition

            hotspot_type = HT.navigation if suggestion.get("type") == "navigation" else HT.info
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
            logger.error("Error creating hotspot from suggestion: %s", e, exc_info=True)

    logger.info("Applied %s hotspot suggestions for scene %s", len(created_hotspots), scene_id)
    return created_hotspots


# ====================
# Tour Generation
# ====================

async def generate_tour(
    db: AsyncSession,
    user_id: int,
    data: TourGenerationRequest,
) -> tuple[AIJob, Tour, list[str]]:
    """Create a new tour from scene inputs and run AI enhancements."""
    from uuid import uuid4

    scenes_input: list[dict[str, Any] | TourGenerationSceneInput] = list(data.scenes or [])
    if not scenes_input and data.image_urls:
        scenes_input = [
            {
                "image_url": url,
                "order_index": index,
            }
            for index, url in enumerate(data.image_urls)
        ]

    if not scenes_input:
        raise BadRequestException(detail="At least one scene image is required")

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

    scene_ids: list[str] = []
    for index, scene_input in enumerate(scenes_input):
        if isinstance(scene_input, dict):
            scene_payload = scene_input
        else:
            scene_payload = scene_input.model_dump(by_alias=True)

        scene_id = str(uuid4())
        scene_ids.append(scene_id)

        image_url = scene_payload.get("image_url")
        if not image_url:
            raise BadRequestException(detail="Scene image_url is required")

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
        _run_with_semaphore(_run_tour_generation(
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
        ))
    )

    return job, tour, scene_ids


async def _run_tour_generation(
    job_id: str,
    tour_id: str,
    user_id: int,
    options: dict[str, Any],
) -> None:
    """Run AI-driven enhancements for a generated tour.

    Creates its own database session for the background task.
    """
    session_factory = get_bg_session_factory()
    async with session_factory() as db:
        try:
            await update_job_status(db, job_id, "processing", 5, result={"tour_id": tour_id})
            from app.services.tour import get_tour

            tour = await get_tour(db, tour_id, user_id, include_scenes=True)
            provider = await _get_ai_provider_safe()

            scenes = tour.scenes or []
            total_scenes = len(scenes)
            generated: list[dict[str, Any]] = []
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

            created_hotspots: list[str] = []
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
            logger.info("Tour generation completed for tour %s", tour_id)

        except AIProviderError as e:
            logger.error("AI provider error during tour generation: %s", e, exc_info=True)
            await update_job_status(db, job_id, "failed", error_message=str(e))
            await db.commit()
        except Exception as e:
            logger.error("Error during tour generation: %s", e, exc_info=True)
            await update_job_status(db, job_id, "failed", error_message=str(e))
            await db.commit()


# ====================
# Tour Optimization
# ====================

async def optimize_tour(
    db: AsyncSession,
    tour_id: str,
    user_id: int,
    options: dict[str, Any] | None = None,
) -> AIJob:
    """Optimize an existing tour using AI."""
    from app.services.tour import get_tour

    tour = await get_tour(db, tour_id, user_id, include_scenes=True)

    if tour.user_id != user_id:
        raise ForbiddenException(detail="Access denied")

    job = await create_ai_job(db, user_id, "optimize_tour", tour_id=tour_id)

    asyncio.create_task(
        _run_with_semaphore(_run_tour_optimization(
            job.id,
            tour.id,
            user_id,
            options or {},
        ))
    )
    return job


async def _run_tour_optimization(
    job_id: str,
    tour_id: str,
    user_id: int,
    options: dict[str, Any],
) -> None:
    """Run AI optimization for a tour.

    Creates its own database session for the background task.
    """
    session_factory = get_bg_session_factory()
    async with session_factory() as db:
        try:
            await update_job_status(db, job_id, "processing", 5, result={"tour_id": tour_id})
            from app.services.tour import get_tour

            tour = await get_tour(db, tour_id, user_id, include_scenes=True)
            provider = await _get_ai_provider_safe()

            scenes = tour.scenes or []
            total_scenes = len(scenes)
            suggestions: list[dict[str, Any]] = []
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

            created_hotspots: list[str] = []
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
                logger.warning("Failed to generate overview recommendations: %s", e)
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
            logger.info("Tour optimization completed for tour %s", tour_id)

        except AIProviderError as e:
            logger.error("AI provider error during tour optimization: %s", e, exc_info=True)
            await update_job_status(db, job_id, "failed", error_message=str(e))
            await db.commit()
        except Exception as e:
            logger.error("Error during tour optimization: %s", e, exc_info=True)
            await update_job_status(db, job_id, "failed", error_message=str(e))
            await db.commit()
