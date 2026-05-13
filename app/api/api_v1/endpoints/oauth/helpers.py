from __future__ import annotations

import ipaddress
import secrets
import socket
from html import escape
from typing import Any
from urllib.parse import urlparse

import anyio
import httpx
from pydantic import BaseModel, HttpUrl

from app.core.logging import get_logger
from app.services.oauth_token_store import oauth_token_store

logger = get_logger(__name__)

# OAuth configuration
OAUTH_AUTHORIZATION_CODE_LIFETIME = 600  # 10 minutes
OAUTH_ACCESS_TOKEN_LIFETIME = 3600  # 1 hour
OAUTH_REFRESH_TOKEN_LIFETIME = 86400 * 30  # 30 days

# ChatGPT redirect URIs per Apps SDK documentation
CHATGPT_REDIRECT_URIS = [
    "https://chatgpt.com/connector_platform_oauth_redirect",
    "https://platform.openai.com/apps-manage/oauth",
]

# ChatGPT dynamic redirect URI prefixes (new Apps SDK uses session-specific callback IDs)
CHATGPT_REDIRECT_PREFIXES = [
    "https://chatgpt.com/connector/oauth/",
]


# =============================================================================
# Pydantic Schemas for OAuth
# =============================================================================


class OAuthAuthorizeRequest(BaseModel):
    response_type: str
    client_id: str
    redirect_uri: HttpUrl | None = None
    scope: str | None = None
    state: str | None = None
    code_challenge: str | None = None  # PKCE
    code_challenge_method: str | None = None  # PKCE
    resource: str | None = None


class OAuthTokenRequest(BaseModel):
    grant_type: str
    code: str | None = None
    redirect_uri: HttpUrl | None = None
    client_id: str | None = None
    refresh_token: str | None = None
    code_verifier: str | None = None  # PKCE
    resource: str | None = None


# =============================================================================
# Helper Functions
# =============================================================================


def generate_auth_code() -> str:
    """Generate a secure authorization code."""
    return secrets.token_urlsafe(32)


def generate_access_token() -> str:
    """Generate a secure access token."""
    return secrets.token_urlsafe(32)


def generate_refresh_token() -> str:
    """Generate a secure refresh token."""
    return secrets.token_urlsafe(32)


def is_loopback_redirect_uri(uri: str) -> bool:
    """Return True for valid OAuth loopback redirect URIs."""
    try:
        parsed = urlparse(uri)
    except Exception:
        return False
    if parsed.scheme != "http":
        return False
    host = (parsed.hostname or "").lower()
    return host in {"localhost", "127.0.0.1", "::1"}


def is_redirect_uri_allowed_for_client(client: dict[str, Any], redirect_uri: str) -> bool:
    """Validate redirect_uri against client policy with ChatGPT compatibility."""
    if redirect_uri in CHATGPT_REDIRECT_URIS:
        return True

    # Support new ChatGPT Apps SDK dynamic callback URIs (session-specific IDs).
    for prefix in CHATGPT_REDIRECT_PREFIXES:
        if redirect_uri.startswith(prefix):
            return True

    registered_uris = client.get("redirect_uris") or []
    if redirect_uri in registered_uris:
        return True

    # First-party fallback for native loopback clients (Cursor/Claude/local inspectors).
    if client.get("is_first_party") and is_loopback_redirect_uri(redirect_uri):
        return True

    return False


