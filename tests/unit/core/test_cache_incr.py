"""CacheManager.incr counts atomically in a fixed window."""

import asyncio

import pytest

from app.core.cache.backends.disk import DiskCacheBackend
from app.core.cache.backends.memory import InMemoryCacheBackend
from app.core.cache.manager import CacheManager


@pytest.mark.asyncio
async def test_memory_incr_is_atomic_under_concurrency():
    cache = CacheManager(backend=InMemoryCacheBackend(max_size=10, default_ttl=60))
    await cache.connect()
    counts = await asyncio.gather(*(cache.incr("k", ttl=60) for _ in range(50)))
    assert sorted(counts) == list(range(1, 51))


@pytest.mark.asyncio
async def test_memory_incr_window_expires_and_is_not_extended():
    backend = InMemoryCacheBackend(max_size=10, default_ttl=60)
    cache = CacheManager(backend=backend)
    await cache.connect()
    assert await cache.incr("k", ttl=1) == 1
    assert await cache.incr("k", ttl=1) == 2
    await asyncio.sleep(1.1)
    assert await cache.incr("k", ttl=1) == 1


@pytest.mark.asyncio
async def test_backend_without_incr_falls_back_to_get_set(tmp_path):
    cache = CacheManager(backend=DiskCacheBackend(directory=str(tmp_path)))
    await cache.connect()
    counts = await asyncio.gather(*(cache.incr("k", ttl=60) for _ in range(10)))
    assert sorted(counts) == list(range(1, 11))
    await cache.disconnect()
