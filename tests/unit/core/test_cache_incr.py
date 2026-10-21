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


class _GetSetOnly:
    """A backend with no incr, to reach the manager's get-then-set fallback."""

    def __init__(self):
        self.store: dict = {}

    async def connect(self):
        return None

    def is_available(self):
        return True

    async def get(self, key):
        return self.store.get(key)

    async def set(self, key, value, ttl=None):
        self.store[key] = value
        return True


@pytest.mark.asyncio
async def test_backend_without_incr_falls_back_to_get_set():
    cache = CacheManager(backend=_GetSetOnly())
    counts = await asyncio.gather(*(cache.incr("k", ttl=60) for _ in range(10)))
    assert sorted(counts) == list(range(1, 11))


@pytest.mark.asyncio
async def test_disk_incr_keeps_a_fixed_window(tmp_path):
    cache = CacheManager(backend=DiskCacheBackend(directory=str(tmp_path)))
    await cache.connect()
    assert await cache.incr("k", ttl=1) == 1
    await asyncio.sleep(0.6)
    assert await cache.incr("k", ttl=1) == 2
    await asyncio.sleep(0.6)  # 1.2 s after the first hit: the window has ended
    assert await cache.incr("k", ttl=1) == 1
    await cache.disconnect()


@pytest.mark.asyncio
async def test_memory_counter_survives_lru_eviction():
    cache = CacheManager(backend=InMemoryCacheBackend(max_size=2, default_ttl=60))
    await cache.connect()
    assert await cache.incr("limit", ttl=60) == 1
    for i in range(10):
        await cache.set(f"other{i}", i)
    assert await cache.incr("limit", ttl=60) == 2