def render_consent_html(
    *,
    session_id: str,
    oauth_session: dict[str, Any] | None = None,
    error_message: str | None = None,
) -> str:
    """Render OAuth consent/login page with optional error state."""
    client_name = escape((oauth_session or {}).get("client_name", "MCP client"))
    escape((oauth_session or {}).get("client_id", "unknown-client"))
    escape((oauth_session or {}).get("resource", ""))
    scopes = [
        escape(s) for s in ((oauth_session or {}).get("scope", "mcp:read mcp:write")).split() if s
    ]
    scope_items = "".join(f"<li>{scope}</li>" for scope in scopes) or "<li>mcp:read</li>"
    error_block = (
        f'<div class="notice error">{escape(error_message)}</div>'
        if error_message
        else '<div class="notice">Sign in to continue securely.</div>'
    )

    return f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
      <meta charset="utf-8" />
      <meta name="viewport" content="width=device-width, initial-scale=1" />
      <title>Sign in to 360Ghar</title>
      <style>
        :root {{
          --bg: #f8f9fa;
          --card: #ffffff;
          --ink: #1a1a1a;
          --muted: #475569;
          --accent: #ff6b00;
          --accent-hover: #e65c00;
          --accent-ink: #ffffff;
          --line: #dbe3f0;
          --error: #b42318;
          --error-bg: #fef3f2;
          --radius: 16px;
          --shadow: 0 18px 42px rgba(15, 23, 42, 0.12);
        }}
        * {{ box-sizing: border-box; }}
        body {{
          margin: 0;
          min-height: 100vh;
          display: grid;
          place-items: center;
          background: radial-gradient(circle at top right, #fff4ed 0%, var(--bg) 42%);
          color: var(--ink);
          font-family: "Avenir Next", "Segoe UI", sans-serif;
          padding: 24px;
        }}
        .panel {{
          width: min(720px, 100%);
          background: var(--card);
          border-radius: var(--radius);
          border: 1px solid var(--line);
          box-shadow: var(--shadow);
          display: grid;
          grid-template-columns: 1fr 1fr;
          overflow: hidden;
        }}
        .aside {{
          background: #ff6b00;
          color: var(--accent-ink);
          padding: 28px;
        }}
        .brand {{
          letter-spacing: 0.08em;
          font-size: 12px;
          text-transform: uppercase;
          opacity: 0.9;
          font-weight: 600;
        }}
        .aside h1 {{
          margin: 12px 0 10px;
          line-height: 1.1;
          font-size: 28px;
        }}
        .aside p {{
          margin: 0;
          line-height: 1.5;
          opacity: 0.9;
          font-size: 14px;
        }}
        .chips {{
          margin-top: 16px;
          display: flex;
          flex-wrap: wrap;
          gap: 8px;
        }}
        .chip {{
          border: 1px solid rgba(255, 255, 255, 0.4);
          border-radius: 999px;
          padding: 6px 10px;
          font-size: 12px;
        }}
        .main {{
          padding: 28px;
          display: grid;
          gap: 14px;
          align-content: start;
        }}
        h2 {{
          margin: 0;
          font-size: 22px;
        }}
        .notice {{
          border: 1px solid var(--line);
          background: #f8fafc;
          border-radius: 12px;
          padding: 10px 12px;
          color: var(--muted);
          font-size: 13px;
        }}
        .notice.error {{
          border-color: #fecdca;
          background: var(--error-bg);
          color: var(--error);
        }}
        ul {{
          margin: 0;
          padding-left: 18px;
          color: var(--muted);
          font-size: 13px;
        }}
        form {{
          display: grid;
          gap: 12px;
        }}
        label {{
          display: grid;
          gap: 6px;
          font-size: 13px;
          color: var(--muted);
        }}
        input {{
          width: 100%;
          border: 1px solid #cbd5e1;
          border-radius: 10px;
          padding: 10px 12px;
          font-size: 14px;
          outline: none;
          transition: border-color 140ms ease, box-shadow 140ms ease;
        }}
        input:focus {{
          border-color: #ff6b00;
          box-shadow: 0 0 0 3px rgba(255, 107, 0, 0.2);
        }}
        button {{
          margin-top: 4px;
          border: 0;
          border-radius: 12px;
          background: var(--accent);
          color: #ffffff;
          font-weight: 600;
          padding: 11px 14px;
          cursor: pointer;
          transition: background 140ms ease, transform 60ms ease;
        }}
        button:hover {{
          background: var(--accent-hover);
        }}
        button:active {{
          transform: translateY(1px);
        }}
        .hint {{
          margin: 0;
          color: var(--muted);
          font-size: 12px;
          line-height: 1.45;
        }}
        .phone-input-wrapper {{
          display: flex;
          align-items: center;
          border: 1px solid #cbd5e1;
          border-radius: 10px;
          overflow: hidden;
          transition: border-color 140ms ease, box-shadow 140ms ease;
        }}
        .phone-input-wrapper:focus-within {{
          border-color: #ff6b00;
          box-shadow: 0 0 0 3px rgba(255, 107, 0, 0.2);
        }}
        .country-code {{
          background: #f1f5f9;
          color: #475569;
          padding: 10px 12px;
          font-size: 14px;
          font-weight: 500;
          border-right: 1px solid #cbd5e1;
          user-select: none;
        }}
        .phone-input-wrapper input {{
          border: none;
          border-radius: 0;
          flex: 1;
          box-shadow: none;
        }}
        .phone-input-wrapper input:focus {{
          box-shadow: none;
        }}
        @media (max-width: 760px) {{
          .panel {{ grid-template-columns: 1fr; }}
        }}
      </style>
    </head>
    <body>
      <section class="panel">
        <aside class="aside">
          <div class="brand">360Ghar</div>
          <h1>Connect your account</h1>
          <p>Sign in to allow <strong>{client_name}</strong> to access your account.</p>
          <div class="chips">
            <span class="chip">You can revoke this access at any time from your account settings.</span>
          </div>
        </aside>
        <main class="main">
          <h2>Sign in</h2>
          {error_block}
          <div class="notice">
            This app is requesting access to:
            <ul>{scope_items}</ul>
          </div>
          <form method="post" autocomplete="on" id="oauth-form">
            <label for="phone">Phone number
              <div class="phone-input-wrapper">
                <span class="country-code">+91</span>
                <input type="tel" id="phone" name="phone" required placeholder="XXXXXXXXXX" maxlength="10" inputmode="numeric" />
              </div>
            </label>
            <label for="password">Password
              <input type="password" id="password" name="password" required />
            </label>
            <input type="hidden" name="session" value="{escape(session_id)}" />
            <button type="submit">Authorize and Continue</button>
          </form>
          <script>
            (function() {{
              const form = document.getElementById('oauth-form');
              const phoneInput = document.getElementById('phone');
              form.addEventListener('submit', function(e) {{
                const phoneValue = phoneInput.value.trim();
                if (phoneValue && !phoneValue.startsWith('+')) {{
                  phoneInput.value = '+91' + phoneValue;
                }}
              }});
            }})();
          </script>
          <p class="hint">By continuing, you authorize {client_name} to access the permissions listed above.</p>
        </main>
      </section>
    </body>
    </html>
    """


async def fetch_client_metadata(client_id: str) -> dict[str, Any] | None:
    """Fetch and validate Client ID Metadata Document for URL-based client_ids."""
    if not client_id.startswith("https://"):
        return None

    try:
        parsed = urlparse(client_id)
        if parsed.scheme != "https" or not parsed.hostname:
            return None

        if parsed.username or parsed.password:
            logger.warning("Rejected client_id with userinfo: %s", client_id)
            return None

        host = parsed.hostname
        if host.lower() in {"localhost"} or host.endswith(".local"):
            logger.warning("Rejected client_id pointing at localhost domain: %s", client_id)
            return None

        port = parsed.port or 443
        if port not in {443}:
            logger.warning("Rejected client_id with non-HTTPS port: %s", client_id)
            return None

        def _resolve_ips() -> list[str]:
            infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
            return [str(info[4][0]) for info in infos if info and info[4]]

        try:
            ips = await anyio.to_thread.run_sync(_resolve_ips)
        except Exception as exc:
            logger.warning("Failed to resolve client_id host %s: %s", host, exc)
            return None

        for ip_str in ips:
            try:
                ip = ipaddress.ip_address(ip_str)
            except ValueError:
                logger.warning("Invalid IP for client_id host %s: %s", host, ip_str)
                return None

            if (
                ip.is_private
                or ip.is_loopback
                or ip.is_link_local
                or ip.is_multicast
                or ip.is_reserved
                or ip.is_unspecified
            ):
                logger.warning(
                    "Rejected client_id resolving to non-public IP %s (%s)", ip_str, client_id
                )
                return None

        async with httpx.AsyncClient(timeout=10.0, follow_redirects=False) as client:
            resp = await client.get(client_id)
            if resp.status_code == 200:
                metadata = resp.json()
                if metadata.get("client_id") == client_id:
                    if "redirect_uris" in metadata and "client_name" in metadata:
                        logger.info("Fetched client metadata from %s", client_id)
                        return dict[str, Any](metadata)
                    logger.warning("Client metadata missing required fields: %s", client_id)
                else:
                    logger.warning("Client ID mismatch in metadata document: %s", client_id)
    except Exception as exc:
        logger.warning("Failed to fetch client metadata from %s: %s", client_id, exc)

    return None


async def validate_client(client_id: str) -> dict[str, Any] | None:
    """Validate a client_id using first-party, DCR, or metadata discovery."""
    if client_id == "ghar360-mcp":
        return {
            "client_id": "ghar360-mcp",
            "client_name": "360Ghar MCP Client",
            "is_first_party": True,
            "redirect_uris": [
                "http://localhost:3000/callback",
                *CHATGPT_REDIRECT_URIS,
            ],
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "token_endpoint_auth_method": "none",
        }

    client = await oauth_token_store.get_client(client_id)
    if client:
        return client

    if client_id.startswith("https://"):
        metadata = await fetch_client_metadata(client_id)
        if metadata:
            return metadata

    return None
