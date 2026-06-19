"""
AI Design Studio Image Generation Endpoint.

Authenticated endpoint for generating AI images using Gemini 3 Pro Image Preview.
Supports text-to-image and image-to-image (reimagine) modes.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.api_v1.dependencies.auth import get_current_active_user
from app.core.logging import get_logger
from app.schemas.user import User as UserSchema
from app.services.ai.image_gen.schemas import (
    ImageGenMode,
    ImageGenRequest,
    ImageGenResponse,
)

logger = get_logger(__name__)

router = APIRouter()


@router.post("/generate", response_model=ImageGenResponse, summary="Generate design image")
async def generate_design_image(
    request: ImageGenRequest,
    current_user: UserSchema = Depends(get_current_active_user),
) -> ImageGenResponse:
    """
    Generate an AI design image using Gemini 3 Pro Image Preview.

    **Requires authentication** (Supabase Bearer token).

    **Modes:**
    - `text-to-image`: Generate from a text prompt
    - `image-to-image`: Transform an uploaded image with a prompt

    **Request body:**
    - `mode`: Generation mode
    - `prompt`: Text description (3-4000 chars)
    - `image`: Base64-encoded source image (required for image-to-image)
    - `mimeType`: MIME type of source image (e.g., image/jpeg)

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
        "AI image generation request: mode=%s, user=%s, prompt_len=%d",
        request.mode.value,
        current_user.id,
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
        "AI image generation succeeded: user=%s, image_len=%d",
        current_user.id,
        len(result.image) if result.image else 0,
    )

    return result
