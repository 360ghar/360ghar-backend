"""Backend-driven deep linking for all 360Ghar apps.

This package centralises everything the previously separate static-hosted
repositories (``ghar_sale_links`` and ``the360ghar_links``) used to do:

* serving the Android App Links verification file (``/.well-known/assetlinks.json``)
* serving the iOS Universal Links verification file
  (``/.well-known/apple-app-site-association``)
* serving smart fallback/redirect pages that open the native app when
  installed and fall back to the app store / website otherwise

The :mod:`app.services.deeplinks.registry` module is the single source of
truth. Add a new app or a new shareable entity there and every other layer
(verification files and redirect pages) updates automatically.
"""

from __future__ import annotations

from app.services.deeplinks.registry import (
    APP_REGISTRY,
    AppLinkConfig,
    EntityPattern,
    Platform,
    get_app,
    get_app_for_path,
)
from app.services.deeplinks.service import (
    build_apple_app_site_association,
    build_assetlinks,
    render_fallback_page,
)

__all__ = [
    "APP_REGISTRY",
    "AppLinkConfig",
    "EntityPattern",
    "Platform",
    "get_app",
    "get_app_for_path",
    "build_apple_app_site_association",
    "build_assetlinks",
    "render_fallback_page",
]
