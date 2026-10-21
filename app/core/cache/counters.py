"""Process-local fixed-window counters for rate limits.

Kept apart from the LRU entries of a cache backend, so ordinary ``set`` traffic cannot
evict a counter and reset a limit early. ``incr`` has no ``await``, so on one event loop
it is atomic. Counters are per process: only Redis shares them across processes.
"""

from __future__ import annotations

import time

MAX_COUNTERS = 10_000


class FixedWindowCounters:
    def __init__(self, max_counters: int = MAX_COUNTERS) -> None:
        self._max = max_counters
        self._items: dict[str, tuple[int, float | None]] = {}

    def incr(self, key: str, ttl: int) -> int:
        """Add 1 and return the count. A new window starts at the first call and is not extended."""
        now = time.time()
        item = self._items.get(key)
        if item is not None and (item[1] is None or item[1] > now):
            count = item[0] + 1
            self._items[key] = (count, item[1])
            return count
        if len(self._items) >= self._max:
            self._purge(now)
        self._items[key] = (1, now + ttl if ttl > 0 else None)
        return 1

    def _purge(self, now: float) -> None:
        self._items = {k: v for k, v in self._items.items() if v[1] is None or v[1] > now}
        while len(self._items) >= self._max:  # all live: drop the oldest window
            self._items.pop(next(iter(self._items)))

    def delete(self, key: str) -> None:
        self._items.pop(key, None)

    def clear(self) -> None:
        self._items.clear()
