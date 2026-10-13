"""
Vastu Checker API Endpoints.

Public endpoints for analyzing floor plans using Vastu Shastra principles.
No authentication required.
"""

import base64

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status

from app.core.constants import DEFAULT_VISION_PROVIDER, VALID_VISION_PROVIDERS
from app.core.logging import get_logger
from app.middleware.rate_limit import EndpointRateLimiter
from app.services.ai.vastu import (
    NorthDirection,
    VastuAnalyzeRequest,
    VastuAnalyzeResponse,
    analyze_vastu,
)
from app.services.image_processing import validate_image_decodes

logger = get_logger(__name__)

router = APIRouter()

_analyze_limiter = EndpointRateLimiter(calls=5, period=60)


async def _check_analyze_rate_limit(request: Request) -> None:
    """FastAPI dependency: rate-limits the analyze endpoint (5 req/60s per IP)."""
    client_id = _analyze_limiter.get_client_id(request)
    allowed = await _analyze_limiter.check_rate_limit(client_id, "POST:/vastu/analyze")
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded. Please try again later.",
            headers={"Retry-After": "60"},
        )

# Allowed image types
ALLOWED_TYPES = ["image/jpeg", "image/jpg", "image/png", "image/webp"]

# Maximum file size: 5MB
MAX_FILE_SIZE = 5 * 1024 * 1024


@router.post("/analyze", response_model=VastuAnalyzeResponse, summary="Analyze floor plan vastu")
async def analyze_floor_plan(
    request: Request,
    image: UploadFile = File(..., description="Floor plan image (JPEG, PNG, or WebP)"),
    north_direction: str = Form(default="up", description="Direction of North in the image: up, down, left, right, unknown"),
    notes: str | None = Form(default=None, description="Additional notes about the property (max 1000 chars)"),
    _rate_limit: None = Depends(_check_analyze_rate_limit),
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
            detail=f"Invalid file type '{content_type}'. Allowed types: JPEG, PNG, WebP"
        )

    # Read and validate file size
    content = await image.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File too large. Maximum size: {MAX_FILE_SIZE / 1024 / 1024}MB"
        )

    if len(content) == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Empty file uploaded"
        )

    # Content-Type header is client-supplied and unreliable; confirm the
    # bytes actually decode before spending an AI provider call on them.
    try:
        validate_image_decodes(content)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or corrupted image file. Please upload a valid JPEG, PNG, or WebP image.",
        ) from None

    # Validate north direction
    try:
        north_dir = NorthDirection(north_direction.lower().strip())
    except ValueError:
        valid_options = [d.value for d in NorthDirection]
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid north direction '{north_direction}'. Valid options: {valid_options}"
        ) from None

    # Validate notes length
    if notes and len(notes) > 1000:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Notes too long. Maximum 1000 characters."
        )

    # Convert to base64
    image_base64 = base64.b64encode(content).decode("utf-8")

    # Build request
    analyze_request = VastuAnalyzeRequest(
        north_direction=north_dir,
        notes=notes,
    )

    logger.info("Starting Vastu analysis: provider=%s, north=%s, file_size=%s", DEFAULT_VISION_PROVIDER, north_dir.value, len(content))

    # Analyze
    result = await analyze_vastu(
        image_base64=image_base64,
        mime_type=content_type,
        request=analyze_request,
    )

    if not result.success:
        logger.warning("Vastu analysis failed: %s", result.error)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=result.error or "Analysis failed. Please try with a clearer floor plan image."
        )

    logger.info("Vastu analysis completed: score=%s", result.data.vastu_score if result.data else 'N/A')

    return result


@router.get("/health", summary="Vastu health check")
async def health_check():
    """Health check endpoint for the Vastu analyzer service."""
    return {
        "status": "healthy",
        "service": "vastu-analyzer",
        "providers": list(VALID_VISION_PROVIDERS),
    }
