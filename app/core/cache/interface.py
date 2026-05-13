"""
Abstract cache interface following Protocol pattern for structural subtyping.
This allows backends to be swapped without inheritance coupling.
"""

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class CacheBackend(Protocol):
    """Protocol defining the cache backend interface.

    All cache backends must implement these methods. Using Protocol
    instead of ABC allows for structural subtyping and better testing.
    """

    async def get(self, key: str) -> Any | None:
        """Retrieve value from cache. Returns None if not found or expired."""
        ...

    async def set(self, key: str, value: Any, ttl: int | None = None) -> bool:
        """Store value in cache with optional TTL in seconds. Returns success status."""
        ...

    async def get_and_delete(self, key: str) -> Any | None:
        """Atomically retrieve value and delete key. Returns None if not found or expired.

        This prevents TOCTOU race conditions where a value is read and then
        deleted in separate non-atomic steps.
        """
        ...

    async def delete(self, key: str) -> bool:
        """Delete a single key. Returns True if deleted, False if not found."""
        ...

    async def delete_pattern(self, pattern: str) -> int:
        """Delete all keys matching pattern (e.g., 'properties:*'). Returns count deleted."""
        ...

    async def exists(self, key: str) -> bool:
        """Check if key exists in cache."""
        ...

    async def clear(self) -> bool:
        """Clear all keys from cache. Returns success status."""
        ...

    async def connect(self) -> None:
        """Initialize connection (if needed). Called during app startup."""
        ...

    async def disconnect(self) -> None:
        """Close connection (if needed). Called during app shutdown."""
        ...

    def is_available(self) -> bool:
        """Check if cache backend is ready for operations."""
        ...


@dataclass
class CacheStats:
    """Cache statistics for monitoring and debugging."""

    hits: int = field(default=0)
    misses: int = field(default=0)
    sets: int = field(default=0)
    deletes: int = field(default=0)
    errors: int = field(default=0)

    @property
    def hit_rate(self) -> float:
        """Calculate cache hit rate."""
        total = self.hits + self.misses
        return self.hits / total if total > 0 else 0.0

    def to_dict(self) -> dict:
        """Convert stats to dictionary for serialization."""
        return {
            "hits": self.hits,
            "misses": self.misses,
            "sets": self.sets,
            "deletes": self.deletes,
            "errors": self.errors,
            "hit_rate": round(self.hit_rate, 4),
        }

    def reset(self) -> None:
        """Reset all statistics to zero."""
        self.hits = 0
        self.misses = 0
        self.sets = 0
        self.deletes = 0
        self.errors = 0
