"""Share cards: a public redirect to the composed OG image, and the cron run that makes the art."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Path, Response
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.api_v1.dependencies.cron import require_cron_secret
from app.core.database import get_db
from app.core.logging import get_logger
from app.schemas.imagery import ImageryRunRequest, ImageryRunResult
from app.services.ai.imagery import service, style

logger = get_logger(__name__)

router = APIRouter()
admin_router = APIRouter()

OG_KINDS = ("property", "locality", "blog", "city")
KIND_ALIASES = {"post": "blog"}  # the website names a blog post "post"
CACHE_ART = "public, max-age=300, s-maxage=3600, stale-while-revalidate=86400"
CACHE_FALLBACK = "public, max-age=60, s-maxage=300"  # short, so the card appears soon after the art is made


@router.get(
    "/og/{kind}/{slug}",
    status_code=302,
    response_class=RedirectResponse,
    responses={302: {"description": "Redirect to the share card image"}},
    summary="Share card image for a property, locality, blog post or city",
)
async def og_card(
    kind: str = Path(..., pattern="^(property|locality|blog|post|city)$"),
    slug: str = Path(..., max_length=200),
    db: AsyncSession = Depends(get_db),
) -> RedirectResponse:
    """302 to a 1200x630 card: generated art with the exact title, price and locality as text.

    This never calls the image model. A subject with no art yet gets the neutral brand card, with a
    short cache time. An unknown subject is 404."""
    kind = KIND_ALIASES.get(kind, kind)
    title, price, where = await service.card_text(db, kind, slug)
    key = style.image_key(kind, slug, style.OG_RATIO, style.OG_SIZE)
    row = await service.get_row(db, key)
    if row is not None and row.status == "ready" and row.public_id:
        try:
            url = service.compose_og_url(row.public_id, title, price=price, locality=where)
            return RedirectResponse(url, status_code=302, headers={"Cache-Control": CACHE_ART})
        except Exception as exc:  # Cloudinary not configured or SDK error: fall back, do not 500
            logger.error("OG compose failed for %s/%s: %s", kind, slug, exc)
    return RedirectResponse(
        service.fallback_og_url(), status_code=302, headers={"Cache-Control": CACHE_FALLBACK}
    )


@admin_router.post(
    "/run",
    response_model=ImageryRunResult,
    summary="Generate house-style art for subjects that have none (cron)",
    dependencies=[Depends(require_cron_secret)],
    responses={
        429: {"model": ImageryRunResult, "description": "The image provider is rate limited. See Retry-After."}
    },
)
async def run_imagery(body: ImageryRunRequest, response: Response, db: AsyncSession = Depends(get_db)) -> Any:
    """One bounded batch, four images at a time. Images already made are skipped, so repeating a
    call is safe. A provider 429 stops the batch: when nothing was made the answer is 429 with
    ``Retry-After``, otherwise 200 with ``retry_after`` set. Call again with a later nightly run."""
    ratio, size = (
        (style.HERO_RATIO, style.HERO_SIZE) if body.variant == "hero" else (style.OG_RATIO, style.OG_SIZE)
    )
    stats = await service.run_batch(
        db, list(body.kinds), max_items=body.max_items, max_seconds=body.max_seconds, ratio=ratio, size=size
    )
    data = stats.as_dict()
    if stats.generated == 0 and stats.rate_limited:
        return JSONResponse(data, status_code=429, headers={"Retry-After": str(stats.retry_after or 1800)})
    return data
