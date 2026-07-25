"""
Shared helpers for tour AI operations.

Contains retry configuration, concurrency semaphore, AI provider wrappers,
prompt templates, image download utilities, and navigation hotspot helpers.
"""
from __future__ import annotations

import asyncio
import base64
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession
from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from app.core.exceptions import ServiceUnavailableException
from app.core.logging import get_logger
from app.models.enums import HotspotType
from app.models.tours import Hotspot, Tour
from app.services.ai import (
    AIMessage,
    AIProvider,
    AIProviderError,
    AIProviderType,
    VisionInput,
    get_ai_provider,
)

logger = get_logger(__name__)

# Retry configuration
MAX_RETRIES = 3
MIN_WAIT_SECONDS = 2
MAX_WAIT_SECONDS = 30

# Limit concurrent background AI tasks to avoid starving PgBouncer connections.
_AI_TASK_SEMAPHORE = asyncio.Semaphore(5)
_BACKGROUND_TASKS: set[asyncio.Task[Any]] = set()


def _track_background_task(coro) -> asyncio.Task[Any]:
    """Retain a background task reference until it completes."""
    task = asyncio.create_task(coro)
    _BACKGROUND_TASKS.add(task)
    task.add_done_callback(_BACKGROUND_TASKS.discard)
    return task


async def _run_with_semaphore(coro):
    """Run a background AI coroutine under the concurrency semaphore."""
    async with _AI_TASK_SEMAPHORE:
        try:
            await coro
        except Exception:
            logger.warning("Unhandled exception in background AI task", exc_info=True)


def _is_retryable_ai_provider_error(exc: BaseException) -> bool:
    """Retry soft provider failures; skip hard quota (fail-over already handled)."""
    if not isinstance(exc, AIProviderError):
        return False
    # Hard quota / cooldown errors set retryable=False so we fail over once
    # instead of re-thrashing the exhausted provider.
    if exc.retryable is False:
        return False
    return True


def _create_retry_decorator():
    """Create a retry decorator for AI provider calls."""
    return retry(
        stop=stop_after_attempt(MAX_RETRIES),
        wait=wait_exponential(multiplier=1, min=MIN_WAIT_SECONDS, max=MAX_WAIT_SECONDS),
        retry=retry_if_exception(_is_retryable_ai_provider_error),
        before_sleep=before_sleep_log(logger, log_level=30),  # WARNING level
        reraise=True,
    )


def _resolve_fallback_provider(primary: AIProvider) -> AIProvider | None:
    """Return the *other* configured vision provider to use as a fallback.

    Tour AI's primary is Gemini (via ``get_ai_provider()``); GLM is the
    fallback. Returns ``None`` if the fallback provider's API key is not
    configured, so the caller can re-raise the original error.
    """
    is_gemini = "gemini" in primary.name.lower()
    fallback_type = AIProviderType.GLM if is_gemini else AIProviderType.GEMINI
    try:
        return get_ai_provider(fallback_type)
    except ValueError:
        return None


@_create_retry_decorator()
async def _complete_json_with_retry(
    ai_provider,
    messages: list[AIMessage],
    vision_input: VisionInput | None = None,
) -> dict[str, Any]:
    """
    Call AI provider's complete_json with automatic retry on AIProviderError.

    On exhaustion, transparently retries once with the fallback vision
    provider (Gemini -> GLM, or vice versa) before giving up.

    Args:
        ai_provider: The primary AI provider instance
        messages: List of AI messages
        vision_input: Optional vision input for image analysis

    Returns:
        The parsed JSON response

    Raises:
        AIProviderError: After all retries (incl. fallback) are exhausted
    """
    try:
        return dict(await ai_provider.complete_json(messages, vision_input))
    except AIProviderError:
        fallback = _resolve_fallback_provider(ai_provider)
        if fallback is None:
            raise
        logger.warning(
            "Tour AI primary provider '%s' failed; trying fallback '%s'",
            ai_provider.name,
            fallback.name,
        )
        return dict(await fallback.complete_json(messages, vision_input))


# Room type mappings for scene analysis
ROOM_TYPES = [
    "living_room", "bedroom", "bathroom", "kitchen", "dining_room",
    "home_office", "hallway", "entrance", "balcony", "terrace",
    "garden", "garage", "basement", "attic", "pool_area",
    "gym", "laundry_room", "storage", "exterior", "other"
]

# Scene analysis prompt template
SCENE_ANALYSIS_PROMPT = """You are an expert real estate photographer and interior designer.
Analyze this 360° panorama image and provide detailed information about the room.
Respond in JSON format with the following structure:
{
    "room_type": "one of: living_room, bedroom, bathroom, kitchen, dining_room, home_office, hallway, entrance, balcony, terrace, garden, garage, basement, attic, pool_area, gym, laundry_room, storage, exterior, other",
    "room_confidence": 0.0 to 1.0,
    "suggested_title": "A descriptive title for this scene (e.g., 'Spacious Master Bedroom')",
    "suggested_description": "A 2-3 sentence description highlighting key features",
    "quality_score": 0 to 100 (integer, based on image quality, lighting, composition),
    "quality_issues": ["list of any quality issues found"],
    "features_detected": ["list of notable features like 'hardwood floors', 'large windows', 'fireplace']
}"""


