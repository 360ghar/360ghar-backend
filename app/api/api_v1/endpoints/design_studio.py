"""
AI Design Studio Image Generation Endpoint.

Public endpoint for generating AI images with Agnes AI.
Supports text-to-image and image-to-image (reimagine) modes.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.core.logging import get_logger
from app.middleware.rate_limit import EndpointRateLimiter
from app.services.ai.image_gen.schemas import (
    ImageGenMode,
    ImageGenRequest,
    ImageGenResponse,
)

logger = get_logger(__name__)

router = APIRouter()

_generate_limiter = EndpointRateLimiter(calls=10, period=60)


async def _check_generate_rate_limit(request: Request) -> None:
    """FastAPI dependency: rate-limits image generation (10 req/60s per IP)."""
    client_id = _generate_limiter.get_client_id(request)
    allowed = await _generate_limiter.check_rate_limit(client_id, "POST:/design-studio/generate")
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded. Please try again later.",
            headers={"Retry-After": "60"},
        )


@router.post("/generate", response_model=ImageGenResponse, summary="Generate design image")
async def generate_design_image(
    request: ImageGenRequest,
    _rate_limit: None = Depends(_check_generate_rate_limit),
) -> ImageGenResponse:
    """
    Generate an AI design image. Free, no login required. Powered by Agnes AI.

    **Rate limit:** 10 requests per minute per IP address.

    **Modes:**
    - `text-to-image`: Generate from a text prompt
    - `image-to-image`: Transform an uploaded image with a prompt

    **Request body:**
    - `mode`: Generation mode
    - `prompt`: Text description (3-4000 chars)
    - `image`: Base64-encoded source image (required for image-to-image)
    - `mimeType`: MIME type of source image (e.g., image/jpeg)
    - `ratio`: Output aspect ratio (`1:1`, `3:4`, `4:3`, `16:9`, `9:16`, `2:3`, `3:2`, `21:9`). Default `1:1`

    **Response:**
    - `success`: Whether generation succeeded
    - `image`: Base64 data URL of generated image (on success)
    - `error`: Error message (on failure)
    - `code`: Error code (on failure)
    """
    from app.services.ai.image_gen.service import generate_image

    if request.mode == ImageGenMode.IMAGE_TO_IMAGE:
        if not request.image:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Source image is required for image-to-image mode",
            )
        if not request.mimeType:
            request.mimeType = "image/jpeg"

    logger.info(
        "AI image generation request: mode=%s, ratio=%s, prompt_len=%d",
        request.mode.value,
        request.ratio,
        len(request.prompt),
    )

    result = await generate_image(request)

    if not result.success:
        status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
        if result.code == "QUOTA_EXCEEDED":
            status_code = status.HTTP_429_TOO_MANY_REQUESTS
        elif result.code == "SERVICE_UNAVAILABLE":
            status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        elif result.code == "CONTENT_BLOCKED":
            status_code = status.HTTP_422_UNPROCESSABLE_ENTITY

        logger.warning(
            "AI image generation failed: code=%s, error=%s",
            result.code,
            (result.error or "")[:200],
        )
        raise HTTPException(
            status_code=status_code,
            detail={"code": result.code, "message": result.error},
        )

    logger.info(
        "AI image generation succeeded: image_len=%d",
        len(result.image) if result.image else 0,
    )

    return result
