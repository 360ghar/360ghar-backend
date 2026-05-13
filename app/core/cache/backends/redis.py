"""
Redis cache backend for distributed caching.
Refactored from existing CacheManager implementation.
"""

import json
import pickle
from typing import Any

import redis.asyncio as redis

from app.core.cache.interface import CacheStats
from app.core.logging import get_logger

logger = get_logger(__name__)


class RedisCacheBackend:
    """Redis-based cache backend for distributed caching.

    Features:
    - JSON serialization with pickle fallback for complex types
    - Pattern-based invalidation using SCAN (non-blocking)
    - Connection pooling
    - Graceful degradation on connection issues
    """

    def __init__(
        self,
        redis_url: str,
        default_ttl: int = 300,
        max_connections: int = 50,
        key_prefix: str = "cache:",
    ):
        """Initialize Redis cache backend.

        Args:
            redis_url: Redis connection URL (e.g., redis://localhost:6379)
            default_ttl: Default TTL in seconds
            max_connections: Maximum connections in pool
            key_prefix: Prefix for all cache keys
        """
        self._redis_url = redis_url
        self._default_ttl = default_ttl
        self._max_connections = max_connections
        self._key_prefix = key_prefix
        self._client: redis.Redis | None = None
        self.stats = CacheStats()

    async def connect(self) -> None:
        """Initialize Redis connection pool."""
        try:
            self._client = redis.from_url(
                self._redis_url,
                encoding="utf-8",
                decode_responses=False,  # Handle bytes for pickle
                max_connections=self._max_connections,
            )
            await self._client.ping()  # type: ignore[misc]
            logger.info("Redis cache connected successfully")
        except Exception as e:
            logger.error("Failed to connect to Redis: %s", e)
            self._client = None

    async def disconnect(self) -> None:
        """Close Redis connection pool."""
        if self._client:
            await self._client.close()
            self._client = None
            logger.info("Redis cache disconnected")

    def is_available(self) -> bool:
        """Check if Redis is connected."""
        return self._client is not None

    def _make_key(self, key: str) -> str:
        """Add prefix to key for namespace isolation."""
        return f"{self._key_prefix}{key}"

    def _serialize(self, value: Any) -> bytes:
        """Serialize value, preferring JSON for simple types."""
        try:
            return json.dumps(value).encode("utf-8")
        except (TypeError, ValueError):
            return pickle.dumps(value)

    def _deserialize(self, data: bytes) -> Any:
        """Deserialize value, trying JSON first."""
        try:
            return json.loads(data.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return pickle.loads(data)

    async def get(self, key: str) -> Any | None:
        """Retrieve value from Redis."""
        if not self._client:
            return None

        try:
            data = await self._client.get(self._make_key(key))
            if data is None:
                self.stats.misses += 1
                return None

            self.stats.hits += 1
            return self._deserialize(data)
        except Exception as e:
            logger.error("Redis get error for %s: %s", key, e)
            self.stats.errors += 1
            return None

    async def set(self, key: str, value: Any, ttl: int | None = None) -> bool:
        """Store value in Redis with TTL."""
        if not self._client:
            return False

        try:
            ttl = ttl if ttl is not None else self._default_ttl
            serialized = self._serialize(value)
            await self._client.setex(self._make_key(key), ttl, serialized)
            self.stats.sets += 1
            return True
        except Exception as e:
            logger.error("Redis set error for %s: %s", key, e)
            self.stats.errors += 1
            return False

    async def get_and_delete(self, key: str) -> Any | None:
        """Atomically retrieve value and delete key from Redis.

        Uses GETDEL (Redis 6.2+) when available, otherwise falls back to
        a Lua script for atomicity.
        """
        if not self._client:
            return None

        try:
            full_key = self._make_key(key)
            # Try GETDEL first (Redis 6.2+)
            try:
                data = await self._client.getdel(full_key)
            except (AttributeError, Exception):
                # Fallback: Lua script for atomic get-and-delete
                lua_script = """
                local value = redis.call('GET', KEYS[1])
                if value then
                    redis.call('DEL', KEYS[1])
                end
                return value
                """
                data = await self._client.eval(lua_script, 1, full_key)  # type: ignore[misc]

            if data is None:
                self.stats.misses += 1
                return None

            self.stats.hits += 1
            self.stats.deletes += 1
            return self._deserialize(data)
        except Exception as e:
            logger.error("Redis get_and_delete error for %s: %s", key, e)
            self.stats.errors += 1
            return None

    async def delete(self, key: str) -> bool:
        """Delete single key from Redis."""
        if not self._client:
            return False

        try:
            result = await self._client.delete(self._make_key(key))
            if result:
                self.stats.deletes += 1
            return bool(result)
        except Exception as e:
            logger.error("Redis delete error for %s: %s", key, e)
            self.stats.errors += 1
            return False

    async def delete_pattern(self, pattern: str) -> int:
        """Delete keys matching pattern using SCAN (non-blocking)."""
        if not self._client:
            return 0

        deleted = 0
        full_pattern = self._make_key(pattern)

        try:
            async for key in self._client.scan_iter(match=full_pattern):
                try:
                    await self._client.delete(key)
                    deleted += 1
                except Exception as inner_e:
                    logger.error("Failed deleting key %s: %s", key, inner_e)

            self.stats.deletes += deleted
            return deleted
        except Exception as e:
            logger.error("Redis delete_pattern error for %s: %s", pattern, e)
            self.stats.errors += 1
            return deleted

    async def exists(self, key: str) -> bool:
        """Check if key exists in Redis."""
        if not self._client:
            return False

        try:
            return bool(await self._client.exists(self._make_key(key)))
        except Exception as e:
            logger.error("Redis exists error for %s: %s", key, e)
            return False

    async def clear(self) -> bool:
        """Clear all keys with the cache prefix."""
        if not self._client:
            return False

        try:
            deleted = await self.delete_pattern("*")
            logger.info("Redis cache cleared: %s keys", deleted)
            return True
        except Exception as e:
            logger.error("Redis clear error: %s", e)
            return False

    def get_stats(self) -> dict:
        """Get cache statistics."""
        stats = self.stats.to_dict()
        stats["backend"] = "redis"
        stats["available"] = self.is_available()
        return stats
