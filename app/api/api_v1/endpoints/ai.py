"""
AI Processing API Endpoints for 360 Virtual Tours.

This module provides REST API endpoints for AI-powered features:
- Scene analysis (room detection, quality scoring)
- Hotspot suggestions
- Description generation
- AI job management
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.api_v1.dependencies.auth import (
    get_current_active_user,
    get_current_active_user_short_session,
)
from app.core.database import get_bg_session_factory, get_db
from app.core.logging import get_logger
from app.schemas.tour import (
    AIJobResponse,
    AIJobStatusResponse,
    DescriptionOptions,
    TourGenerationRequest,
    TourGenerationResponse,
)
from app.schemas.user import User as UserSchema
from app.services import tour_ai
from app.services.storage import storage_service

router = APIRouter()
logger = get_logger(__name__)


# ====================
# Scene Analysis
# ====================


@router.post(
    "/tours/{tour_id}/analyze", response_model=AIJobResponse, summary="Analyze tour scenes"
)
async def analyze_tour_scenes(
    tour_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: UserSchema = Depends(get_current_active_user),
):
    """
    Analyze all scenes in a tour using AI.

    Detects room types, suggests titles/descriptions, and evaluates image quality.
    Returns a job ID for tracking progress.
    """
    job = await tour_ai.analyze_tour_scenes(
        db=db,
        tour_id=tour_id,
        user_id=current_user.id,
    )
    return {"job": job}


# ====================
# Spatial Connect (re-run AI room linking on an existing tour)
# ====================


@router.post(
    "/tours/{tour_id}/connect-spatial",
    response_model=AIJobResponse,
    summary="Connect tour rooms with AI",
)
async def connect_tour_spatial(
    tour_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: UserSchema = Depends(get_current_active_user),
):
    """
    Re-run doorway linking on an existing tour with AI.

    Replaces previously AI-generated navigation hotspots with a fresh, fully
    reachable set built from the scenes' panoramas; manually placed hotspots are
    kept. Returns a job ID for tracking progress.
    """
    job = await tour_ai.spatial_connect_existing_tour(
        db=db,
        tour_id=tour_id,
        user_id=current_user.id,
    )
    return {"job": job}


# ====================
# Tour Generation & Optimization
# ====================


@router.post("/tours/generate", response_model=TourGenerationResponse, summary="Generate tour")
async def generate_tour(
    images: list[UploadFile] = File(..., description="360 panorama images to create tour from"),
    title: str | None = Form(None, max_length=255, description="Tour title"),
    description: str | None = Form(None, max_length=5000, description="Tour description"),
    generate_titles: bool = Form(True, description="Generate scene titles with AI"),
    generate_descriptions: bool = Form(True, description="Generate AI descriptions for scenes"),
    suggest_hotspots: bool = Form(
        False, description="Suggest hotspot placements without spatial detection"
    ),
    spatial: bool = Form(True, description="Use spatial doorway detection for hotspot placement"),
    apply_to_scenes: bool = Form(
        True, description="Apply the generated titles and descriptions to the scenes"
    ),
    language: str | None = Form(
        None, max_length=20, description="Language for generated text, for example en"
    ),
    current_user: UserSchema = Depends(get_current_active_user_short_session),
):
    """
    Generate a new tour from uploaded 360 images using AI.

    Accepts multipart/form-data with image files and tour options.
    Images are uploaded to storage and then processed by AI to:
    - Detect room types
    - Generate scene titles and descriptions
    - Optionally suggest hotspot placements using spatial doorway detection
    """
    if not images:
        raise HTTPException(status_code=400, detail="At least one image is required")

    # Validate image files
    allowed_types = {"image/jpeg", "image/png", "image/webp"}
    for img in images:
        if img.content_type not in allowed_types:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid file type: {img.content_type}. Allowed: {', '.join(allowed_types)}",
            )

    # Upload images to storage
    upload_results = await storage_service.upload_batch(
        images,
        db=None,
        user_id=current_user.id,
        visibility="private",
    )

    # upload_batch returns one item per file: {index, filename, status, result?, error?}.
    # Only "uploaded" items carry result["public_url"].
    image_urls: list[str] = []
    for item in upload_results:
        if item["status"] != "uploaded":
            logger.warning("Tour image upload failed: %s", item.get("error"))
            continue
        url = (item.get("result") or {}).get("public_url")
        if url:
            image_urls.append(url)
        else:
            logger.warning("Upload result missing URL: %s", item)

    if not image_urls:
        raise HTTPException(status_code=500, detail="Failed to upload images")

    # Generate a default title if not provided
    tour_title = title if title else f"AI Generated Tour ({len(images)} scenes)"

    # Create TourGenerationRequest with uploaded image URLs.
    # spatial=True uses vision-based doorway detection; when spatial is off, the
    # naive suggest_hotspots fallback is used only if suggest_hotspots is set.
    payload = TourGenerationRequest(
        title=tour_title,
        description=description,
        image_urls=image_urls,
        generate_titles=generate_titles,
        generate_descriptions=generate_descriptions,
        suggest_hotspots=suggest_hotspots and not spatial,
        spatial=spatial,
        apply_to_scenes=apply_to_scenes,
        language=language,
    )

    session_factory = get_bg_session_factory()
    async with session_factory() as db:
        job, tour, scene_ids = await tour_ai.generate_tour(
            db=db,
            user_id=current_user.id,
            data=payload,
        )
        return {"job": job, "tour_id": tour.id, "scene_ids": scene_ids}


# ====================
# Hotspot Suggestions
# ====================


@router.post(
    "/scenes/{scene_id}/hotspots", response_model=AIJobResponse, summary="Suggest scene hotspots"
)
async def suggest_scene_hotspots(
    scene_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: UserSchema = Depends(get_current_active_user),
):
    """
    Get AI-suggested hotspots for a scene.

    Analyzes the panorama to suggest optimal navigation and info hotspot placements.
    """
    job = await tour_ai.suggest_scene_hotspots(
        db=db,
        scene_id=scene_id,
        user_id=current_user.id,
    )
    return {"job": job}


# ====================
# Description Generation
# ====================


@router.post(
    "/tours/{tour_id}/descriptions",
    response_model=AIJobResponse,
    summary="Generate tour descriptions",
)
async def generate_tour_descriptions(
    tour_id: str,
    options: DescriptionOptions | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: UserSchema = Depends(get_current_active_user),
):
    """
    Generate AI descriptions for all scenes in a tour.

    Creates descriptions for each scene based on panorama content.
    """
    job = await tour_ai.generate_tour_descriptions(
        db=db,
        tour_id=tour_id,
        user_id=current_user.id,
        options=options.model_dump() if options else None,
    )
    return {"job": job}


# ====================
# AI Job Management
# ====================


@router.get("/jobs/{job_id}", response_model=AIJobStatusResponse, summary="Get AI job")
async def get_ai_job(
    job_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: UserSchema = Depends(get_current_active_user),
):
    """
    Get the status and result of an AI processing job.

    Returns the job details including progress and results if completed.
    """
    job = await tour_ai.get_ai_job(
        db=db,
        job_id=job_id,
        user_id=current_user.id,
    )
    return {"job": job, "result": job.result}


@router.post(
    "/jobs/{job_id}/cancel",
    response_model=AIJobStatusResponse,
    summary="Cancel AI job",
    responses={409: {"description": "The job already finished or was cancelled."}},
)
async def cancel_ai_job(
    job_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: UserSchema = Depends(get_current_active_user),
):
    """
    Cancel a running AI processing job. Returns the job after cancellation.

    Only pending or processing jobs can be cancelled. Any other state returns
    409 with code JOB_NOT_CANCELLABLE.
    """
    cancelled = await tour_ai.cancel_ai_job(
        db=db,
        job_id=job_id,
        user_id=current_user.id,
    )
    if not cancelled:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "JOB_NOT_CANCELLABLE",
                "message": "Only pending or processing jobs can be cancelled.",
            },
        )
    job = await tour_ai.get_ai_job(db=db, job_id=job_id, user_id=current_user.id)
    return {"job": job, "result": job.result}
