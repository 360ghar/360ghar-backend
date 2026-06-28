"""Local JWT verification via Supabase JWKS.

Verifies the Supabase access-token signature, ``iss``, ``aud``, and ``exp``
claims locally using the cached JWKS public key set, avoiding a per-request
HTTP round-trip to ``/auth/v1/user``.  Falls back gracefully when the JWKS
endpoint is unreachable (the caller can then try introspection).

JWKS are cached with a TTL (default 1 h) and refreshed on a ``kid`` miss.
A short-TTL positive cache (token-hash → claims) avoids re-verifying
identical tokens within the cache window.
"""

from __future__ import annotations

import hashlib
import time
from typing import Any

import jwt
from jwt import InvalidTokenError
from jwt.algorithms import ECAlgorithm, RSAAlgorithm

from app.config import settings
from app.core.http import get_supabase_auth_http_client
from app.core.logging import get_logger

logger = get_logger(__name__)

JWKS_TTL_SECONDS = 3600  # 1 hour
_TOKEN_CACHE_TTL_SECONDS = 60  # short-lived positive cache
_TOKEN_CACHE_MAX_SIZE = 5000


def _jwks_url() -> str:
    return f"{settings.SUPABASE_URL.rstrip('/')}/auth/v1/.well-known/jwks.json"


class _JWKSCache:
    """In-memory JWKS cache with TTL + on-demand refresh.

    Caches both successful key fetches and "empty" responses (e.g. Supabase
    projects without JWKS enabled) so we don't re-fetch every request.
    """

    def __init__(self) -> None:
        self._keys: dict[str, Any] = {}  # kid → public key
        self._fetched_at: float = 0.0
        self._empty_fetched_at: float = 0.0  # timestamp of last empty-keyset response

    def _is_fresh(self) -> bool:
        if (time.time() - self._fetched_at) < JWKS_TTL_SECONDS and bool(self._keys):
            return True
        # Treat a recent empty-keyset response as "fresh" to avoid re-fetching
        # every request when the JWKS endpoint returns no keys.
        if (time.time() - self._empty_fetched_at) < JWKS_TTL_SECONDS:
            return True
        return False

    async def refresh(self) -> None:
        """Fetch the JWKS from Supabase and populate the cache."""
        url = _jwks_url()
        headers = {"apikey": settings.SUPABASE_CLIENT_KEY}
        try:
            client = get_supabase_auth_http_client()
            resp = await client.get(url, headers=headers, timeout=10.0)
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:  # noqa: BLE001
            logger.warning("JWKS fetch failed: %s", exc)
            return

        keys = data.get("keys") or []
        new_map: dict[str, Any] = {}
        for key in keys:
            kid = key.get("kid")
            if not kid:
                continue
            try:
                kty = key.get("kty", "")
                if kty == "EC":
                    new_map[kid] = ECAlgorithm.from_jwk(key)
                elif kty == "RSA":
                    new_map[kid] = RSAAlgorithm.from_jwk(key)
                else:
                    logger.debug("Skipping JWKS key %s with unsupported kty=%s", kid, kty)
            except Exception as exc:  # noqa: BLE001
                logger.debug("Skipping unparseable JWKS key %s: %s", kid, exc)
        if new_map:
            self._keys = new_map
            self._fetched_at = time.time()
            self._empty_fetched_at = 0.0
            logger.info("JWKS cache refreshed (%d keys)", len(new_map))
        else:
            # Empty keyset — record the fetch time so we don't re-fetch every request.
            self._empty_fetched_at = time.time()
            logger.debug("JWKS endpoint returned no keys; will retry in %ds", JWKS_TTL_SECONDS)

    def get_key(self, kid: str | None) -> Any | None:
        return self._keys.get(kid) if kid else None

    def has_keys(self) -> bool:
        return bool(self._keys)


_jwks_cache = _JWKSCache()


class _TokenCache:
    """Short-TTL positive cache: token-hash → decoded claims."""

    def __init__(self) -> None:
        self._store: dict[str, tuple[float, dict[str, Any]]] = {}

    @staticmethod
    def _hash(token: str) -> str:
        return hashlib.sha256(token.encode()).hexdigest()

    def get(self, token: str) -> dict[str, Any] | None:
        h = self._hash(token)
        entry = self._store.get(h)
        if entry is None:
            return None
        expires_at, claims = entry
        if time.time() > expires_at:
            self._store.pop(h, None)
            return None
        return claims

    def set(self, token: str, claims: dict[str, Any]) -> None:
        if len(self._store) > _TOKEN_CACHE_MAX_SIZE:
            # Evict ~10% of the oldest entries to bound memory.
            now = time.time()
            for k, (exp, _) in list(self._store.items()):
                if now > exp:
                    self._store.pop(k, None)
            if len(self._store) > _TOKEN_CACHE_MAX_SIZE:
                for k in sorted(self._store, key=lambda k: self._store[k][0])[
                    : max(1, _TOKEN_CACHE_MAX_SIZE // 10)
                ]:
                    self._store.pop(k, None)
        self._store[self._hash(token)] = (time.time() + _TOKEN_CACHE_TTL_SECONDS, claims)


_token_cache = _TokenCache()


def _expected_audiences() -> list[str]:
    """Audience values to accept.  Supabase JWTs use the publishable key or
    ``authenticated`` as the audience depending on the key format."""
    cands: list[str] = []
    key = settings.SUPABASE_CLIENT_KEY
    if key:
        cands.append(key)
    cands.append("authenticated")
    return cands


async def verify_jwt_locally(token: str) -> dict[str, Any] | None:
    """Verify a Supabase JWT locally using JWKS.

    Returns the decoded claims on success, ``None`` on a definitive
    invalid/expired token.  Raises :class:`JWKSUnavailable` when the JWKS
    cannot be fetched so the caller can fall back to introspection.
    """
    # Fast path: positive cache.
    cached = _token_cache.get(token)
    if cached is not None:
        return cached

    # Ensure JWKS keys are available.
    if not _jwks_cache._is_fresh():
        await _jwks_cache.refresh()
    if not _jwks_cache.has_keys():
        raise JWKSUnavailable("JWKS keys are not available")

    # Peek the unverified header for the kid.
    try:
        unverified_header = jwt.get_unverified_header(token)
    except InvalidTokenError as exc:
        logger.info("Malformed JWT header: %s", exc)
        return None

    kid = unverified_header.get("kid")
    public_key = _jwks_cache.get_key(kid)
    if public_key is None:
        # kid miss — refresh JWKS once and retry.
        await _jwks_cache.refresh()
        public_key = _jwks_cache.get_key(kid)
        if public_key is None:
            raise JWKSUnavailable(f"Unknown kid: {kid}")

    try:
        claims = jwt.decode(
            token,
            public_key,
            algorithms=["RS256", "ES256"],
            audience=_expected_audiences(),
            issuer=f"{settings.SUPABASE_URL.rstrip('/')}/auth/v1",
            options={"require": ["exp", "iat", "iss", "sub"]},
        )
    except jwt.ExpiredSignatureError:
        logger.info("JWT expired")
        return None
    except InvalidTokenError as exc:
        logger.info("JWT invalid: %s", exc)
        return None

    _token_cache.set(token, claims)
    return claims


class JWKSUnavailable(Exception):
    """Raised when the JWKS cannot be fetched for local verification."""
