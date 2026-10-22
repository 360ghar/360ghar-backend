"""Draft a listing from photos (owners)."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Depends

from app.api.api_v1.dependencies.auth import get_current_active_user
from app.config import settings
from app.core.exceptions import ServiceUnavailableException
from app.core.logging import get_logger
from app.middleware.ai_limits import ai_limit
from app.schemas.ai_tools import ListingDraftRequest, ListingDraftResponse, PhotoIn
from app.services.ai import listing_draft as ld
from app.services.ai import photos as photo_tools
from app.services.ai.base import AIProviderConfig, AIProviderError

logger = get_logger(__name__)

router = APIRouter()

_limit = ai_limit("ai:listing-draft", per_minute=3, per_hour=20)
FETCH_CONCURRENCY = 4


def _provider() -> Any:
    from app.services.ai.providers.agnes import AgnesProvider

    if not settings.AGNES_AI_API_KEY:
        raise ServiceUnavailableException("Listing writer is not available", error_code="AI_UNAVAILABLE")
    return AgnesProvider(
        AIProviderConfig(
            api_key=settings.AGNES_AI_API_KEY, model=settings.AGNES_TEXT_MODEL,
            max_tokens=2000, temperature=0.4, timeout=120,
        )
    )


async def _load(item: PhotoIn, gate: asyncio.Semaphore) -> photo_tools.Photo:
    async with gate:
        declared: str | None = item.mime_type
        if item.base64 is not None:
            data, declared = photo_tools.decode_base64(item.base64, item.mime_type)
        else:
            data = await photo_tools.fetch_cloudinary(item.url or "")
        return await asyncio.to_thread(photo_tools.check_photo, data, declared)


async def _load_all(items: list[PhotoIn]) -> list[photo_tools.Photo]:
    """Load every photo; the first failure cancels the rest, so a bad request costs no more bandwidth."""
    gate = asyncio.Semaphore(FETCH_CONCURRENCY)
    tasks = [asyncio.create_task(_load(p, gate)) for p in items]
    try:
        return list(await asyncio.gather(*tasks))
    except BaseException:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        raise


@router.post(
    "/listing-draft",
    response_model=ListingDraftResponse,
    summary="Draft a listing title and description from photos",
    dependencies=[Depends(get_current_active_user), Depends(_limit)],
)
async def listing_draft(body: ListingDraftRequest) -> Any:
    """Sign-in required. Limited to 3 per minute and 20 per hour per IP.

    Send 1 to 8 photos, each as a Cloudinary URL of this account or as base64 (JPEG, PNG or WebP,
    up to 3 MB decoded). Every photo is checked (size, magic bytes against ``mime_type``, full
    decode) before the model sees any. Returns an editable ``title`` and ``description``, one
    ``rooms`` tag per photo, and ``flags`` for photo problems. Treat the text as a draft: the
    owner reviews it before saving the listing.
    """
    photos = await _load_all(body.photos)
    vision = [await asyncio.to_thread(photo_tools.shrink, p) for p in photos]
    provider = _provider()
    try:
        return await ld.draft_listing(provider, photos, vision, body.hints)
    except (AIProviderError, TimeoutError) as exc:
        logger.error("Listing draft provider error: %s", type(exc).__name__)
        raise ServiceUnavailableException("Listing writer is not available", error_code="AI_UNAVAILABLE") from exc
    finally:
        await provider.close()
