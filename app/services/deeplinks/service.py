"""Deep link service: verification files, link generation, fallback pages.

All functions are pure / stateless and driven entirely by
:data:`app.services.deeplinks.registry.APP_REGISTRY` plus a few values pulled
from :class:`app.core.config.Settings`. There is no database dependency, so the
deep link surface is fully cacheable and cheap to serve.
"""

from __future__ import annotations

import html
import json
import logging
from dataclasses import dataclass

from app.config import settings
from app.services.deeplinks.registry import (
    APP_REGISTRY,
    AppLinkConfig,
    get_app,
)

logger = logging.getLogger(__name__)

# Placeholder value for the Apple Team ID; a real 10-char Team ID must override
# it in production or iOS Universal Links will never verify.
_PLACEHOLDER_TEAM_ID = "TEAMID"
_team_id_warned = False

# Maximum accepted length for a deep-link identifier. Mirrored by the request
# schema (app/schemas/deeplinks.py) so the POST body and GET path agree.
MAX_IDENTIFIER_LENGTH = 256


def _read_fingerprint_setting(setting_name: str) -> list[str]:
    """Parse a comma-separated SHA-256 fingerprint Settings value into a list."""
    raw = getattr(settings, setting_name, "") or ""
    return [fp.strip() for fp in raw.split(",") if fp.strip()]


def _fingerprints_for_package(app: AppLinkConfig, package: str) -> list[str]:
    """SHA-256 fingerprints for a specific Android package of ``app``.

    Honours per-package overrides (e.g. a legacy package signed with a different
    key) before falling back to the app-level fingerprint setting. Returns an
    empty list when no setting is configured, so an unconfigured package is
    emitted with an empty fingerprint array rather than the wrong key.
    """
    setting_name = app.fingerprint_setting_for(package)
    if not setting_name:
        return []
    return _read_fingerprint_setting(setting_name)


def _domain() -> str:
    return settings.DEEPLINK_DOMAIN.strip().rstrip("/")


def _team_id() -> str:
    team_id = settings.DEEPLINK_APPLE_TEAM_ID.strip()
    # A valid Apple Team ID is exactly 10 alphanumeric characters. Flag the
    # placeholder and any other malformed value so misconfigurations surface in
    # logs instead of silently emitting unusable AASA appIDs.
    if team_id == _PLACEHOLDER_TEAM_ID or len(team_id) != 10 or not team_id.isalnum():
        global _team_id_warned
        if not _team_id_warned:
            logger.warning(
                "DEEPLINK_APPLE_TEAM_ID=%r is invalid; expected a real 10-char "
                "Apple Team ID. The apple-app-site-association file will emit "
                "invalid appID values and iOS Universal Links will not verify.",
                team_id,
            )
            _team_id_warned = True
    return team_id


# ---------------------------------------------------------------------------
# Android — assetlinks.json
# ---------------------------------------------------------------------------

def build_assetlinks() -> list[dict]:
    """Build the combined Android App Links ``assetlinks.json`` payload.

    One Digital Asset Links statement per Android package across all apps.
    Packages without configured fingerprints are still emitted (with an empty
    fingerprint list) so the structure is visible, but Android will only verify
    packages that have at least one real fingerprint.
    """
    statements: list[dict] = []
    for app in APP_REGISTRY:
        for package in app.android_packages:
            fingerprints = _fingerprints_for_package(app, package)
            statements.append(
                {
                    "relation": ["delegate_permission/common.handle_all_urls"],
                    "target": {
                        "namespace": "android_app",
                        "package_name": package,
                        "sha256_cert_fingerprints": fingerprints,
                    },
                }
            )
    return statements


# ---------------------------------------------------------------------------
# iOS — apple-app-site-association
# ---------------------------------------------------------------------------

def build_apple_app_site_association() -> dict:
    """Build the combined iOS Universal Links AASA payload.

    ``appID`` is ``<TeamID>.<bundleId>``. Paths come from each app's
    :meth:`AppLinkConfig.aasa_paths`. Apps flagged ``use_webcredentials`` are
    additionally listed in the ``webcredentials`` block (for password autofill /
    Sign in with Apple association).
    """
    team_id = _team_id()
    details: list[dict] = []
    webcredential_apps: list[str] = []

    for app in APP_REGISTRY:
        app_id = f"{team_id}.{app.ios_bundle_id}"
        details.append({"appID": app_id, "paths": app.aasa_paths()})
        if app.use_webcredentials:
            webcredential_apps.append(app_id)

    return {
        "applinks": {"apps": [], "details": details},
        "webcredentials": {"apps": webcredential_apps},
    }


# ---------------------------------------------------------------------------
# Link generation
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class GeneratedLink:
    app: str
    entity: str
    identifier: str
    # Canonical HTTPS App Link / Universal Link (share this).
    url: str
    # Custom-scheme URL (direct app launch fallback).
    scheme_url: str
    # Web fallback shown when the app is not installed.
    web_fallback_url: str


