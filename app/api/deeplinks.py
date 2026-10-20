"""Backend-driven deep linking endpoints.

Three routers are exposed (registration happens in
``app.infrastructure.routing`` and ``app.api.api_v1.api``):

* :data:`wellknown_router` — root-level Android/iOS verification files
  (``/.well-known/assetlinks.json`` and
  ``/.well-known/apple-app-site-association``).
* :data:`redirect_router` — root-level smart fallback/redirect pages for every
  app's link paths (``/p/{id}``, ``/estate/{entity}/{id}``,
  ``/flatmates/{entity}/{id}``, ``/stays/{entity}/{id}`` …).

Both routers are public (no auth). The JSON link-generation API was removed:
no client called it, and the redirect pages and share links use the registry.
"""

from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import HTMLResponse, Response

from app.core.logging import get_logger
from app.services.deeplinks import (
    APP_REGISTRY,
    build_apple_app_site_association,
    build_assetlinks,
    get_app_for_path,
    render_fallback_page,
)

logger = get_logger(__name__)

# Verification files change only when fingerprints / apps change. Allow CDN /
# browser caching but keep it modest so cert-fingerprint rotations propagate.
_WELLKNOWN_CACHE = "public, max-age=3600"
_AASA_MEDIA_TYPE = "application/json"


# ---------------------------------------------------------------------------
# /.well-known verification files (served at the domain root)
# ---------------------------------------------------------------------------

wellknown_router = APIRouter()


@wellknown_router.get("/.well-known/assetlinks.json", include_in_schema=False)
async def android_assetlinks() -> Response:
    """Android App Links Digital Asset Links statement list (all apps)."""
    payload = json.dumps(build_assetlinks(), separators=(",", ":"))
    return Response(
        content=payload,
        media_type=_AASA_MEDIA_TYPE,
        headers={"Cache-Control": _WELLKNOWN_CACHE},
    )


@wellknown_router.get("/.well-known/apple-app-site-association", include_in_schema=False)
async def apple_app_site_association() -> Response:
    """iOS Universal Links association file (all apps).

    Served with ``Content-Type: application/json`` and **no** file extension,
    as required by Apple.
    """
    payload = json.dumps(build_apple_app_site_association(), separators=(",", ":"))
    return Response(
        content=payload,
        media_type=_AASA_MEDIA_TYPE,
        headers={"Cache-Control": _WELLKNOWN_CACHE},
    )


# ---------------------------------------------------------------------------
# Smart fallback / redirect pages (served at the domain root)
# ---------------------------------------------------------------------------
#
# Rather than a greedy catch-all (which would shadow the whole site and other
# routes when the backend shares a host with the marketing site), we register
# ONLY the explicit paths each app actually claims, derived from the registry:
#   * flagship root app:  /p/{id}, /property/{id}, /tour/{id}
#   * namespaced apps:    /estate/{entity}/{id}, /flatmates/{entity}/{id}, …
# Unknown entities under a known prefix return 404.

redirect_router = APIRouter()


async def _render_for_path(path: str) -> HTMLResponse:
    resolved = get_app_for_path(path)
    if resolved is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    app, entity, identifier = resolved
    return HTMLResponse(content=render_fallback_page(app, entity, identifier))


def _register_redirect_routes(router: APIRouter) -> None:
    """Register explicit fallback-page routes for every registered app path."""
    seen: set[str] = set()
    for app in APP_REGISTRY:
        for entity_pattern in app.entities:
            if app.path_prefix:
                route = f"/{app.path_prefix}/{entity_pattern.entity}/{{identifier:path}}"
            else:
                route = f"/{entity_pattern.entity}/{{identifier:path}}"
            if route in seen:
                continue
            seen.add(route)

            # Capture `route` in a closure (default-parameter binding is unsafe
            # here — FastAPI would expose `_route` as an overridable query
            # parameter on the registered route, letting callers tamper with
            # the route's identifier prefix).
            prefix = route.rsplit("/{identifier:path}", 1)[0]

            async def _handler(identifier: str, _prefix: str = prefix) -> HTMLResponse:
                # Reconstruct the public path and resolve via the registry so
                # validation stays in one place.
                return await _render_for_path(f"{_prefix}/{identifier}")

            router.add_api_route(
                route,
                _handler,
                methods=["GET"],
                include_in_schema=False,
                response_class=HTMLResponse,
            )


_register_redirect_routes(redirect_router)
