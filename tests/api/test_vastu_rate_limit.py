"""The Vastu analyze endpoint allows 5 calls per minute per IP (limiter not overridden)."""

from unittest.mock import patch

import pytest
from httpx import AsyncClient

from app.core.cache.backends.memory import InMemoryCacheBackend
from app.core.cache.manager import CacheManager


@pytest.mark.asyncio
async def test_analyze_is_rate_limited_per_ip(client: AsyncClient):
    cache = CacheManager(backend=InMemoryCacheBackend(max_size=100, default_ttl=60))
    await cache.connect()
    # A text file fails type validation, so no AI call runs. The limiter runs first.
    files = {"image": ("plan.txt", b"not an image", "text/plain")}

    with patch("app.middleware.rate_limit.get_cache_manager", return_value=cache):
        codes = [(await client.post("/api/v1/vastu/analyze", files=files)).status_code for _ in range(6)]

    assert 429 not in codes[:5]
    assert codes[5] == 429
