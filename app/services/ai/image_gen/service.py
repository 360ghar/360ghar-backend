"""
AI Image Generation Service.

Calls Gemini 3 Pro Image Preview model via the Google Generative Language REST API
for both text-to-image and image-to-image generation.

The image generation API uses ``generateContent`` with
``responseModalities: ["IMAGE", "TEXT"]`` to request image output.
"""

from __future__ import annotations

import time
from typing import Any

import httpx
from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from app.config import settings
from app.core.logging import get_logger
from app.services.ai.image_gen.schemas import (
    ImageGenMode,
    ImageGenRequest,
    ImageGenResponse,
)

logger = get_logger(__name__)

_GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"
_DEFAULT_MODEL = "gemini-3-pro-image-preview"

_MAX_RETRIES = 2
_RETRY_MIN_WAIT = 2
_RETRY_MAX_WAIT = 10
_RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}

_TIMEOUT = 180


def _is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, httpx.RequestError):
        return True
    if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code in _RETRYABLE_STATUS_CODES:
        return True
    return False


async def generate_image(request: ImageGenRequest) -> ImageGenResponse:
    """
    Generate an image using Gemini 3 Pro Image Preview.

    Args:
        request: Generation request with mode, prompt, and optional source image.

    Returns:
        ImageGenResponse with base64 data URL on success, or error details on failure.
    """
    api_key = settings.GOOGLE_API_KEY
    if not api_key:
        return ImageGenResponse(
            success=False,
            error="Image generation is not configured (missing API key)",
            code="SERVICE_UNAVAILABLE",
        )

    url = f"{_GEMINI_API_BASE}/{_DEFAULT_MODEL}:generateContent?key={api_key}"
    payload = _build_payload(request)

    try:
        result = await _call_gemini(url, payload)
    except Exception as exc:
        logger.error("Image generation failed: %s", exc)
        msg = str(exc)
        if "timeout" in msg.lower():
            code = "TIMEOUT"
        elif "quota" in msg.lower() or "429" in msg:
            code = "QUOTA_EXCEEDED"
        elif "safety" in msg.lower() or "blocked" in msg.lower():
            code = "CONTENT_BLOCKED"
        else:
            code = "GENERATION_FAILED"
        return ImageGenResponse(success=False, error=msg[:500], code=code)

    image_data_url = _extract_image(result)
    if not image_data_url:
        return ImageGenResponse(
            success=False,
            error="The model did not return an image. Try a different prompt.",
            code="NO_IMAGE_RETURNED",
        )

    return ImageGenResponse(success=True, image=image_data_url)


def _build_payload(request: ImageGenRequest) -> dict[str, Any]:
    """Build the Gemini generateContent request body."""
    parts: list[dict[str, Any]] = [{"text": request.prompt}]

    if request.mode == ImageGenMode.IMAGE_TO_IMAGE and request.image:
        mime = request.mimeType or "image/jpeg"
        parts.insert(
            0,
            {
                "inlineData": {
                    "mimeType": mime,
                    "data": request.image,
                }
            },
        )

    contents = [{"role": "user", "parts": parts}]

    generation_config: dict[str, Any] = {
        "responseModalities": ["IMAGE", "TEXT"],
    }

    system_parts: list[dict[str, Any]] = []
    if request.mode == ImageGenMode.IMAGE_TO_IMAGE:
        system_parts.append(
            {
                "text": (
                    "You are an expert interior/exterior designer. Transform the provided image "
                    "according to the user's prompt while preserving the room layout, architecture, "
                    "and structural elements. Only change colors, materials, textures, decor, and styling. "
                    "Generate a photorealistic, high-quality result."
                )
            }
        )
    else:
        system_parts.append(
            {
                "text": (
                    "You are an expert interior/exterior design visualizer. Generate a photorealistic, "
                    "high-quality architectural visualization based on the user's description. "
                    "The output should look like a professional design render with realistic lighting, "
                    "textures, and materials."
                )
            }
        )

    payload: dict[str, Any] = {
        "contents": contents,
        "generationConfig": generation_config,
    }
    if system_parts:
        payload["systemInstruction"] = {"parts": system_parts}

    return payload


async def _call_gemini(url: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Call Gemini API with retries."""
    import logging

    @retry(
        stop=stop_after_attempt(_MAX_RETRIES),
        wait=wait_exponential(multiplier=1, min=_RETRY_MIN_WAIT, max=_RETRY_MAX_WAIT),
        retry=retry_if_exception(_is_retryable),
        before_sleep=before_sleep_log(logger, logging.WARNING),
        reraise=True,
    )
    async def _do_post() -> dict[str, Any]:
        from app.core.http import get_general_client

        client = get_general_client()
        t_start = time.monotonic()
        resp = await client.post(
            url,
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=float(_TIMEOUT),
        )
        elapsed_ms = (time.monotonic() - t_start) * 1000
        logger.info(
            "Gemini image API call completed",
            extra={"duration_ms": round(elapsed_ms, 1), "status": resp.status_code},
        )

        if resp.status_code in _RETRYABLE_STATUS_CODES:
            raise httpx.HTTPStatusError(
                f"Retryable HTTP {resp.status_code}",
                request=resp.request,
                response=resp,
            )

        if resp.status_code >= 400:
            body = resp.text[:1000]
            raise RuntimeError(f"Gemini API error {resp.status_code}: {body}")

        data: dict[str, Any] = resp.json()
        return data

    return await _do_post()


def _extract_image(result: dict[str, Any]) -> str | None:
    """
    Extract base64 image from Gemini response.

    Returns a data URL string (e.g., 'data:image/png;base64,...') or None.
    """
    try:
        candidates = result.get("candidates", [])
        if not candidates:
            return None

        parts = candidates[0].get("content", {}).get("parts", [])
        for part in parts:
            inline_data = part.get("inlineData") or part.get("inline_data")
            if inline_data:
                mime = inline_data.get("mimeType") or inline_data.get("mime_type", "image/png")
                data = inline_data.get("data", "")
                if data:
                    return f"data:{mime};base64,{data}"
    except (KeyError, IndexError, TypeError) as exc:
        logger.warning("Failed to extract image from response: %s", exc)
    return None
