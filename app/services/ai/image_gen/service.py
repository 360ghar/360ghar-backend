"""
AI Image Generation Service.

Calls the Agnes AI images API (OpenAI-compatible ``/images/generations``)
for both text-to-image and image-to-image generation.

Response format is requested as ``b64_json`` inside ``extra_body``. If the
API returns a URL instead, the image is downloaded and converted to a data URL.
"""

from __future__ import annotations

import base64
import logging
import time
from typing import Any

import httpx
from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception,
    stop_after_attempt,
)

from app.config import settings
from app.core.http import get_general_client
from app.core.logging import get_logger
from app.services.ai.base import _parse_retry_after_seconds, _retry_wait
from app.services.ai.image_gen.schemas import (
    ImageGenMode,
    ImageGenRequest,
    ImageGenResponse,
)

logger = get_logger(__name__)

# 1K (1024 px) keeps the base64 response near 1.5 MB for phones; 2K is about 5 MB.
_IMAGE_SIZE = "1K"

_MAX_RETRIES = 5
_RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}

_TIMEOUT = 300.0

_TXT2IMG_INSTRUCTION = (
    "You are an expert interior/exterior design visualizer. Generate a photorealistic, "
    "high-quality architectural visualization based on the user's description. "
    "The output should look like a professional design render with realistic lighting, "
    "textures, and materials."
)
_IMG2IMG_INSTRUCTION = (
    "You are an expert interior/exterior designer. Transform the provided image "
    "according to the user's prompt while preserving the room layout, architecture, "
    "and structural elements. Only change colors, materials, textures, decor, and styling. "
    "Generate a photorealistic, high-quality result."
)


class _AgnesImageError(Exception):
    """Non-2xx response from the Agnes images API."""

    def __init__(self, status_code: int, body: str, retry_after_seconds: float | None = None):
        super().__init__(f"Agnes image API error {status_code}: {body}")
        self.status_code = status_code
        self.body = body
        self.retry_after_seconds = retry_after_seconds  # read by _retry_wait


def _is_retryable(exc: BaseException) -> bool:
    # Timeouts are not retried: each attempt can take minutes.
    if isinstance(exc, httpx.TimeoutException):
        return False
    if isinstance(exc, httpx.RequestError):
        return True
    return isinstance(exc, _AgnesImageError) and exc.status_code in _RETRYABLE_STATUS_CODES


async def generate_image(request: ImageGenRequest) -> ImageGenResponse:
    """
    Generate an image with Agnes AI.

    Args:
        request: Generation request with mode, prompt, ratio, and optional source image.

    Returns:
        ImageGenResponse with base64 data URL on success, or error details on failure.
    """
    if not settings.AGNES_AI_API_KEY:
        return ImageGenResponse(
            success=False,
            error="Image generation is not configured (missing API key)",
            code="SERVICE_UNAVAILABLE",
        )

    try:
        data = await _call_agnes(_build_payload(request))
    except httpx.TimeoutException as exc:
        logger.error("Image generation timed out: %s", exc)
        return ImageGenResponse(success=False, error="Image generation timed out", code="TIMEOUT")
    except _AgnesImageError as exc:
        logger.error("Image generation failed: %s", exc)
        return ImageGenResponse(success=False, error=str(exc)[:500], code=_map_error_code(exc))
    except Exception as exc:
        logger.error("Image generation failed: %s", exc)
        return ImageGenResponse(success=False, error=str(exc)[:500], code="GENERATION_FAILED")

    image_data_url = await _extract_image(data)
    if not image_data_url:
        return ImageGenResponse(
            success=False,
            error="The model did not return an image. Try a different prompt.",
            code="NO_IMAGE_RETURNED",
        )

    return ImageGenResponse(success=True, image=image_data_url)


def _map_error_code(exc: _AgnesImageError) -> str:
    body = exc.body.lower()
    if exc.status_code in (402, 429):
        return "QUOTA_EXCEEDED"
    if exc.status_code == 400 and any(word in body for word in ("safety", "moderation", "content policy", "blocked")):
        return "CONTENT_BLOCKED"
    return "GENERATION_FAILED"


def _build_payload(request: ImageGenRequest) -> dict[str, Any]:
    """Build the images/generations request body."""
    is_img2img = request.mode == ImageGenMode.IMAGE_TO_IMAGE and bool(request.image)
    instruction = _IMG2IMG_INSTRUCTION if is_img2img else _TXT2IMG_INSTRUCTION

    extra_body: dict[str, Any] = {"response_format": "b64_json"}
    if is_img2img:
        mime = request.mimeType or "image/jpeg"
        extra_body["image"] = [f"data:{mime};base64,{request.image}"]

    return {
        "model": settings.AGNES_IMAGE_MODEL,
        "prompt": f"{instruction}\n\n{request.prompt}",
        "size": _IMAGE_SIZE,
        "ratio": request.ratio,
        "extra_body": extra_body,
    }


async def _call_agnes(payload: dict[str, Any]) -> dict[str, Any]:
    """POST to the Agnes images API with exponential-backoff retries."""

    @retry(
        stop=stop_after_attempt(_MAX_RETRIES),
        wait=_retry_wait,
        retry=retry_if_exception(_is_retryable),
        before_sleep=before_sleep_log(logger, logging.WARNING),
        reraise=True,
    )
    async def _do_post() -> dict[str, Any]:
        url = f"{settings.AGNES_API_BASE}/images/generations"
        t_start = time.monotonic()
        resp = await get_general_client().post(
            url,
            json=payload,
            headers={
                "Authorization": f"Bearer {settings.AGNES_AI_API_KEY}",
                "Content-Type": "application/json",
            },
            timeout=_TIMEOUT,
        )
        logger.info(
            "Agnes image API call completed",
            extra={"duration_ms": round((time.monotonic() - t_start) * 1000, 1), "status": resp.status_code},
        )
        if resp.status_code >= 400:
            body = resp.text[:1000]
            raise _AgnesImageError(resp.status_code, body, _parse_retry_after_seconds(resp.headers, body))
        data: dict[str, Any] = resp.json()
        return data

    return await _do_post()


async def _extract_image(result: dict[str, Any]) -> str | None:
    """Return a ``data:`` URL for the first image in an images API response, or None."""
    try:
        item = result["data"][0]
    except (KeyError, IndexError, TypeError):
        return None

    if not isinstance(item, dict):
        return None
    b64 = item.get("b64_json")
    if b64:
        return f"data:image/png;base64,{b64}"

    url = item.get("url")
    if url:
        try:
            resp = await get_general_client().get(url, timeout=60.0)
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            logger.warning("Failed to download generated image: %s", exc)
            return None
        mime = resp.headers.get("content-type", "image/png").split(";")[0].strip()
        return f"data:{mime};base64,{base64.b64encode(resp.content).decode('ascii')}"

    return None
