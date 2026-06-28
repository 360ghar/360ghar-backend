"""Backend-driven deep linking endpoints.

Three routers are exposed (registration happens in
``app.infrastructure.routing`` and ``app.api.api_v1.api``):

* :data:`wellknown_router` — root-level Android/iOS verification files
  (``/.well-known/assetlinks.json`` and
  ``/.well-known/apple-app-site-association``).
* :data:`redirect_router` — root-level smart fallback/redirect pages for every
  app's link paths (``/p/{id}``, ``/estate/{entity}/{id}``,
  ``/flatmates/{entity}/{id}``, ``/stays/{entity}/{id}`` …).
* :data:`api_router` — JSON link-generation API, mounted under ``/api/v1/deeplinks``.

All routers are public (no auth) — they replace the previously separate
static-hosted ``ghar_sale_links`` / ``the360ghar_links`` repos.
"""

from __future__ import annotations

import dataclasses
import json

from fastapi import APIRouter, HTTPException, Path, status
from fastapi.responses import HTMLResponse, Response

from app.core.logging import get_logger
from app.schemas.deeplinks import (
    AppInfo,
    EntityInfo,
    GeneratedLinkResponse,
    GenerateLinkRequest,
)
from app.services.deeplinks import (
    APP_REGISTRY,
    build_apple_app_site_association,
    build_assetlinks,
    generate_link,
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
# JSON link-generation API (mounted under /api/v1/deeplinks)
# ---------------------------------------------------------------------------

api_router = APIRouter()


@api_router.get("/apps", response_model=list[AppInfo])
async def list_apps() -> list[AppInfo]:
    """List every registered app and its shareable entities (discovery)."""
    return [
        AppInfo(
            key=app.key,
            name=app.name,
            path_prefix=app.path_prefix,
            custom_scheme=app.custom_scheme,
            android_packages=list(app.android_packages),
            ios_bundle_id=app.ios_bundle_id,
            entities=[
                EntityInfo(entity=e.entity, description=e.description, public=e.public)
                for e in app.entities
            ],
        )
        for app in APP_REGISTRY
    ]


@api_router.post("/generate", response_model=GeneratedLinkResponse)
async def generate(body: GenerateLinkRequest) -> GeneratedLinkResponse:
    """Generate the canonical share link for an entity."""
    try:
        link = generate_link(body.app, body.entity, body.identifier)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return GeneratedLinkResponse(**dataclasses.asdict(link))


@api_router.get("/{app_key}/{entity}/{identifier:path}", response_model=GeneratedLinkResponse)
async def generate_path(
    app_key: str = Path(..., max_length=32, description="App key: ghar/estate/flatmates/stays"),
    entity: str = Path(..., max_length=32, description="Entity type, e.g. 'property'"),
    identifier: str = Path(..., description="Entity identifier (may contain slashes)"),
) -> GeneratedLinkResponse:
    """Convenience GET form of link generation."""
    try:
        link = generate_link(app_key, entity, identifier)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return GeneratedLinkResponse(**dataclasses.asdict(link))


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
