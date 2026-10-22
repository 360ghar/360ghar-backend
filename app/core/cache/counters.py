"""Process-local fixed-window counters for rate limits.

Kept apart from the LRU entries of a cache backend, so ordinary ``set`` traffic cannot
evict a counter and reset a limit early. ``incr`` has no ``await``, so on one event loop
it is atomic. Counters are per process: only Redis shares them across processes.
"""

from __future__ import annotations

import fnmatch
import time

MAX_COUNTERS = 100_000
_SWEEP_INTERVAL = 1.0  # seconds between sweeps of expired counters


class FixedWindowCounters:
    def __init__(self, max_counters: int = MAX_COUNTERS) -> None:
        self._max = max_counters
        self._items: dict[str, tuple[int, float | None]] = {}
        self._last_sweep = 0.0

    def incr(self, key: str, ttl: int) -> int:
        """Add 1 and return the count. A new window starts at the first call and is not extended.

        The clock is monotonic, so a wall-clock change cannot cut or extend a window. A live
        counter is never evicted: when the table is full of live counters, a new key is not
        stored and counts as 1 (fails open for that key), so no active window is reset.
        """
        now = time.monotonic()
        item = self._items.get(key)
        if item is not None and (item[1] is None or item[1] > now):
            count = item[0] + 1
            self._items[key] = (count, item[1])
            return count
        if len(self._items) >= self._max:
            self._sweep(now)
            if len(self._items) >= self._max:
                return 1
        self._items[key] = (1, now + ttl if ttl > 0 else None)
        return 1

    def decr(self, key: str) -> int:
        """Take back one count from a live window (never below 0). Returns the new count."""
        item = self._items.get(key)
        if item is None or (item[1] is not None and item[1] <= time.monotonic()):
            return 0
        count = max(0, item[0] - 1)
        self._items[key] = (count, item[1])
        return count

    def _sweep(self, now: float) -> None:
        if now - self._last_sweep < _SWEEP_INTERVAL:
            return
        self._last_sweep = now
        self._items = {k: v for k, v in self._items.items() if v[1] is None or v[1] > now}

    def delete(self, key: str) -> None:
        self._items.pop(key, None)

    def delete_pattern(self, pattern: str) -> int:
        keys = [k for k in self._items if fnmatch.fnmatch(k, pattern)]
        for key in keys:
            del self._items[key]
        return len(keys)

    def clear(self) -> None:
        self._items.clear()
