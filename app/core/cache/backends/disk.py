"""Disk-backed cache with an in-memory metadata index."""

from __future__ import annotations

import asyncio
import fnmatch
import hashlib
import pickle
import tempfile
import time
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.core.cache.counters import FixedWindowCounters
from app.core.cache.interface import CacheStats
from app.core.logging import get_logger

logger = get_logger(__name__)


@dataclass
class DiskCacheEntry:
    """Metadata for a disk cache entry."""

    path: Path
    expires_at: float | None
    created_at: float
    size_bytes: int

    def is_expired(self) -> bool:
        if self.expires_at is None:
            return False
        return time.time() > self.expires_at


class DiskCacheBackend:
    """LRU cache that stores values on disk and keeps only metadata in memory."""

    def __init__(
        self,
        directory: str | Path,
        max_size: int = 1000,
        default_ttl: int = 300,
        max_entry_bytes: int = 1_000_000,
        cleanup_interval: int = 300,
    ) -> None:
        self._directory = Path(directory)
        self._max_size = max_size
        self._default_ttl = default_ttl
        self._max_entry_bytes = max_entry_bytes
        self._cleanup_interval = cleanup_interval
        self._entries: OrderedDict[str, DiskCacheEntry] = OrderedDict()
        self._counters = FixedWindowCounters()
        self._lock = asyncio.Lock()
        self._cleanup_task: asyncio.Task[None] | None = None
        self._available = False
        self.stats = CacheStats()

    async def connect(self) -> None:
        """Create the cache directory and start expiry cleanup."""
        self._directory.mkdir(parents=True, exist_ok=True)
        self._available = True
        self._cleanup_task = asyncio.create_task(self._periodic_cleanup())
        logger.info(
            "Disk cache initialized",
            extra={
                "directory": str(self._directory),
                "max_size": self._max_size,
                "max_entry_bytes": self._max_entry_bytes,
            },
        )

    async def disconnect(self) -> None:
        """Stop cleanup. Cached files are kept for process-local reuse while running."""
        self._available = False
        self._counters.clear()
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
            self._cleanup_task = None
        logger.info("Disk cache disconnected")

    def is_available(self) -> bool:
        return self._available

    async def get(self, key: str) -> Any | None:
        async with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                self.stats.misses += 1
                return None
            if entry.is_expired():
                await self._delete_locked(key)
                self.stats.misses += 1
                return None
            try:
                data = entry.path.read_bytes()
            except FileNotFoundError:
                self._entries.pop(key, None)
                self.stats.misses += 1
                return None
            except OSError as exc:
                logger.warning("Disk cache read failed for %s: %s", key, exc)
                self.stats.errors += 1
                return None

            self._entries.move_to_end(key)

            try:
                value = pickle.loads(data)
            except Exception as exc:
                logger.warning("Disk cache deserialize failed for %s: %s", key, exc)
                await self._delete_locked(key)
                self.stats.errors += 1
                return None

            self.stats.hits += 1
            return value

    async def set(self, key: str, value: Any, ttl: int | None = None) -> bool:
        try:
            data = pickle.dumps(value, protocol=pickle.HIGHEST_PROTOCOL)
        except Exception as exc:
            logger.warning("Disk cache serialization failed for %s: %s", key, exc)
            self.stats.errors += 1
            return False

        if len(data) > self._max_entry_bytes:
            logger.debug(
                "Disk cache rejected oversized value",
                extra={"key": key, "size_bytes": len(data), "limit": self._max_entry_bytes},
            )
            return False

        ttl = ttl if ttl is not None else self._default_ttl
        expires_at = time.time() + ttl if ttl > 0 else None
        async with self._lock:
            path = self._path_for_key(key)
            tmp_path: Path | None = None
            try:
                with tempfile.NamedTemporaryFile(
                    mode="wb",
                    dir=self._directory,
                    prefix=".tmp-cache-",
                    delete=False,
                ) as tmp:
                    tmp.write(data)
                    tmp_path = Path(tmp.name)
                tmp_path.replace(path)
            except OSError as exc:
                if tmp_path is not None:
                    self._unlink_quietly(tmp_path)
                logger.warning("Disk cache write failed for %s: %s", key, exc)
                self.stats.errors += 1
                return False

            old_entry = self._entries.pop(key, None)
            if old_entry and old_entry.path != path:
                self._unlink_quietly(old_entry.path)
            self._entries[key] = DiskCacheEntry(
                path=path,
                expires_at=expires_at,
                created_at=time.time(),
                size_bytes=len(data),
            )
            await self._evict_if_needed_locked()

        self.stats.sets += 1
        return True

    async def incr(self, key: str, ttl: int | None = None) -> int:
        """Add 1 to a counter and return it (fixed window of ``ttl`` s, not extended).

        The entry index of this backend is per process, so counters are too. They are
        held in memory, apart from the LRU files, and are not shared across workers.
        """
        return self._counters.incr(key, ttl if ttl is not None else self._default_ttl)

    async def get_and_delete(self, key: str) -> Any | None:
        value = await self.get(key)
        if value is not None:
            await self.delete(key)
        return value

    async def delete(self, key: str) -> bool:
        async with self._lock:
            self._counters.delete(key)
            return await self._delete_locked(key)

    async def delete_pattern(self, pattern: str) -> int:
        async with self._lock:
            keys = [key for key in self._entries if fnmatch.fnmatch(key, pattern)]
            for key in keys:
                await self._delete_locked(key)
            counters_deleted = self._counters.delete_pattern(pattern)
        return len(keys) + counters_deleted

    async def exists(self, key: str) -> bool:
        async with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return False
            if entry.is_expired():
                await self._delete_locked(key)
                return False
            return entry.path.exists()

    async def clear(self) -> bool:
        async with self._lock:
            keys = list(self._entries)
            for key in keys:
                await self._delete_locked(key)
            self._counters.clear()
        logger.info("Disk cache cleared: %s entries", len(keys))
        return True

    def get_stats(self) -> dict[str, Any]:
        stats = self.stats.to_dict()
        stats["backend"] = "disk"
        stats["available"] = self.is_available()
        stats["size"] = len(self._entries)
        stats["max_size"] = self._max_size
        stats["max_entry_bytes"] = self._max_entry_bytes
        return stats

    async def _delete_locked(self, key: str) -> bool:
        entry = self._entries.pop(key, None)
        if entry is None:
            return False
        self._unlink_quietly(entry.path)
        self.stats.deletes += 1
        return True

    async def _evict_if_needed_locked(self) -> None:
        while len(self._entries) > self._max_size:
            _, entry = self._entries.popitem(last=False)
            self._unlink_quietly(entry.path)

    async def _periodic_cleanup(self) -> None:
        while self._available:
            try:
                await asyncio.sleep(self._cleanup_interval)
                await self._cleanup_expired()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("Disk cache cleanup error: %s", exc)

    async def _cleanup_expired(self) -> None:
        async with self._lock:
            expired = [key for key, entry in self._entries.items() if entry.is_expired()]
            for key in expired:
                await self._delete_locked(key)
        if expired:
            logger.debug("Disk cache removed %s expired entries", len(expired))

    def _path_for_key(self, key: str) -> Path:
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
        return self._directory / f"{digest}.cache"

    @staticmethod
    def _unlink_quietly(path: Path) -> None:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            logger.debug("Failed to remove cache file %s", path, exc_info=True)
