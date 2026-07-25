"""
Public HTML endpoints for social share previews.

These routes are intentionally server-rendered (no SPA/JS required for crawlers)
so that Open Graph / Twitter metadata works for link unfurling.
"""

from __future__ import annotations

import html
import json
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse
from sqlalchemy import ColumnElement, and_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.core.database import get_db
from app.models.enums import TourStatus, TourVisibility
from app.models.tours import Scene, Tour

router = APIRouter()


def _allowed_redirect_hosts() -> set[str]:
    hosts: set[str] = set()
    for raw in (settings.PUBLIC_APP_URL, settings.PUBLIC_BASE_URL):
        if not raw:
            continue
        parsed = urlparse(raw)
        if parsed.hostname:
            hosts.add(parsed.hostname.lower())
    return hosts


def _is_safe_absolute_url(url: str, request: Request | None = None) -> bool:
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return False
    allowed = _allowed_redirect_hosts()
    if allowed:
        return parsed.hostname.lower() in allowed
    # No PUBLIC_APP_URL/PUBLIC_BASE_URL configured (e.g. local dev) — fall
    # back to matching the current request's own host so redirects still
    # work locally without allowing arbitrary external hosts.
    if request is not None:
        return parsed.hostname.lower() == (
            urlparse(str(request.base_url)).hostname or ""
        ).lower()
    return False


def _get_frontend_base_url(request: Request) -> str:
    return (
        (settings.PUBLIC_APP_URL or "").rstrip("/")
        or (settings.PUBLIC_BASE_URL or "").rstrip("/")
        or str(request.base_url).rstrip("/")
    )


def _render_tour_share(tour: Tour, request: Request, redirect: str | None) -> HTMLResponse:
    """Render the OG/Twitter share preview HTML for an already-fetched tour."""
    tour_id = tour.id
    scenes = list(getattr(tour, "scenes", []) or [])
    first_scene: Scene | None = scenes[0] if scenes else None

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

    redirect_url = (
        redirect if redirect and _is_safe_absolute_url(redirect, request) else viewer_url
    )
    share_url = str(request.url)

    title_esc = html.escape(title)
    desc_esc = html.escape(description)
    share_url_esc = html.escape(share_url)
    viewer_url_esc = html.escape(viewer_url)
    redirect_url_esc = html.escape(redirect_url)
    image_url_esc = html.escape(image_url)
    og_image_meta = (
        f'<meta property="og:image" content="{image_url_esc}" />' if image_url else ""
    )
    twitter_image_meta = (
        f'<meta name="twitter:image" content="{image_url_esc}" />' if image_url else ""
    )
    # Escape redirect URL for safe embedding in <script>: prevent </script> injection
    redirect_url_js = json.dumps(redirect_url).replace("</", "<\\/")

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
    {og_image_meta}

    <meta name="twitter:card" content="summary_large_image" />
    <meta name="twitter:title" content="{title_esc}" />
    <meta name="twitter:description" content="{desc_esc}" />
    {twitter_image_meta}

    <link rel="canonical" href="{viewer_url_esc}" />

    <meta http-equiv="refresh" content="0; url={redirect_url_esc}" />
    <script>
      window.location.replace({redirect_url_js});
    </script>
  </head>
  <body>
    <p>Redirecting to <a href="{redirect_url_esc}">{viewer_url_esc}</a>…</p>
  </body>
</html>
"""

    return HTMLResponse(content=html_doc)


async def _get_shareable_tour(db: AsyncSession, *criteria: ColumnElement[bool]) -> Tour:
    """Fetch a published, non-private, non-deleted tour (scenes preloaded) or 404."""
    query = (
        select(Tour)
        .where(and_(Tour.deleted_at.is_(None), *criteria))
        .options(selectinload(Tour.scenes))
    )
    result = await db.execute(query)
    tour = result.scalar_one_or_none()

    if (
        not tour
        or tour.status != TourStatus.published
        or tour.visibility == TourVisibility.private
    ):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tour not found")

    return tour


@router.get("/share/tours/{tour_id}", response_class=HTMLResponse)
async def tour_share_preview(
    tour_id: str,
    request: Request,
    redirect: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    """
    Render Open Graph/Twitter meta tags for a tour and redirect humans to the viewer.

    The optional `redirect` query param allows the caller (frontend) to control where
    humans land after crawlers read the metadata.
    """
    tour = await _get_shareable_tour(db, Tour.id == tour_id)
    return _render_tour_share(tour, request, redirect)


@router.get("/v/{code}", response_class=HTMLResponse)
async def tour_short_link(
    code: str,
    request: Request,
    redirect: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    """
    Short share link for a tour (assigned on publish).

    Resolves the short code and renders the same share preview as
    ``/share/tours/{tour_id}``.
    """
    tour = await _get_shareable_tour(db, Tour.short_code == code)
    return _render_tour_share(tour, request, redirect)
