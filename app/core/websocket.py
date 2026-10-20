"""WebSocket connection manager for AI job progress and user notifications.

Frames are the typed models in ``app.schemas.realtime``. The endpoint accepts the
socket and authenticates it. The manager only tracks connections and sends frames.
"""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import WebSocket
from starlette.websockets import WebSocketState

from app.core.logging import get_logger
from app.core.utils import utc_now
from app.schemas.realtime import (
    JobUpdateData,
    JobUpdateFrame,
    UserNotificationFrame,
    UserNotificationPayload,
)

logger = get_logger(__name__)


def job_frame(job_id: str, data: dict[str, Any]) -> JobUpdateFrame:
    """Build the job frame from the state dict used by the job pipeline.

    Keys: ``status``, ``progress``, ``error_message``, ``result``. Missing keys are null.
    """
    progress = data.get("progress")
    return JobUpdateFrame(
        job_id=job_id,
        data=JobUpdateData(
            status=str(data.get("status") or ""),
            progress=int(progress) if progress is not None else None,
            error_message=data.get("error_message"),
            result=data.get("result"),
        ),
    )


class ConnectionManager:
    """Tracks WebSocket connections per job and per user.

    Supports:
    - Job connections (AI job progress, keyed by job_id)
    - User connections (notifications)
    """

    def __init__(self):
        # Maps job_id -> set of connected websockets
        self.job_connections: dict[str, set[WebSocket]] = {}
        # Maps user_id -> set of connected websockets
        self.user_connections: dict[int, set[WebSocket]] = {}
        # Lock for thread-safe operations
        self._lock = asyncio.Lock()

    async def connect_job(self, websocket: WebSocket, job_id: str) -> None:
        """Register an accepted, authenticated socket for a job. The caller accepts it."""
        async with self._lock:
            if job_id not in self.job_connections:
                self.job_connections[job_id] = set()
            self.job_connections[job_id].add(websocket)
        logger.debug("WebSocket connected for job %s", job_id)

    async def connect_user(self, websocket: WebSocket, user_id: int) -> None:
        """Register an accepted, authenticated socket for a user. The caller accepts it."""
        async with self._lock:
            if user_id not in self.user_connections:
                self.user_connections[user_id] = set()
            self.user_connections[user_id].add(websocket)
        logger.debug("WebSocket connected for user %s", user_id)

    async def disconnect_job(self, websocket: WebSocket, job_id: str) -> None:
        """Disconnect a websocket from job updates."""
        async with self._lock:
            if job_id in self.job_connections:
                self.job_connections[job_id].discard(websocket)
                if not self.job_connections[job_id]:
                    del self.job_connections[job_id]
        logger.debug("WebSocket disconnected from job %s", job_id)

    async def disconnect_user(self, websocket: WebSocket, user_id: int) -> None:
        """Disconnect a websocket from user updates."""
        async with self._lock:
            if user_id in self.user_connections:
                self.user_connections[user_id].discard(websocket)
                if not self.user_connections[user_id]:
                    del self.user_connections[user_id]
        logger.debug("WebSocket disconnected from user %s", user_id)

    async def _send_text(self, sockets: list[WebSocket], message: str) -> list[WebSocket]:
        dead: list[WebSocket] = []
        for websocket in sockets:
            try:
                if websocket.client_state == WebSocketState.CONNECTED:
                    await websocket.send_text(message)
            except Exception as e:
                logger.warning("Failed to send WebSocket frame: %s", e)
                dead.append(websocket)
        return dead

    async def send_job_update(self, job_id: str, data: dict[str, Any]) -> None:
        """Send one ``job_update`` frame to every socket connected to ``job_id``."""
        if job_id not in self.job_connections:
            return
        message = job_frame(job_id, data).model_dump_json()
        dead = await self._send_text(list(self.job_connections.get(job_id, set())), message)
        for ws in dead:
            await self.disconnect_job(ws, job_id)

    async def send_user_notification(self, user_id: int, notification: dict[str, Any]) -> None:
        """Send a ``notification`` frame. ``notification`` holds id, type, title, message, created_at."""
        if user_id not in self.user_connections:
            return
        frame = UserNotificationFrame(data=UserNotificationPayload.model_validate(notification))
        dead = await self._send_text(
            list(self.user_connections.get(user_id, set())), frame.model_dump_json()
        )
        for ws in dead:
            await self.disconnect_user(ws, user_id)

    async def broadcast_job_completion(
        self,
        job_id: str,
        user_id: int,
        result: dict[str, Any],
    ) -> None:
        """Send the titled completion notification to user sockets.

        The job socket gets its frame from the caller (``send_job_update``), once per state.
        """
        await self.send_user_notification(
            user_id,
            {
                "id": job_id,
                "type": "job_completed",
                "title": "Processing complete",
                "message": "Your tour job has finished.",
                "created_at": utc_now(),
            },
        )

    async def broadcast_job_error(
        self,
        job_id: str,
        user_id: int,
        error_message: str,
    ) -> None:
        """Send the titled failure notification to user sockets. The job frame comes from the caller."""
        await self.send_user_notification(
            user_id,
            {
                "id": job_id,
                "type": "job_failed",
                "title": "Processing failed",
                "message": error_message,
                "created_at": utc_now(),
            },
        )

    def get_job_connection_count(self, job_id: str) -> int:
        """Get the number of connections for a job."""
        return len(self.job_connections.get(job_id, set()))

    def get_user_connection_count(self, user_id: int) -> int:
        """Get the number of connections for a user."""
        return len(self.user_connections.get(user_id, set()))


manager = ConnectionManager()
