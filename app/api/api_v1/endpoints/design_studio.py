"""
AI Design Studio Image Generation Endpoint.

Public endpoint for generating AI images with 360Ghar AI.
Supports text-to-image and image-to-image (reimagine) modes.
"""

from __future__ import annotations

import asyncio
from typing import NoReturn

from fastapi import APIRouter, Depends, HTTPException, status

from app.core.logging import get_logger
from app.middleware.ai_limits import ai_limit
from app.schemas.ai_tools import StageRequest, StageResponse
from app.services.ai.image_gen.schemas import (
    DesignImageOut,
    ImageGenMode,
    ImageGenRequest,
    ImageGenResponse,
)

logger = get_logger(__name__)

router = APIRouter()

_generate_limit = ai_limit("design-studio:generate", per_minute=10)


def raise_image_failure(result: ImageGenResponse) -> NoReturn:
    """Raise the HTTP error for a failed generation: 429 quota, 503 unavailable, else 422."""
    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    if result.code == "QUOTA_EXCEEDED":
        status_code = status.HTTP_429_TOO_MANY_REQUESTS
    elif result.code in ("SERVICE_UNAVAILABLE", "TIMEOUT"):
        status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    logger.warning(
        "AI image generation failed: code=%s, error=%s",
        result.code,
        (result.error or "")[:200],
    )
    raise HTTPException(
        status_code=status_code,
        detail={"code": result.code, "message": result.error},
    )


@router.post("/generate", response_model=DesignImageOut, summary="Generate design image")
async def generate_design_image(
    request: ImageGenRequest,
    _rate_limit: None = Depends(_generate_limit),
) -> DesignImageOut:
    """
    Generate an AI design image. Free, no login required. Powered by 360Ghar AI.

    **Rate limit:** 10 requests per minute per IP address.

    **Modes:**
    - `text-to-image`: Generate from a text prompt
    - `image-to-image`: Transform an uploaded image with a prompt

    **Request body:**
    - `mode`: Generation mode
    - `prompt`: Text description (3-4000 chars)
    - `image`: Base64-encoded source image (required for image-to-image)
    - `mime_type`: MIME type of source image (e.g., image/jpeg)
    - `ratio`: Output aspect ratio (`1:1`, `3:4`, `4:3`, `16:9`, `9:16`, `2:3`, `3:2`, `21:9`). Default `1:1`

    **Response:** `image`, a base64 data URL. A failed generation returns an error
    envelope with a `code` (`QUOTA_EXCEEDED`, `SERVICE_UNAVAILABLE`, `CONTENT_BLOCKED`,
    and others).
    """
    from app.services.ai.image_gen.service import generate_image

    if request.mode == ImageGenMode.IMAGE_TO_IMAGE:
        if not request.image:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Source image is required for image-to-image mode",
            )
        if not request.mime_type:
            request.mime_type = "image/jpeg"

    logger.info(
        "AI image generation request: mode=%s, ratio=%s, prompt_len=%d",
        request.mode.value,
        request.ratio,
        len(request.prompt),
    )

    result = await generate_image(request)

    if not result.success:
        raise_image_failure(result)

    logger.info(
        "AI image generation succeeded: image_len=%d",
        len(result.image) if result.image else 0,
    )

    return DesignImageOut(image=result.image or "")


_stage_limit = ai_limit("design-studio:stage", per_minute=5)


@router.post(
    "/stage",
    response_model=StageResponse,
    summary="Virtually stage a room photo",
    dependencies=[Depends(_stage_limit)],
)
async def stage_room(request: StageRequest) -> StageResponse:
    """Add furniture to an empty-room photo. Free, no login required. Powered by 360Ghar AI.

    **Rate limit:** 5 requests per minute per IP address.

    The room's walls, floor, windows and layout are kept. The returned image always carries a
    visible "Virtually staged" band and the response has ``staged: true``. Show both wherever the
    image is used: a staged photo must not be presented as the real room.

    ``room_type`` and ``style`` are fixed choices. The image is a JPEG, PNG or WebP of up to 5 MB.
    """
    from app.services.ai import photos as photo_tools
    from app.services.ai.staging import stage_photo

    data, declared = photo_tools.decode_base64(request.image, request.mime_type, max_bytes=5 * 1024 * 1024)
    photo = await asyncio.to_thread(photo_tools.check_photo, data, declared)
    result = await stage_photo(photo, request.room_type, request.style)
    if not result.success:
        raise_image_failure(result)
    return StageResponse(image=result.image or "")
