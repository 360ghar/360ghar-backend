"""
Tests for app.core.cache module.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.cache.backends.disk import DiskCacheBackend
from app.core.cache.manager import (
    CacheBackendType,
    CacheManager,
    NullCacheBackend,
)


@pytest.fixture(autouse=True)
def _restore_global_cache_manager():
    """Restore the global cache manager singleton after each test.

    Several tests in this module mutate ``app.core.cache._cache_manager``
    directly (or via ``set_cache_manager``). Without restoring it, the leaked
    ``MagicMock`` becomes the global manager for the rest of the suite, breaking
    unrelated tests that await its async methods.
    """
    import app.core.cache as cache_module

    original = cache_module._cache_manager
    try:
        yield
    finally:
        cache_module._cache_manager = original


class TestNullCacheBackend:
    """Tests for NullCacheBackend."""

    @pytest.mark.asyncio
    async def test_get_returns_none(self):
        """Test get always returns None."""
        cache = NullCacheBackend()
        result = await cache.get("any_key")
        assert result is None

    @pytest.mark.asyncio
    async def test_set_returns_true(self):
        """Test set always returns True."""
        cache = NullCacheBackend()
        result = await cache.set("key", "value", ttl=300)
        assert result is True

    @pytest.mark.asyncio
    async def test_delete_returns_true(self):
        """Test delete always returns True."""
        cache = NullCacheBackend()
        result = await cache.delete("key")
        assert result is True

    @pytest.mark.asyncio
    async def test_delete_pattern_returns_zero(self):
        """Test delete_pattern always returns 0."""
        cache = NullCacheBackend()
        result = await cache.delete_pattern("key:*")
        assert result == 0

    @pytest.mark.asyncio
    async def test_exists_returns_false(self):
        """Test exists always returns False."""
        cache = NullCacheBackend()
        result = await cache.exists("key")
        assert result is False

    @pytest.mark.asyncio
    async def test_clear_returns_true(self):
        """Test clear always returns True."""
        cache = NullCacheBackend()
        result = await cache.clear()
        assert result is True

    @pytest.mark.asyncio
    async def test_connect_is_noop(self):
        """Test connect is no-op."""
        cache = NullCacheBackend()
        await cache.connect()  # Should not raise

    @pytest.mark.asyncio
    async def test_disconnect_is_noop(self):
        """Test disconnect is no-op."""
        cache = NullCacheBackend()
        await cache.disconnect()  # Should not raise

    def test_is_available_returns_false(self):
        """Test is_available returns False."""
        cache = NullCacheBackend()
        assert cache.is_available() is False


class TestCacheBackendType:
    """Tests for CacheBackendType enum."""

    def test_memory_backend_type(self):
        """Test memory backend type value."""
        assert CacheBackendType.MEMORY.value == "memory"

    def test_redis_backend_type(self):
        """Test redis backend type value."""
        assert CacheBackendType.REDIS.value == "redis"

    def test_disk_backend_type(self):
        """Test disk backend type value."""
        assert CacheBackendType.DISK.value == "disk"


class TestCacheManager:
    """Tests for CacheManager class."""

    def test_create_from_config_memory(self):
        """Test CacheManager creation with memory backend."""
        settings = MagicMock()
        settings.SERVERLESS_ENABLED = False
        settings.CACHE_BACKEND = "memory"
        settings.CACHE_DEFAULT_TTL = 300
        settings.CACHE_MEMORY_MAX_SIZE = 1000
        settings.CACHE_MEMORY_MAX_ENTRY_BYTES = 1_000_000

        manager = CacheManager.create_from_config(settings)

        assert manager is not None
        assert manager._primary is not None

    def test_create_from_config_disk(self):
        """Test CacheManager creation with disk backend."""
        settings = MagicMock()
        settings.SERVERLESS_ENABLED = False
        settings.CACHE_BACKEND = "disk"
        settings.CACHE_DEFAULT_TTL = 300
        settings.CACHE_DISK_DIR = "/tmp/test-cache"
        settings.CACHE_DISK_MAX_SIZE = 1000
        settings.CACHE_DISK_MAX_ENTRY_BYTES = 1_000_000
        settings.CACHE_MEMORY_MAX_SIZE = 250
        settings.CACHE_MEMORY_MAX_ENTRY_BYTES = 1_000_000

        manager = CacheManager.create_from_config(settings)

        assert manager is not None
        assert manager._primary is not None
        assert manager._fallback is not None

    def test_create_from_config_redis(self):
        """Test CacheManager creation with redis backend."""
        settings = MagicMock()
        settings.SERVERLESS_ENABLED = False
        settings.CACHE_BACKEND = "redis"
        settings.REDIS_URL = "redis://localhost:6379"
        settings.CACHE_DEFAULT_TTL = 300
        settings.CACHE_REDIS_MAX_CONNECTIONS = 15
        settings.CACHE_KEY_PREFIX = "test:"
        settings.CACHE_MEMORY_MAX_SIZE = 500
        settings.CACHE_MEMORY_MAX_ENTRY_BYTES = 1_000_000

        manager = CacheManager.create_from_config(settings)

        assert manager is not None
        assert manager._primary is not None
        assert manager._fallback is not None

    @pytest.mark.asyncio
    async def test_get_delegates_to_backend(self):
        """Test get delegates to active backend."""
        mock_backend = MagicMock()
        mock_backend.is_available.return_value = True
        mock_backend.get = AsyncMock(return_value="cached_value")

        manager = CacheManager(backend=mock_backend)

        result = await manager.get("test_key")

        mock_backend.get.assert_called_once_with("test_key")
        assert result == "cached_value"

    @pytest.mark.asyncio
    async def test_set_delegates_to_backend(self):
        """Test set delegates to active backend."""
        mock_backend = MagicMock()
        mock_backend.is_available.return_value = True
        mock_backend.set = AsyncMock(return_value=True)

        manager = CacheManager(backend=mock_backend)

        result = await manager.set("key", "value", ttl=300)

        mock_backend.set.assert_called_once_with("key", "value", 300)
        assert result is True

    @pytest.mark.asyncio
    async def test_delete_delegates_to_backend(self):
        """Test delete delegates to active backend."""
        mock_backend = MagicMock()
        mock_backend.is_available.return_value = True
        mock_backend.delete = AsyncMock(return_value=True)

        manager = CacheManager(backend=mock_backend)

        result = await manager.delete("key")

        mock_backend.delete.assert_called_once_with("key")
        assert result is True

    @pytest.mark.asyncio
    async def test_delete_pattern_delegates_to_backend(self):
        """Test delete_pattern delegates to active backend."""
        mock_backend = MagicMock()
        mock_backend.is_available.return_value = True
        mock_backend.delete_pattern = AsyncMock(return_value=5)

        manager = CacheManager(backend=mock_backend)

        result = await manager.delete_pattern("prefix:*")

        mock_backend.delete_pattern.assert_called_once_with("prefix:*")
        assert result == 5

    @pytest.mark.asyncio
    async def test_exists_delegates_to_backend(self):
        """Test exists delegates to active backend."""
        mock_backend = MagicMock()
        mock_backend.is_available.return_value = True
        mock_backend.exists = AsyncMock(return_value=True)

        manager = CacheManager(backend=mock_backend)

        result = await manager.exists("key")

        mock_backend.exists.assert_called_once_with("key")
        assert result is True

    @pytest.mark.asyncio
    async def test_clear_delegates_to_backend(self):
        """Test clear delegates to active backend."""
        mock_backend = MagicMock()
        mock_backend.is_available.return_value = True
        mock_backend.clear = AsyncMock(return_value=True)

        manager = CacheManager(backend=mock_backend)

        result = await manager.clear()

        mock_backend.clear.assert_called_once()
        assert result is True

    def test_is_available_checks_backend(self):
        """Test is_available checks backend availability."""
        mock_backend = MagicMock()
        mock_backend.is_available.return_value = True

        manager = CacheManager(backend=mock_backend)

        assert manager.is_available() is True
        mock_backend.is_available.assert_called()

    @pytest.mark.asyncio
    async def test_uses_fallback_when_primary_unavailable(self):
        """Test manager uses fallback when primary is not available."""
        # Create a mock that has both sync and async methods configured properly
        mock_primary = MagicMock()
        mock_primary.is_available.return_value = False  # Sync method
        mock_primary.get = AsyncMock(return_value=None)  # Async method

        mock_fallback = MagicMock()
        mock_fallback.is_available.return_value = True  # Sync method
        mock_fallback.get = AsyncMock(return_value="fallback_value")  # Async method

        manager = CacheManager(backend=mock_primary, fallback=mock_fallback)

        result = await manager.get("key")

        mock_fallback.get.assert_called_once_with("key")
        assert result == "fallback_value"

    @pytest.mark.asyncio
    async def test_connect_sets_fallback_on_primary_failure(self):
        """Test connect uses fallback on primary connection failure."""
        mock_primary = AsyncMock()
        mock_primary.connect.side_effect = Exception("Connection failed")
        mock_primary.is_available = MagicMock(return_value=False)

        mock_fallback = AsyncMock()
        mock_fallback.connect.return_value = None

        manager = CacheManager(backend=mock_primary, fallback=mock_fallback)

        await manager.connect()

        assert manager._use_fallback is True

    @pytest.mark.asyncio
    async def test_disconnect_closes_all_backends(self):
        """Test disconnect closes primary and fallback."""
        mock_primary = AsyncMock()
        mock_fallback = AsyncMock()

        manager = CacheManager(backend=mock_primary, fallback=mock_fallback)

        await manager.disconnect()

        mock_primary.disconnect.assert_called_once()
        mock_fallback.disconnect.assert_called_once()

    def test_get_stats(self):
        """Test get_stats returns stats dictionary."""
        mock_backend = MagicMock()
        mock_backend.is_available.return_value = True
        mock_backend.stats = MagicMock()
        mock_backend.stats.to_dict.return_value = {"hits": 100, "misses": 10}

        manager = CacheManager(backend=mock_backend)
        manager._use_fallback = False

        stats = manager.get_stats()

        assert stats["available"] is True
        assert stats["using_fallback"] is False
        assert "primary" in stats

    @pytest.mark.asyncio
    async def test_invalidate_user_cache(self):
        """Test invalidate_user_cache clears user-related keys."""
        mock_backend = MagicMock()
        mock_backend.is_available.return_value = True
        mock_backend.delete_pattern = AsyncMock(return_value=3)

        manager = CacheManager(backend=mock_backend)

        result = await manager.invalidate_user_cache(user_id=123)

        assert result == 9  # 3 patterns * 3 deleted each
        assert mock_backend.delete_pattern.call_count == 3


class TestCacheModuleFunctions:
    """Tests for cache module-level functions."""

    @pytest.fixture(autouse=True)
    def _reset_global_cache_manager(self):
        """Reset the module-level singleton before and after each test.

        Several tests below swap in a MagicMock as the global ``_cache_manager``.
        Without this teardown the mock leaks into the rest of the process and
        breaks unrelated async API tests that hit the real cache (the mock's
        coroutine-returning methods are not awaitable).
        """
        import app.core.cache as cache_module

        original = cache_module._cache_manager
        cache_module._cache_manager = None
        yield
        cache_module._cache_manager = original

    def test_get_cache_manager_creates_singleton(self):
        """Test get_cache_manager returns singleton."""
        with patch("app.core.cache.CacheManager.create_from_config") as mock_create:
            mock_manager = MagicMock()
            mock_create.return_value = mock_manager

            import app.core.cache as cache_module
            cache_module._cache_manager = None

            manager1 = cache_module.get_cache_manager()
            manager2 = cache_module.get_cache_manager()

            assert mock_create.call_count == 1
            assert manager1 is manager2

    def test_set_cache_manager(self):
        """Test set_cache_manager overrides global manager."""
        import app.core.cache as cache_module

        mock_manager = MagicMock()
        cache_module.set_cache_manager(mock_manager)

        assert cache_module._cache_manager is mock_manager

    @pytest.mark.asyncio
    async def test_initialize_cache(self):
        """Test initialize_cache connects manager."""
        mock_manager = AsyncMock()

        with patch("app.core.cache.get_cache_manager", return_value=mock_manager):
            from app.core.cache import initialize_cache

            await initialize_cache()

            mock_manager.connect.assert_called_once()

    @pytest.mark.asyncio
    async def test_shutdown_cache(self):
        """Test shutdown_cache disconnects manager."""
        mock_manager = AsyncMock()

        with patch("app.core.cache.get_cache_manager", return_value=mock_manager):
            from app.core.cache import shutdown_cache

            await shutdown_cache()

            mock_manager.disconnect.assert_called_once()


class TestPropertyCacheManager:
    """Tests for PropertyCacheManager class."""

    def test_generate_cache_key(self):
        """Test cache key generation is consistent."""
        from app.core.cache import PropertyCacheManager

        filters = {"city": "Mumbai", "purpose": "rent"}
        key1 = PropertyCacheManager.generate_cache_key(filters, 1, 1, 10)
        key2 = PropertyCacheManager.generate_cache_key(filters, 1, 1, 10)

        assert key1 == key2
        assert key1.startswith("properties:v1:")

    def test_generate_cache_key_different_filters(self):
        """Test different filters produce different keys."""
        from app.core.cache import PropertyCacheManager

        key1 = PropertyCacheManager.generate_cache_key({"city": "Mumbai"}, 1, 1, 10)
        key2 = PropertyCacheManager.generate_cache_key({"city": "Delhi"}, 1, 1, 10)

        assert key1 != key2

    def test_generate_cache_key_different_users(self):
        """Test different users produce different keys."""
        from app.core.cache import PropertyCacheManager

        key1 = PropertyCacheManager.generate_cache_key({}, 1, 1, 10)
        key2 = PropertyCacheManager.generate_cache_key({}, 2, 1, 10)

        assert key1 != key2

    @pytest.mark.asyncio
    async def test_invalidate_property_caches(self):
        """Test invalidate_property_caches deletes pattern."""
        with patch("app.core.cache.get_cache_manager") as mock_get:
            mock_manager = AsyncMock()
            mock_manager.delete_pattern.return_value = 10
            mock_get.return_value = mock_manager

            from app.core.cache import PropertyCacheManager

            result = await PropertyCacheManager.invalidate_property_caches(123)

            mock_manager.delete_pattern.assert_called_once_with("properties:*")
            assert result == 10

    @pytest.mark.asyncio
    async def test_get_cached_properties(self):
        """Test get_cached_properties retrieves from cache."""
        with patch("app.core.cache.get_cache_manager") as mock_get:
            mock_manager = AsyncMock()
            mock_manager.get.return_value = {"items": []}
            mock_get.return_value = mock_manager

            from app.core.cache import PropertyCacheManager

            result = await PropertyCacheManager.get_cached_properties({}, 1, 1, 10)

            assert result == {"items": []}

    @pytest.mark.asyncio
    async def test_cache_properties(self):
        """Test cache_properties stores in cache."""
        with patch("app.core.cache.get_cache_manager") as mock_get:
            mock_manager = AsyncMock()
            mock_manager.set.return_value = True
            mock_get.return_value = mock_manager

            from app.core.cache import PropertyCacheManager

            result = await PropertyCacheManager.cache_properties(
                {}, 1, 1, 10, {"items": []}, ttl=300
            )

            assert result is True
            mock_manager.set.assert_called_once()


class TestDiskCacheBackend:
    """Tests for the disk-backed cache implementation."""

    @pytest.mark.asyncio
    async def test_round_trip_and_delete_pattern(self, tmp_path):
        cache = DiskCacheBackend(tmp_path, max_size=10, default_ttl=300)
        await cache.connect()
        try:
            assert await cache.set("properties:one", {"id": 1})
            assert await cache.set("properties:two", {"id": 2})

            assert await cache.get("properties:one") == {"id": 1}
            assert await cache.delete_pattern("properties:*") == 2
            assert await cache.exists("properties:one") is False
            assert cache.stats.deletes == 2
        finally:
            await cache.disconnect()

    @pytest.mark.asyncio
    async def test_rejects_oversized_entries(self, tmp_path):
        cache = DiskCacheBackend(tmp_path, max_entry_bytes=8)
        await cache.connect()
        try:
            assert await cache.set("large", "x" * 100) is False
            assert await cache.get("large") is None
        finally:
            await cache.disconnect()
