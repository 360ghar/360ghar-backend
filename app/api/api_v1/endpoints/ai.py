"""
AI Processing API Endpoints for 360 Virtual Tours.

This module provides REST API endpoints for AI-powered features:
- Scene analysis (room detection, quality scoring)
- Hotspot suggestions
- Description generation
- AI job management
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.api_v1.dependencies.auth import (
    get_current_active_user,
    get_current_active_user_short_session,
)
from app.core.database import get_bg_session_factory, get_db
from app.core.logging import get_logger
from app.schemas.pagination import CursorPage, CursorParams, build_cursor_page
from app.schemas.tour import (
    AIJobBase,
    AIJobResponse,
    AIJobStatusResponse,
    ApplyHotspotSuggestions,
    ApplySceneAnalysis,
    DescriptionOptions,
    TourGenerationRequest,
    TourGenerationResponse,
    TourOptimizationRequest,
    TourOptimizationResponse,
)
from app.schemas.user import User as UserSchema
from app.services import tour_ai
from app.services.storage import storage_service

router = APIRouter()
logger = get_logger(__name__)


# ====================
# Scene Analysis
# ====================

@router.post("/tours/{tour_id}/analyze", response_model=AIJobResponse, summary="Analyze tour scenes")
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
# Tour Generation & Optimization
# ====================

@router.post("/tours/generate", response_model=TourGenerationResponse, summary="Generate tour")
async def generate_tour(
    images: list[UploadFile] = File(..., description="360 panorama images to create tour from"),
    title: str | None = Form(None, max_length=255, description="Tour title"),
    description: str | None = Form(None, max_length=5000, description="Tour description"),
    auto_detect_rooms: bool = Form(True, description="Automatically detect room types"),
    auto_place_hotspots: bool = Form(False, description="Automatically suggest hotspot placements"),
    auto_generate_descriptions: bool = Form(True, description="Generate AI descriptions for scenes"),
    spatial: bool = Form(True, description="Use spatial doorway detection for hotspot placement"),
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
                detail=f"Invalid file type: {img.content_type}. Allowed: {', '.join(allowed_types)}"
            )

    # Upload images to storage
    upload_results = await storage_service.upload_batch(
        images,
        db=None,
        user_id=current_user.id,
        folder="scenes",
        visibility="private",
    )

    # Extract image URLs from upload results
    image_urls = []
    for result in upload_results:
        url = result.get("url") or result.get("public_url")
        if url:
            image_urls.append(url)
        else:
            logger.warning("Upload result missing URL: %s", result)

    if not image_urls:
        raise HTTPException(status_code=500, detail="Failed to upload images")

    # Generate a default title if not provided
    tour_title = title if title else f"AI Generated Tour ({len(images)} scenes)"

    # Create TourGenerationRequest with uploaded image URLs.
    # spatial=True uses vision-based doorway detection; when spatial is off, the
    # naive suggest_hotspots fallback is used only if auto_place_hotspots is set.
    payload = TourGenerationRequest(
        title=tour_title,
        description=description,
        image_urls=image_urls,
        generate_titles=auto_detect_rooms,
        generate_descriptions=auto_generate_descriptions,
        suggest_hotspots=auto_place_hotspots and not spatial,
        spatial=spatial,
    )

    session_factory = get_bg_session_factory()
    async with session_factory() as db:
        job, tour, scene_ids = await tour_ai.generate_tour(
            db=db,
            user_id=current_user.id,
            data=payload,
        )
        return {"job": job, "tour_id": tour.id, "scene_ids": scene_ids}


@router.post("/tours/{tour_id}/optimize", response_model=TourOptimizationResponse, summary="Optimize tour")
async def optimize_tour(
    tour_id: str,
    payload: TourOptimizationRequest | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: UserSchema = Depends(get_current_active_user),
):
    """
    Optimize an existing tour using AI suggestions.
    """
    job = await tour_ai.optimize_tour(
        db=db,
        tour_id=tour_id,
        user_id=current_user.id,
        options=payload.model_dump(exclude_unset=True) if payload else None,
    )
    return {"job": job}


@router.post("/tours/{tour_id}/spatial-connect", response_model=TourOptimizationResponse, summary="Spatial connect tour scenes")
async def spatial_connect_tour(
    tour_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: UserSchema = Depends(get_current_active_user),
):
    """
    Run the spatial AI pipeline on an existing tour to auto-connect scenes.

    Analyzes every panorama in the tour to detect doorways and room types,
    then places navigation hotspots at the detected doorway positions.
    Existing auto-generated spatial hotspots are replaced.
    First deletes all hotspots with custom_data.spatial=true, then re-runs.
    """
    job = await tour_ai.spatial_connect_existing_tour(
        db=db,
        tour_id=tour_id,
        user_id=current_user.id,
    )
    return {"job": job}


@router.post("/tours/{tour_id}/floor-plans/{floor_plan_id}/analyze", response_model=AIJobResponse, summary="AI analyze floor plan")
async def analyze_floor_plan(
    tour_id: str,
    floor_plan_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: UserSchema = Depends(get_current_active_user),
):
    """
    Analyze a floor plan image using AI to auto-detect rooms and place markers.

    Uses vision AI to identify room labels and positions in the floor plan,
    then matches them to the tour's 360° scenes by room type.
    """
    job = await tour_ai.analyze_floor_plan_ai(
        db=db,
        tour_id=tour_id,
        floor_plan_id=floor_plan_id,
        user_id=current_user.id,
    )
    return {"job": job}


@router.post("/scenes/{scene_id}/analyze", response_model=AIJobResponse, summary="Analyze scene")
async def analyze_scene(
    scene_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: UserSchema = Depends(get_current_active_user),
):
    """
    Analyze a single scene using AI.

    Returns room type, suggested title/description, and quality assessment.
    """
    job = await tour_ai.analyze_scene(
        db=db,
        scene_id=scene_id,
        user_id=current_user.id,
    )
    return {"job": job}


# ====================
# Hotspot Suggestions
# ====================

@router.post("/scenes/{scene_id}/hotspots", response_model=AIJobResponse, summary="Suggest scene hotspots")
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


@router.post("/tours/{tour_id}/hotspots", response_model=AIJobResponse, summary="Suggest tour hotspots")
async def suggest_tour_hotspots(
    tour_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: UserSchema = Depends(get_current_active_user),
):
    """
    Get AI-suggested hotspots for all scenes in a tour.

    Analyzes all panoramas and suggests navigation hotspots to connect scenes.
    """
    job = await tour_ai.suggest_tour_hotspots(
        db=db,
        tour_id=tour_id,
        user_id=current_user.id,
    )
    return {"job": job}


# ====================
# Description Generation
# ====================

@router.post("/scenes/{scene_id}/description", response_model=AIJobResponse, summary="Generate scene description")
async def generate_scene_description(
    scene_id: str,
    options: DescriptionOptions | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: UserSchema = Depends(get_current_active_user),
):
    """
    Generate AI description for a scene.

    Creates a compelling description based on the panorama content.
    """
    job = await tour_ai.generate_scene_description(
        db=db,
        scene_id=scene_id,
        user_id=current_user.id,
        options=options.model_dump() if options else None,
    )
    return {"job": job}


@router.post("/tours/{tour_id}/descriptions", response_model=AIJobResponse, summary="Generate tour descriptions")
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

@router.get("/jobs", response_model=CursorPage[AIJobBase], summary="List AI jobs")
async def list_ai_jobs(
    status_filter: str | None = Query(None, alias="status", description="Filter by status"),
    page: CursorParams = Depends(),
    db: AsyncSession = Depends(get_db),
    current_user: UserSchema = Depends(get_current_active_user),
):
    """
    List AI processing jobs for the current user.

    Returns jobs with optional status filtering and cursor pagination.
    """
    rows, next_payload, total = await tour_ai.get_user_ai_jobs(
        db=db,
        user_id=current_user.id,
        status_filter=status_filter,
        cursor_payload=page.decoded(),
        limit=page.limit,
        with_total=page.include_total,
    )
    return build_cursor_page(
        [AIJobBase.model_validate(r) for r in rows],
        limit=page.limit,
        next_payload=next_payload,
        total=total,
    )


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


@router.post("/jobs/{job_id}/cancel", summary="Cancel AI job")
async def cancel_ai_job(
    job_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: UserSchema = Depends(get_current_active_user),
):
    """
    Cancel a running AI processing job.

    Only pending or processing jobs can be cancelled.
    """
    success = await tour_ai.cancel_ai_job(
        db=db,
        job_id=job_id,
        user_id=current_user.id,
    )
    return {"success": success}


# ====================
# Apply Suggestions
# ====================

@router.post("/tours/{tour_id}/apply-analysis", summary="Apply scene analysis")
async def apply_scene_analysis(
    tour_id: str,
    data: ApplySceneAnalysis,
    db: AsyncSession = Depends(get_db),
    current_user: UserSchema = Depends(get_current_active_user),
):
    """
    Apply AI scene analysis suggestions to scenes.

    Updates scene titles and descriptions based on selected suggestions.
    """
    updated = await tour_ai.apply_scene_analysis(
        db=db,
        tour_id=tour_id,
        user_id=current_user.id,
        suggestions=data.suggestions,
    )
    return {"updated": updated}


@router.post("/scenes/{scene_id}/apply-hotspots", response_model=dict, summary="Apply hotspot suggestions")
async def apply_hotspot_suggestions(
    scene_id: str,
    data: ApplyHotspotSuggestions,
    job_id: str | None = Query(None, description="Job ID containing suggestions"),
    db: AsyncSession = Depends(get_db),
    current_user: UserSchema = Depends(get_current_active_user),
):
    """
    Apply AI hotspot suggestions to a scene.

    Creates hotspots based on the selected suggestion IDs.
    """
    hotspots = await tour_ai.apply_hotspot_suggestions(
        db=db,
        scene_id=scene_id,
        user_id=current_user.id,
        suggestion_ids=data.suggestion_ids,
        job_id=job_id,
    )
    # Convert to dict for JSON response
    return {"hotspots": [{"id": h.id, "type": h.type.value, "title": h.title} for h in hotspots]}