def _build_hotspot_suggestion_prompt(scene_context: str, full_format: bool = True) -> str:
    """Build the system prompt for hotspot suggestions."""
    if full_format:
        return f"""You are an expert virtual tour designer.
Analyze this 360° panorama and suggest optimal hotspot placements.
Hotspots can be navigation points to other rooms or information points for notable features.

Available scenes to link to:
{scene_context}

Respond in JSON format with an array of hotspot suggestions:
{{
    "hotspots": [
        {{
            "type": "navigation" or "info",
            "yaw": horizontal angle in degrees (-180 to 180, where 0 is center of view),
            "pitch": vertical angle in degrees (-90 to 90, where 0 is horizon),
            "target_scene_id": "scene ID if type is navigation, null otherwise",
            "suggested_title": "title for the hotspot",
            "reasoning": "brief explanation of why this hotspot is suggested",
            "confidence": 0.0 to 1.0
        }}
    ]
}}

Focus on:
1. Doorways and passages that likely lead to other rooms
2. Notable features worth highlighting (fireplaces, views, art, furniture)
3. Logical flow between connected spaces"""
    else:
        return f"""You are an expert virtual tour designer.
Analyze this 360° panorama and suggest optimal hotspot placements.

Available scenes to link to:
{scene_context}

Respond in JSON format:
{{
    "hotspots": [
        {{
            "type": "navigation" or "info",
            "yaw": -180 to 180,
            "pitch": -90 to 90,
            "target_scene_id": "scene ID if navigation",
            "suggested_title": "title",
            "reasoning": "why this hotspot",
            "confidence": 0.0 to 1.0
        }}
    ]
}}"""


async def _ensure_navigation_hotspots(
    db: AsyncSession,
    tour: Tour,
) -> list[Hotspot]:
    """Create basic navigation hotspots for scenes lacking them."""
    from uuid import uuid4

    scenes = sorted(tour.scenes or [], key=lambda s: s.order_index)
    if len(scenes) < 2:
        return []

    created: list[Hotspot] = []
    for index, scene in enumerate(scenes[:-1]):
        next_scene = scenes[index + 1]
        # Skip if navigation hotspot already exists for this target.
        existing = any(
            hotspot.type == HotspotType.navigation and hotspot.target_scene_id == next_scene.id
            for hotspot in (scene.hotspots or [])
        )
        if existing:
            continue

        hotspot = Hotspot(
            id=str(uuid4()),
            scene_id=scene.id,
            type=HotspotType.navigation,
            position={"yaw": 0, "pitch": 0, "radius": None},
            target_scene_id=next_scene.id,
            title=next_scene.title or "Next",
            description=None,
            icon=None,
            icon_name=None,
            icon_color=None,
            icon_size=32,
            content=None,
            custom_data={"auto_generated": True},
            order_index=0,
            is_active=True,
        )
        db.add(hotspot)
        created.append(hotspot)

    if created:
        await db.commit()
        for hotspot in created:
            await db.refresh(hotspot)

    return created


# Cap outbound image downloads to bound memory/DoS from oversized assets.
MAX_DOWNLOAD_BYTES = 25 * 1024 * 1024


async def _download_image_bytes(url: str, timeout: float = 60.0) -> bytes:
    """Download an image (or any asset) and return the raw bytes."""
    from app.core.http import get_general_client

    client = get_general_client()
    async with client.stream(
        "GET", url, timeout=timeout, follow_redirects=False
    ) as response:
        if response.is_redirect or 300 <= response.status_code < 400:
            raise ValueError(
                f"Refusing to follow redirect for {url} (status {response.status_code})"
            )
        response.raise_for_status()
        buffer = bytearray()
        async for chunk in response.aiter_bytes():
            buffer.extend(chunk)
            if len(buffer) > MAX_DOWNLOAD_BYTES:
                raise ValueError(
                    f"Download exceeded {MAX_DOWNLOAD_BYTES} bytes: {url}"
                )
        return bytes(buffer)


async def _download_image_as_base64(url: str) -> tuple[str, str]:
    """Download an image and convert to base64."""
    from app.core.http import get_general_client
    from app.services.image_processing import validate_image_decodes

    client = get_general_client()
    response = await client.get(url, timeout=60.0)
    response.raise_for_status()

    # The content-type header alone is not reliable evidence of a decodable
    # image (redirects, stale/corrupted stored files, transcoding failures).
    try:
        validate_image_decodes(response.content)
    except Exception as exc:
        raise ValueError(f"Downloaded image at {url} is not a valid image: {exc}") from exc

    content_type = response.headers.get("content-type", "image/jpeg")
    if ";" in content_type:
        content_type = content_type.split(";")[0].strip()

    image_base64 = base64.b64encode(response.content).decode("utf-8")
    return image_base64, content_type


async def _get_ai_provider_safe():
    """Get AI provider with error handling."""
    try:
        return get_ai_provider()
    except ValueError as e:
        logger.error("Failed to get AI provider: %s", e)
        raise ServiceUnavailableException(
            detail="AI service is not configured. Please set GOOGLE_API_KEY."
        ) from e
