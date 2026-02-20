"""
Public HTML endpoints for social share previews.

These routes are intentionally server-rendered (no SPA/JS required for crawlers)
so that Open Graph / Twitter metadata works for link unfurling.
"""

from __future__ import annotations

import html
from typing import Optional
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.database import get_db
from app.models.enums import TourStatus
from app.models.tours import Scene, Tour


router = APIRouter()


def _is_safe_absolute_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
    except Exception:
        return False
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _get_frontend_base_url(request: Request) -> str:
    return (
        (settings.PUBLIC_APP_URL or "").rstrip("/")
        or (settings.PUBLIC_BASE_URL or "").rstrip("/")
        or str(request.base_url).rstrip("/")
    )


@router.get("/share/tours/{tour_id}", response_class=HTMLResponse)
async def tour_share_preview(
    tour_id: str,
    request: Request,
    redirect: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    """
    Render Open Graph/Twitter meta tags for a tour and redirect humans to the viewer.

    The optional `redirect` query param allows the caller (frontend) to control where
    humans land after crawlers read the metadata.
    """
    query = (
        select(Tour)
        .where(and_(Tour.id == tour_id, Tour.deleted_at.is_(None)))
        .options(selectinload(Tour.scenes))
    )
    result = await db.execute(query)
    tour = result.scalar_one_or_none()

    if not tour or tour.status != TourStatus.published or not tour.is_public:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tour not found")

    scenes = list(getattr(tour, "scenes", []) or [])
    first_scene: Optional[Scene] = scenes[0] if scenes else None

    title = tour.title or "Virtual Tour"
    description = tour.description or "Explore this 360° virtual tour."

    image_url = (
        tour.thumbnail_url
        or (first_scene.thumbnail_url if first_scene else None)
        or (first_scene.image_url if first_scene else None)
        or ""
    )

    frontend_base = _get_frontend_base_url(request)
    viewer_url = f"{frontend_base}/view/{tour_id}"

    redirect_url = redirect if redirect and _is_safe_absolute_url(redirect) else viewer_url
    share_url = str(request.url)

    title_esc = html.escape(title)
    desc_esc = html.escape(description)
    share_url_esc = html.escape(share_url)
    viewer_url_esc = html.escape(viewer_url)
    redirect_url_esc = html.escape(redirect_url)
    image_url_esc = html.escape(image_url)

    html_doc = f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>{title_esc}</title>

    <meta name="description" content="{desc_esc}" />

    <meta property="og:title" content="{title_esc}" />
    <meta property="og:description" content="{desc_esc}" />
    <meta property="og:type" content="website" />
    <meta property="og:url" content="{share_url_esc}" />
    {"<meta property=\"og:image\" content=\"" + image_url_esc + "\" />" if image_url else ""}

    <meta name="twitter:card" content="summary_large_image" />
    <meta name="twitter:title" content="{title_esc}" />
    <meta name="twitter:description" content="{desc_esc}" />
    {"<meta name=\"twitter:image\" content=\"" + image_url_esc + "\" />" if image_url else ""}

    <link rel="canonical" href="{viewer_url_esc}" />

    <meta http-equiv="refresh" content="0; url={redirect_url_esc}" />
    <script>
      window.location.replace({redirect_url!r});
    </script>
  </head>
  <body>
    <p>Redirecting to <a href="{redirect_url_esc}">{viewer_url_esc}</a>…</p>
  </body>
</html>
"""

    return HTMLResponse(content=html_doc)

