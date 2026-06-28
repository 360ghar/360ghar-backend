"""Runtime verification that image URLs resolve to a real asset.

Closes the gap left by ``ValidationUtils.is_absolute_url()`` (which only
checks the URL scheme). A well-formed but non-existent Cloudinary URL like
``https://res.cloudinary.com/.../hc_properties/.../master_bedroom.webp``
passes the scheme check yet returns HTTP 404; this module rejects such URLs
by issuing a minimal ranged GET and inspecting the status.

Design notes
------------
* Uses the shared ``get_general_client()`` httpx pool per AGENTS.md; never
  creates an ephemeral ``httpx.AsyncClient``.
* Sends ``Range: bytes=0-0`` to download at most one byte. Cloudinary and
  most CDNs honour this; servers that ignore ``Range`` still return a 2xx
  status code we accept on.
* 2xx and 3xx responses are treated as OK; 4xx/5xx and network errors are
  treated as failures. The function never raises.
* Cloudinary hostnames are treated as first-party and hard-block on failure.
  Third-party hosts (legacy ``nobroker.in`` etc.) are soft: a verification
  failure logs a warning but still returns True, so transient third-party
  outages do not break property creation.
"""

from __future__ import annotations

import httpx

from app.core.http import get_general_client
from app.core.logging import get_logger

logger = get_logger(__name__)

# Hosts whose URLs are authoritative and must resolve. A failure here is
# treated as a hard block (the URL is dropped). Anything else is soft.
_FIRST_PARTY_HOSTS = frozenset(
    {
        "res.cloudinary.com",
    }
)

# Per-request timeout. Kept short: this runs on the property create/update
# path and must not dominate request latency. The shared general client
# already follows redirects.
_DEFAULT_TIMEOUT = 4.0


def _is_first_party(url: str) -> bool:
    try:
        host = url.split("://", 1)[1].split("/", 1)[0].lower()
    except IndexError:
        return False
    return any(host == h or host.endswith("." + h) for h in _FIRST_PARTY_HOSTS)


async def verify_image_url(url: str, *, timeout: float = _DEFAULT_TIMEOUT) -> bool:
    """Return True iff ``url`` resolves to a reachable image asset.

    A 1-byte ranged GET is issued. 2xx/3xx -> True, 4xx/5xx/network error ->
    False. Cloudinary (first-party) failures are hard: the caller MUST drop
    the URL. Third-party failures are soft: this function still returns True
    after logging, so transient outages do not block inserts.

    For first-party URLs a single retry is attempted on network error so a
    transient timeout does not produce a false-positive "broken" verdict
    (important for the nightly sweep, which can saturate the shared pool).

    Never raises.
    """
    if not url or not url.startswith(("http://", "https://")):
        return False

    first_party = _is_first_party(url)
    client = get_general_client()

    async def _attempt() -> httpx.Response | None:
        try:
            return await client.get(
                url,
                headers={"Range": "bytes=0-0"},
                timeout=timeout,
            )
        except httpx.HTTPError as exc:
            logger.debug("Image URL verification network error: %s", exc)
            return None

    resp = await _attempt()
    # Retry once for first-party on network error (transient pool saturation).
    if resp is None and first_party:
        resp = await _attempt()

    if resp is None:
        # Network error after retry.
        return False if first_party else True

    ok = resp.status_code < 400
    if not ok:
        logger.warning(
            "Image URL returned HTTP %s: %s [%s]",
            resp.status_code,
            url,
            "first-party -> DROP" if first_party else "third-party -> keep",
        )
        return False if first_party else True

    return True


async def verify_image_urls(
    urls: list[str],
    *,
    timeout: float = _DEFAULT_TIMEOUT,
) -> tuple[list[str], list[str]]:
    """Verify a batch of URLs concurrently.

    Returns ``(kept, dropped)`` where ``dropped`` only ever contains
    first-party URLs that failed verification. Third-party soft-failures
    are kept in ``kept``.
    """
    import asyncio

    if not urls:
        return [], []

    results = await asyncio.gather(
        *(verify_image_url(u, timeout=timeout) for u in urls),
        return_exceptions=False,
    )
    kept: list[str] = []
    dropped: list[str] = []
    for url, ok in zip(urls, results, strict=True):
        if ok:
            kept.append(url)
        else:
            dropped.append(url)
    return kept, dropped
