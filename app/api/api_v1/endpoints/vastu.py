"""
Vastu Checker API Endpoints.

Public endpoints for analyzing floor plans using Vastu Shastra principles.
No authentication required.
"""

import base64

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from pydantic import BaseModel

from app.core.constants import DEFAULT_VISION_PROVIDER, VALID_VISION_PROVIDERS
from app.core.logging import get_logger
from app.middleware.ai_limits import ai_limit
from app.services.ai.vastu import (
    NorthDirection,
    VastuAnalyzeRequest,
    VastuAnalyzeResponse,
    analyze_vastu,
)
from app.services.image_processing import validate_image_decodes

logger = get_logger(__name__)

router = APIRouter()

_analyze_limit = ai_limit("vastu:analyze", per_minute=5)


# Allowed image types
ALLOWED_TYPES = ["image/jpeg", "image/jpg", "image/png", "image/webp"]

# Maximum file size: 5MB
MAX_FILE_SIZE = 5 * 1024 * 1024


@router.post("/analyze", response_model=VastuAnalyzeResponse, summary="Analyze floor plan vastu")
async def analyze_floor_plan(
    request: Request,
    image: UploadFile = File(..., description="Floor plan image (JPEG, PNG, or WebP)"),
    north_direction: NorthDirection = Form(
        default=NorthDirection.UP,
        description="Direction of North in the image: up, down, left, right, unknown",
    ),
    notes: str | None = Form(
        default=None, description="Additional notes about the property (max 1000 chars)"
    ),
    _rate_limit: None = Depends(_analyze_limit),
):
    """
    Analyze a floor plan image for Vastu Shastra compliance.

    This is a **public endpoint** - no authentication required.

    Upload a floor plan image and receive a comprehensive Vastu analysis including:
    - Overall Vastu score (1-10)
    - Room-by-room analysis with status ratings
    - Major defects identified with severity levels
    - Practical remedies and improvement suggestions
    - Full markdown report for display/download

    **Supported image formats:** JPEG, PNG, WebP (max 5MB)

    **North Direction Options:**
    - `up`: North is at the top of the image
    - `down`: North is at the bottom
    - `left`: North is to the left
    - `right`: North is to the right
    - `unknown`: Not sure (AI will attempt to detect)

    **AI Provider:** Agnes AI (`agnes-3.0-flash`).

    **Rate limit:** 5 requests per minute per IP address.
    """
    # Validate file type
    content_type = image.content_type or ""
    if content_type not in ALLOWED_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid file type '{content_type}'. Allowed types: JPEG, PNG, WebP",
        )

    # Read and validate file size
    content = await image.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File too large. Maximum size: {MAX_FILE_SIZE / 1024 / 1024}MB",
        )

    if len(content) == 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Empty file uploaded")

    # Content-Type header is client-supplied and unreliable; confirm the
    # bytes actually decode before spending an AI provider call on them.
    try:
        validate_image_decodes(content)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or corrupted image file. Please upload a valid JPEG, PNG, or WebP image.",
        ) from None

    # Validate notes length
    if notes and len(notes) > 1000:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Notes too long. Maximum 1000 characters.",
        )

    # Convert to base64
    image_base64 = base64.b64encode(content).decode("utf-8")

    # Build request
    analyze_request = VastuAnalyzeRequest(
        north_direction=north_direction,
        notes=notes,
    )

    logger.info(
        "Starting Vastu analysis: provider=%s, north=%s, file_size=%s",
        DEFAULT_VISION_PROVIDER,
        north_direction.value,
        len(content),
    )

    # Analyze
    result = await analyze_vastu(
        image_base64=image_base64,
        mime_type=content_type,
        request=analyze_request,
    )

    logger.info("Vastu analysis completed: score=%s", result.data.vastu_score)

    return result


class VastuHealthOut(BaseModel):
    """Health of the Vastu analyzer service."""

    status: str
    service: str
    providers: list[str]


@router.get("/health", summary="Vastu health check", response_model=VastuHealthOut)
async def health_check() -> VastuHealthOut:
    """Health check endpoint for the Vastu analyzer service."""
    return VastuHealthOut(
        status="healthy",
        service="vastu-analyzer",
        providers=list(VALID_VISION_PROVIDERS),
    )
