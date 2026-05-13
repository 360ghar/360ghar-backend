"""
CacheManager facade that provides a unified interface and handles
backend selection based on configuration.
"""

from enum import Enum
from typing import Any

from app.core.cache.backends.memory import InMemoryCacheBackend
from app.core.cache.backends.redis import RedisCacheBackend
from app.core.cache.interface import CacheBackend
from app.core.logging import get_logger

logger = get_logger(__name__)


class CacheBackendType(str, Enum):
    """Supported cache backend types."""

    MEMORY = "memory"
    REDIS = "redis"


class NullCacheBackend:
    """Null Object pattern - no-op cache for graceful degradation.

    Used when no cache backend is available or caching is disabled.
    All operations return safe defaults without errors.
    """

    async def get(self, key: str) -> None:
        """Always returns None."""
        return None

    async def set(self, key: str, value: Any, ttl: int | None = None) -> bool:
        """Always returns True (pretend success), but logs a warning."""
        logger.warning("NullCacheBackend: discarding write for key '%s' — cache is disabled", key)
        return True

    async def get_and_delete(self, key: str) -> None:
        """Always returns None (no-op)."""
        return None

    async def delete(self, key: str) -> bool:
        """Always returns True."""
        return True

    async def delete_pattern(self, pattern: str) -> int:
        """Always returns 0."""
        return 0

    async def exists(self, key: str) -> bool:
        """Always returns False."""
        return False

    async def clear(self) -> bool:
        """Always returns True."""
        return True

    async def connect(self) -> None:
        """No-op."""
        pass

    async def disconnect(self) -> None:
        """No-op."""
        pass

    def is_available(self) -> bool:
        """Always returns False to indicate cache is disabled."""
        return False


class CacheManager:
    """Unified cache manager that abstracts backend selection.

    Usage:
        cache = CacheManager.create_from_config(settings)
        await cache.connect()

        # Use directly
        await cache.set("key", "value", ttl=300)
        value = await cache.get("key")

        # Pattern invalidation
        await cache.delete_pattern("properties:*")
    """

    def __init__(
        self,
        backend: CacheBackend,
        fallback: CacheBackend | None = None,
    ):
        """Initialize with primary backend and optional fallback.

        Args:
            backend: Primary cache backend
            fallback: Optional fallback (e.g., in-memory when Redis fails)
        """
        self._primary = backend
        self._fallback = fallback or NullCacheBackend()
        self._use_fallback = False

    @classmethod
    def create_from_config(cls, settings: Any) -> "CacheManager":
        """Factory method to create CacheManager from app settings.

        When SERVERLESS_ENABLED is true, forces the in-memory backend to
        avoid persistent Redis connections that generate outbound packets
        and prevent Railway serverless scale-to-zero.

        Args:
            settings: Application settings with cache configuration

        Returns:
            Configured CacheManager instance
        """
        if getattr(settings, "SERVERLESS_ENABLED", False):
            logger.info("Serverless mode — using in-memory cache (no Redis keep-alive)")
            primary: CacheBackend = InMemoryCacheBackend(
                max_size=getattr(settings, "CACHE_MEMORY_MAX_SIZE", 1000),
                default_ttl=getattr(settings, "CACHE_DEFAULT_TTL", 300),
            )
            return cls(backend=primary)

        backend_type = CacheBackendType(
            getattr(settings, "CACHE_BACKEND", "memory")
        )

        if backend_type == CacheBackendType.REDIS:
            primary = RedisCacheBackend(
                redis_url=settings.REDIS_URL,
                default_ttl=getattr(settings, "CACHE_DEFAULT_TTL", 300),
                key_prefix=getattr(settings, "CACHE_KEY_PREFIX", "ghar360:"),
            )
            # In-memory fallback when Redis is unavailable
            fallback = InMemoryCacheBackend(
                max_size=getattr(settings, "CACHE_MEMORY_MAX_SIZE", 500),
                default_ttl=getattr(settings, "CACHE_DEFAULT_TTL", 300),
            )
        else:
            primary = InMemoryCacheBackend(
                max_size=getattr(settings, "CACHE_MEMORY_MAX_SIZE", 1000),
                default_ttl=getattr(settings, "CACHE_DEFAULT_TTL", 300),
            )
            fallback = None

        return cls(backend=primary, fallback=fallback)

    @property
    def backend(self) -> CacheBackend:
        """Get active backend (primary or fallback)."""
        if self._use_fallback or not self._primary.is_available():
            return self._fallback
        return self._primary

    async def connect(self) -> None:
        """Initialize cache connections."""
        try:
            await self._primary.connect()
            if not self._primary.is_available():
                logger.warning("Primary cache not available, using fallback")
                self._use_fallback = True
        except Exception as e:
            logger.warning("Primary cache connection failed: %s", e)
            self._use_fallback = True

        if self._fallback and not isinstance(self._fallback, NullCacheBackend):
            try:
                await self._fallback.connect()
            except Exception as e:
                logger.warning("Fallback cache connection failed: %s", e)

    async def disconnect(self) -> None:
        """Close all cache connections."""
        try:
            await self._primary.disconnect()
        except Exception as e:
            logger.warning("Primary cache disconnect error: %s", e)

        if self._fallback and not isinstance(self._fallback, NullCacheBackend):
            try:
                await self._fallback.disconnect()
            except Exception as e:
                logger.warning("Fallback cache disconnect error: %s", e)

    # Delegate all operations to active backend
    async def get(self, key: str) -> Any | None:
        """Get value from cache."""
        return await self.backend.get(key)

    async def get_and_delete(self, key: str) -> Any | None:
        """Atomically get value and delete key from cache.

        Prevents TOCTOU races where a value is read and then deleted
        in separate non-atomic steps (e.g., auth code exchange).
        """
        return await self.backend.get_and_delete(key)

    async def set(self, key: str, value: Any, ttl: int | None = None) -> bool:
        """Set value in cache."""
        return await self.backend.set(key, value, ttl)

    async def delete(self, key: str) -> bool:
        """Delete key from cache."""
        return await self.backend.delete(key)

    async def delete_pattern(self, pattern: str) -> int:
        """Delete all keys matching pattern."""
        return await self.backend.delete_pattern(pattern)

    async def exists(self, key: str) -> bool:
        """Check if key exists in cache."""
        return await self.backend.exists(key)

    async def clear(self) -> bool:
        """Clear all keys from cache."""
        return await self.backend.clear()

    def is_available(self) -> bool:
        """Check if cache is available."""
        return self.backend.is_available()

    def get_stats(self) -> dict[str, Any]:
        """Get cache statistics."""
        stats: dict[str, Any] = {"backend": "null", "available": False}

        if hasattr(self._primary, "stats"):
            stats["primary"] = self._primary.stats.to_dict()
            stats["backend"] = self._primary.__class__.__name__

        if hasattr(self._fallback, "stats") and not isinstance(
            self._fallback, NullCacheBackend
        ):
            stats["fallback"] = self._fallback.stats.to_dict()

        stats["available"] = self.is_available()
        stats["using_fallback"] = self._use_fallback

        return stats

    async def invalidate_user_cache(self, user_id: int) -> int:
        """Invalidate all cache entries for a user.

        Args:
            user_id: User ID to invalidate

        Returns:
            Total number of keys deleted
        """
        patterns = [
            f"user:{user_id}:*",
            f"auth:token:*:{user_id}",
            f"properties:user:{user_id}:*",
        ]
        total_deleted = 0
        for pattern in patterns:
            total_deleted += await self.delete_pattern(pattern)
        return total_deleted
