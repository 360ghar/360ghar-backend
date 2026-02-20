"""
Thread-safe in-memory cache with LRU eviction and TTL support.
Uses asyncio.Lock for async safety and OrderedDict for LRU ordering.
"""

import asyncio
import fnmatch
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Optional, Any

from app.core.cache.interface import CacheStats
from app.core.logging import get_logger

logger = get_logger(__name__)


@dataclass
class CacheEntry:
    """Single cache entry with value and expiration tracking."""

    value: Any
    expires_at: Optional[float]  # Unix timestamp, None = no expiry
    created_at: float

    def is_expired(self) -> bool:
        """Check if entry has expired."""
        if self.expires_at is None:
            return False
        return time.time() > self.expires_at


class InMemoryCacheBackend:
    """Thread-safe in-memory LRU cache implementation.

    Features:
    - LRU eviction when max_size is reached
    - Per-key TTL support
    - Pattern-based invalidation using fnmatch
    - Thread-safe via asyncio.Lock
    - Automatic cleanup of expired entries

    Note: This implementation is process-local and not suitable for
    multi-process deployments. Use Redis for distributed caching.
    """

    def __init__(
        self,
        max_size: int = 1000,
        default_ttl: int = 300,
        cleanup_interval: int = 86400,  # once daily
    ):
        """Initialize in-memory cache.

        Args:
            max_size: Maximum number of entries before LRU eviction
            default_ttl: Default TTL in seconds for entries without explicit TTL
            cleanup_interval: Interval in seconds for background cleanup of expired entries (default: daily)
        """
        self._cache: OrderedDict[str, CacheEntry] = OrderedDict()
        self._lock = asyncio.Lock()
        self._max_size = max_size
        self._default_ttl = default_ttl
        self._cleanup_interval = cleanup_interval
        self._cleanup_task: Optional[asyncio.Task] = None
        self._available = False
        self.stats = CacheStats()

    async def connect(self) -> None:
        """Start the background cleanup task."""
        self._available = True
        self._cleanup_task = asyncio.create_task(self._periodic_cleanup())
        logger.info(
            "In-memory cache initialized",
            extra={"max_size": self._max_size, "default_ttl": self._default_ttl},
        )

    async def disconnect(self) -> None:
        """Stop cleanup task and clear cache."""
        self._available = False
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
        async with self._lock:
            self._cache.clear()
        logger.info("In-memory cache disconnected")

    def is_available(self) -> bool:
        """Check if cache is available."""
        return self._available

    async def get(self, key: str) -> Optional[Any]:
        """Get value, updating LRU order on access."""
        async with self._lock:
            entry = self._cache.get(key)
            if entry is None:
                self.stats.misses += 1
                return None

            if entry.is_expired():
                del self._cache[key]
                self.stats.misses += 1
                return None

            # Move to end for LRU (most recently used)
            self._cache.move_to_end(key)
            self.stats.hits += 1
            return entry.value

    async def set(self, key: str, value: Any, ttl: Optional[int] = None) -> bool:
        """Set value with optional TTL, evicting LRU if needed."""
        try:
            ttl = ttl if ttl is not None else self._default_ttl
            expires_at = time.time() + ttl if ttl > 0 else None

            async with self._lock:
                # If key exists, remove it first (will be re-added at end)
                if key in self._cache:
                    del self._cache[key]

                # Evict LRU entries if at capacity
                while len(self._cache) >= self._max_size:
                    # popitem(last=False) removes oldest (least recently used)
                    evicted_key, _ = self._cache.popitem(last=False)
                    logger.debug(f"LRU eviction: {evicted_key}")

                self._cache[key] = CacheEntry(
                    value=value,
                    expires_at=expires_at,
                    created_at=time.time(),
                )

            self.stats.sets += 1
            return True
        except Exception as e:
            logger.error(f"In-memory cache set error: {e}")
            self.stats.errors += 1
            return False

    async def delete(self, key: str) -> bool:
        """Delete single key."""
        async with self._lock:
            if key in self._cache:
                del self._cache[key]
                self.stats.deletes += 1
                return True
            return False

    async def delete_pattern(self, pattern: str) -> int:
        """Delete keys matching fnmatch pattern (e.g., 'properties:*')."""
        deleted = 0
        async with self._lock:
            # Collect keys to delete (can't modify dict during iteration)
            keys_to_delete = [
                k for k in self._cache.keys() if fnmatch.fnmatch(k, pattern)
            ]
            for key in keys_to_delete:
                del self._cache[key]
                deleted += 1

        self.stats.deletes += deleted
        if deleted > 0:
            logger.debug(f"Pattern delete '{pattern}': {deleted} keys removed")
        return deleted

    async def exists(self, key: str) -> bool:
        """Check if non-expired key exists."""
        async with self._lock:
            entry = self._cache.get(key)
            if entry is None:
                return False
            if entry.is_expired():
                del self._cache[key]
                return False
            return True

    async def clear(self) -> bool:
        """Clear all entries."""
        async with self._lock:
            count = len(self._cache)
            self._cache.clear()
        logger.info(f"In-memory cache cleared: {count} entries")
        return True

    async def _periodic_cleanup(self) -> None:
        """Background task to remove expired entries."""
        while self._available:
            try:
                await asyncio.sleep(self._cleanup_interval)
                await self._cleanup_expired()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Cleanup task error: {e}")

    async def _cleanup_expired(self) -> None:
        """Remove all expired entries."""
        async with self._lock:
            expired_keys = [k for k, v in self._cache.items() if v.is_expired()]
            for key in expired_keys:
                del self._cache[key]

        if expired_keys:
            logger.debug(f"Cleaned up {len(expired_keys)} expired entries")

    def get_size(self) -> int:
        """Current number of entries (approximate, not locked)."""
        return len(self._cache)

    def get_stats(self) -> dict:
        """Get cache statistics including size info."""
        stats = self.stats.to_dict()
        stats["size"] = self.get_size()
        stats["max_size"] = self._max_size
        return stats
