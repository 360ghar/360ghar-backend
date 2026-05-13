from __future__ import annotations

import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)


class SSEEventBus:
    """Lightweight pub/sub that maps user_id to a set of asyncio queues.

    Service methods call ``emit(user_id, event_dict)`` after DB commit.
    The SSE endpoint consumes from its queue via ``subscribe`` / ``unsubscribe``.
    """

    def __init__(self) -> None:
        self._queues: dict[int, list[asyncio.Queue[dict[str, Any]]]] = {}
        self._lock = asyncio.Lock()
        self._emit_count = 0

    async def subscribe(self, user_id: int) -> asyncio.Queue[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=256)
        async with self._lock:
            self._queues.setdefault(user_id, []).append(queue)
        return queue

    async def unsubscribe(self, user_id: int, queue: asyncio.Queue[dict[str, Any]]) -> None:
        async with self._lock:
            queues = self._queues.get(user_id)
            if queues is None:
                return
            try:
                queues.remove(queue)
            except ValueError:
                pass
            if not queues:
                del self._queues[user_id]

    async def emit(self, user_id: int, event: dict[str, Any]) -> None:
        """Fire-and-forget push to all queues for *user_id*.

        Non-blocking: drops the oldest item when a queue is full.
        Periodically reaps dead queues (those whose consumer has abandoned them).

        Must be called from an async context (e.g., ``await sse_bus.emit(...)``).
        """
        should_reap = False
        async with self._lock:
            queues = self._queues.get(user_id)
            if not queues:
                return
            for q in queues:
                try:
                    q.put_nowait(event)
                except asyncio.QueueFull:
                    try:
                        q.get_nowait()
                    except asyncio.QueueEmpty:
                        pass
                    try:
                        q.put_nowait(event)
                    except asyncio.QueueFull:
                        logger.warning("SSE queue full for user %s, dropping event", user_id)

            self._emit_count += 1
            if self._emit_count % 100 == 0:
                should_reap = True

        if should_reap:
            await self._reap_dead_queues_async()

    async def _reap_dead_queues_async(self) -> None:
        """Collect stale queue info under a brief lock, then reap."""
        async with self._lock:
            snapshot = {
                uid: list(queues) for uid, queues in self._queues.items()
            }

        stale_users: list[int] = []
        for uid, queues in snapshot.items():
            alive = [q for q in queues if not q.full()]
            if alive:
                async with self._lock:
                    current = self._queues.get(uid)
                    if current is not None:
                        current[:] = alive
            else:
                stale_users.append(uid)

        if stale_users:
            async with self._lock:
                for uid in stale_users:
                    if uid in self._queues and not self._queues[uid]:
                        del self._queues[uid]


sse_bus = SSEEventBus()
