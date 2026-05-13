"""
Modular caching system with swappable backends.

Usage:
    from app.core.cache import get_cache_manager, cached

    # Access global cache manager
    cache = get_cache_manager()
    await cache.set("key", "value", ttl=300)

    # Use decorators
    @cached("amenities", ttl=86400)
    async def get_amenities():
        ...
"""

import hashlib
import json
from typing import Any

from app.core.cache.decorators import cached, invalidate_cache
from app.core.cache.interface import CacheBackend, CacheStats
from app.core.cache.keys import CacheKeyPatterns, build_cache_key, generate_hash
from app.core.cache.manager import CacheBackendType, CacheManager, NullCacheBackend

# Global cache manager instance
_cache_manager: CacheManager | None = None


def get_cache_manager() -> CacheManager:
    """Get the global cache manager instance.

    Creates a new instance from settings if one doesn't exist.
    Call initialize_cache() during app startup to connect.
    """
    global _cache_manager
    if _cache_manager is None:
        from app.config import settings

        _cache_manager = CacheManager.create_from_config(settings)
    return _cache_manager


def __getattr__(name: str) -> Any:
    if name == "cache_manager":
        return get_cache_manager()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def set_cache_manager(manager: CacheManager | None) -> None:
    """Set the global cache manager (for testing).

    Args:
        manager: CacheManager instance to use globally, or None to reset.
    """
    global _cache_manager
    _cache_manager = manager


def reset_cache_manager() -> None:
    """Reset the global cache manager. For use in test teardown."""
    global _cache_manager
    if _cache_manager is not None:
        _cache_manager = None


async def initialize_cache() -> None:
    """Initialize cache connections. Call during app startup."""
    await get_cache_manager().connect()


async def shutdown_cache() -> None:
    """Close cache connections. Call during app shutdown."""
    manager = get_cache_manager()
    await manager.disconnect()


class PropertyCacheManager:
    """Specialized cache manager for property queries.

    Provides helper methods for caching property search results
    with consistent key generation and invalidation.
    """

    @staticmethod
    def generate_cache_key(
        filters: dict, user_id: int, page: int, limit: int
    ) -> str:
        """Generate consistent cache key for property queries."""
        filter_str = json.dumps(
            filters,
            sort_keys=True,
            default=lambda o: getattr(o, "value", str(o)),
        )
        filter_hash = hashlib.md5(filter_str.encode()).hexdigest()[:16]
        return f"properties:v1:{filter_hash}:u{user_id}:p{page}:l{limit}"

    @staticmethod
    async def invalidate_property_caches(property_id: int) -> int:
        """Invalidate all caches related to properties."""
        cache = get_cache_manager()
        return await cache.delete_pattern("properties:*")

    @staticmethod
    async def get_cached_properties(
        filters: dict, user_id: int, page: int, limit: int
    ) -> dict | None:
        """Get cached property results."""
        cache = get_cache_manager()
        cache_key = PropertyCacheManager.generate_cache_key(
            filters, user_id, page, limit
        )
        return await cache.get(cache_key)

    @staticmethod
    async def cache_properties(
        filters: dict,
        user_id: int,
        page: int,
        limit: int,
        result: dict,
        ttl: int = 300,
    ) -> bool:
        """Cache property results."""
        cache = get_cache_manager()
        cache_key = PropertyCacheManager.generate_cache_key(
            filters, user_id, page, limit
        )
        return await cache.set(cache_key, result, ttl)


__all__ = [
    # Manager
    "CacheManager",
    "CacheBackendType",
    "NullCacheBackend",
    "cache_manager",
    "get_cache_manager",
    "set_cache_manager",
    "reset_cache_manager",
    "initialize_cache",
    "shutdown_cache",
    # Property-specific
    "PropertyCacheManager",
    # Interface
    "CacheBackend",
    "CacheStats",
    # Decorators
    "cached",
    "invalidate_cache",
    # Keys
    "build_cache_key",
    "generate_hash",
    "CacheKeyPatterns",
]
