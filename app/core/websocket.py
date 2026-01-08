"""
WebSocket Connection Manager.

This module provides real-time communication capabilities for AI job progress
updates and user notifications.
"""
from typing import Dict, Set, Any, Optional
import asyncio
import json

from fastapi import WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

from app.core.logging import get_logger

logger = get_logger(__name__)


class ConnectionManager:
    """
    Manages WebSocket connections for real-time updates.

    Supports:
    - Job-specific connections (for AI job progress)
    - User-level connections (for notifications)
    """

    def __init__(self):
        # Maps job_id -> set of connected websockets
        self.job_connections: Dict[str, Set[WebSocket]] = {}
        # Maps user_id -> set of connected websockets
        self.user_connections: Dict[int, Set[WebSocket]] = {}
        # Lock for thread-safe operations
        self._lock = asyncio.Lock()

    async def connect_job(self, websocket: WebSocket, job_id: str) -> None:
        """Connect a websocket to receive updates for a specific job."""
        await websocket.accept()
        async with self._lock:
            if job_id not in self.job_connections:
                self.job_connections[job_id] = set()
            self.job_connections[job_id].add(websocket)
        logger.debug(f"WebSocket connected for job {job_id}")

    async def connect_user(self, websocket: WebSocket, user_id: int) -> None:
        """Connect a websocket to receive updates for a user."""
        await websocket.accept()
        async with self._lock:
            if user_id not in self.user_connections:
                self.user_connections[user_id] = set()
            self.user_connections[user_id].add(websocket)
        logger.debug(f"WebSocket connected for user {user_id}")

    def disconnect_job(self, websocket: WebSocket, job_id: str) -> None:
        """Disconnect a websocket from job updates."""
        if job_id in self.job_connections:
            self.job_connections[job_id].discard(websocket)
            if not self.job_connections[job_id]:
                del self.job_connections[job_id]
        logger.debug(f"WebSocket disconnected from job {job_id}")

    def disconnect_user(self, websocket: WebSocket, user_id: int) -> None:
        """Disconnect a websocket from user updates."""
        if user_id in self.user_connections:
            self.user_connections[user_id].discard(websocket)
            if not self.user_connections[user_id]:
                del self.user_connections[user_id]
        logger.debug(f"WebSocket disconnected from user {user_id}")

    async def send_job_update(
        self,
        job_id: str,
        data: Dict[str, Any],
    ) -> None:
        """
        Send an update to all websockets connected to a job.

        Args:
            job_id: The job ID to send updates to
            data: Update data (status, progress, result, etc.)
        """
        if job_id not in self.job_connections:
            return

        message = json.dumps({
            "type": "job_update",
            "job_id": job_id,
            "data": data,
        })

        # Create a copy to avoid modification during iteration
        connections = list(self.job_connections.get(job_id, set()))
        dead_connections = []

        for websocket in connections:
            try:
                if websocket.client_state == WebSocketState.CONNECTED:
                    await websocket.send_text(message)
            except Exception as e:
                logger.warning(f"Failed to send job update: {e}")
                dead_connections.append(websocket)

        # Clean up dead connections
        for ws in dead_connections:
            self.disconnect_job(ws, job_id)

    async def send_user_notification(
        self,
        user_id: int,
        notification: Dict[str, Any],
    ) -> None:
        """
        Send a notification to all websockets connected for a user.

        Args:
            user_id: The user ID to send notification to
            notification: Notification data
        """
        if user_id not in self.user_connections:
            return

        message = json.dumps({
            "type": "notification",
            "data": notification,
        })

        connections = list(self.user_connections.get(user_id, set()))
        dead_connections = []

        for websocket in connections:
            try:
                if websocket.client_state == WebSocketState.CONNECTED:
                    await websocket.send_text(message)
            except Exception as e:
                logger.warning(f"Failed to send user notification: {e}")
                dead_connections.append(websocket)

        for ws in dead_connections:
            self.disconnect_user(ws, user_id)

    async def broadcast_job_completion(
        self,
        job_id: str,
        user_id: int,
        result: Dict[str, Any],
    ) -> None:
        """
        Broadcast job completion to both job and user connections.

        Args:
            job_id: The completed job ID
            user_id: The user who owns the job
            result: Job result data
        """
        # Send to job-specific connections
        await self.send_job_update(job_id, {
            "status": "completed",
            "progress": 100,
            "result": result,
        })

        # Send notification to user connections
        await self.send_user_notification(user_id, {
            "type": "job_completed",
            "job_id": job_id,
            "result": result,
        })

    async def broadcast_job_error(
        self,
        job_id: str,
        user_id: int,
        error_message: str,
    ) -> None:
        """
        Broadcast job error to both job and user connections.

        Args:
            job_id: The failed job ID
            user_id: The user who owns the job
            error_message: Error message
        """
        await self.send_job_update(job_id, {
            "status": "failed",
            "error": error_message,
        })

        await self.send_user_notification(user_id, {
            "type": "job_failed",
            "job_id": job_id,
            "error": error_message,
        })

    def get_job_connection_count(self, job_id: str) -> int:
        """Get the number of connections for a job."""
        return len(self.job_connections.get(job_id, set()))

    def get_user_connection_count(self, user_id: int) -> int:
        """Get the number of connections for a user."""
        return len(self.user_connections.get(user_id, set()))


# Global connection manager instance
manager = ConnectionManager()