def generate_link(app_key: str, entity: str, identifier: str) -> GeneratedLink:
    """Generate the canonical share link for ``app_key``/``entity``/``identifier``.

    Raises :class:`ValueError` if the app or entity is unknown so callers can
    surface a 4xx rather than emitting a broken link.
    """
    app = get_app(app_key)
    if app is None:
        raise ValueError(f"Unknown app: {app_key!r}")
    if not any(e.entity == entity for e in app.entities):
        valid = ", ".join(e.entity for e in app.entities)
        raise ValueError(
            f"Unknown entity {entity!r} for app {app_key!r}. Valid entities: {valid}"
        )

    identifier = str(identifier).strip().strip("/")
    if not identifier:
        raise ValueError("identifier must not be empty")
    # Enforce the same length cap as the request schema so every entry point
    # (POST body and GET path) rejects oversized identifiers consistently.
    if len(identifier) > MAX_IDENTIFIER_LENGTH:
        raise ValueError(
            f"identifier exceeds maximum length of {MAX_IDENTIFIER_LENGTH} characters"
        )

    domain = _domain()
    return GeneratedLink(
        app=app.key,
        entity=entity,
        identifier=identifier,
        url=f"https://{domain}{app.https_path(entity, identifier)}",
        scheme_url=app.scheme_url(entity, identifier),
        web_fallback_url=app.web_fallback_url or f"https://{domain}",
    )


# ---------------------------------------------------------------------------
# Smart fallback / redirect HTML page
# ---------------------------------------------------------------------------

def render_fallback_page(
    app: AppLinkConfig,
    entity: str,
    identifier: str,
) -> str:
    """Render the smart fallback HTML page for an incoming link.

    On a real device, the OS intercepts a verified App/Universal Link *before*
    this page loads and opens the app directly. This page is the fallback for
    when the app is not installed (or verification failed): it attempts a
    custom-scheme launch, then surfaces store / website buttons.
    """
    domain = _domain()
    scheme_url = app.scheme_url(entity, identifier) if identifier else ""
    web_url = app.web_fallback_url or f"https://{domain}"
    # Deep web link mirrors the canonical path when we have an id.
    if identifier:
        web_url = f"https://{domain}{app.https_path(entity, identifier)}"

    store_url = app.play_store_url or app.app_store_url or web_url
    ios_store_url = app.app_store_url or store_url

    # Escape every interpolated value for HTML context.
    name_esc = html.escape(app.name)
    emoji_esc = html.escape(app.emoji)
    web_url_esc = html.escape(web_url)
    play_url_esc = html.escape(app.play_store_url or store_url)
    # JS-safe encoding for inline <script>. json.dumps() alone does NOT escape
    # the "</script>" sequence, so we additionally neutralise "</" (matching the
    # approach in app/api/share.py) to prevent a </script> breakout / XSS via a
    # crafted identifier path segment.
    def _js(value: str) -> str:
        return json.dumps(value).replace("</", "<\\/")

    scheme_js = _js(scheme_url)
    play_js = _js(app.play_store_url or store_url)
    ios_js = _js(ios_store_url)
    web_js = _js(web_url)
    from_esc = html.escape(app.gradient_from)
    to_esc = html.escape(app.gradient_to)

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>{name_esc} — Opening…</title>
  <meta property="og:title" content="{name_esc}" />
  <meta property="og:type" content="website" />
  <meta property="og:url" content="{web_url_esc}" />
  <style>
    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
    body {{
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
      background: linear-gradient(135deg, {from_esc} 0%, {to_esc} 100%);
      min-height: 100vh; display: flex; align-items: center;
      justify-content: center; padding: 20px;
    }}
    .container {{
      background: #fff; border-radius: 20px; padding: 40px; text-align: center;
      max-width: 400px; box-shadow: 0 20px 60px rgba(0,0,0,0.3);
    }}
    .logo {{ font-size: 48px; margin-bottom: 20px; }}
    h1 {{ color: #333; margin-bottom: 10px; font-size: 24px; }}
    p {{ color: #666; margin-bottom: 30px; line-height: 1.6; }}
    .btn {{
      display: inline-block; padding: 15px 40px; border-radius: 30px;
      text-decoration: none; font-weight: 600; margin: 10px;
      transition: transform 0.2s;
    }}
    .btn:hover {{ transform: scale(1.05); }}
    .btn-primary {{
      background: linear-gradient(135deg, {from_esc} 0%, {to_esc} 100%); color: #fff;
    }}
    .btn-secondary {{ background: #f0f0f0; color: #333; }}
    .spinner {{
      width: 40px; height: 40px; border: 4px solid #f0f0f0;
      border-top: 4px solid {from_esc}; border-radius: 50%;
      animation: spin 1s linear infinite; margin: 0 auto 20px;
    }}
    @keyframes spin {{ to {{ transform: rotate(360deg); }} }}
  </style>
</head>
<body>
  <div class="container">
    <div class="spinner"></div>
    <div class="logo">{emoji_esc}</div>
    <h1>Opening {name_esc}…</h1>
    <p>If the app doesn't open automatically, install it below.</p>
    <a id="storeLink" href="{play_url_esc}" class="btn btn-primary">Get the App</a>
    <br />
    <a id="webLink" href="{web_url_esc}" class="btn btn-secondary">View on Website</a>
  </div>
  <script>
    (function () {{
      var scheme = {scheme_js};
      var play = {play_js};
      var ios = {ios_js};
      var web = {web_js};
      var ua = navigator.userAgent || navigator.vendor || "";
      var isIOS = /iPad|iPhone|iPod/.test(ua);
      var isAndroid = /android/i.test(ua);

      document.getElementById("webLink").href = web;
      document.getElementById("storeLink").href = isIOS ? ios : play;

      // Attempt to launch the installed app via its custom scheme. If the
      // verified App/Universal Link already opened the app, this page never ran.
      if (scheme) {{
        var t = setTimeout(function () {{
          document.querySelector(".spinner").style.display = "none";
        }}, 2000);
        if (isAndroid || isIOS) {{
          window.location.href = scheme;
        }} else {{
          clearTimeout(t);
          document.querySelector(".spinner").style.display = "none";
        }}
      }} else {{
        document.querySelector(".spinner").style.display = "none";
      }}
    }})();
  </script>
</body>
</html>"""
