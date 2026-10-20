"""Typed frames for the WebSocket channels. Each channel has one frame schema.

Connection flow, for every channel:

1. The server accepts the socket. No token is in the URL.
2. The client sends one text frame: ``ClientAuthFrame``. It must arrive within
   the auth timeout. A bad or missing frame closes the socket with 4001.
3. The server sends a ``ControlFrame`` of type ``connected``, or the first data frame.

Channel frames:

- ``/ws/jobs/{job_id}``: ``JobUpdateFrame`` (one per job state change)
- ``/ws/user``: ``UserNotificationFrame``

Every channel also sends ``ControlFrame`` (``connected``, ``heartbeat``).
Close codes: 4001 invalid or missing token, 4004 job not found or not
accessible to the caller.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from app.schemas.base import UtcDateTime, WriteModel

WS_CLOSE_UNAUTHORIZED = 4001
WS_CLOSE_NOT_FOUND = 4004


class ClientAuthFrame(WriteModel):
    """The first frame a client sends. The token never travels in the URL."""

    type: Literal["auth"]
    token: str = Field(min_length=1, max_length=8192)


class ControlFrame(BaseModel):
    type: Literal["connected", "heartbeat"]
    message: str | None = None


class JobUpdateData(BaseModel):
    """The state of one AI job. ``status`` is the AIJob status (pending, processing, completed, failed, cancelled)."""

    status: str
    progress: int | None = None
    error_message: str | None = None
    result: dict[str, Any] | None = None


class JobUpdateFrame(BaseModel):
    """Progress of one AI job, on ``/ws/jobs/{job_id}``."""

    type: Literal["job_update"] = "job_update"
    job_id: str
    data: JobUpdateData


class UserNotificationPayload(BaseModel):
    id: str
    type: str
    title: str
    message: str
    created_at: UtcDateTime


class UserNotificationFrame(BaseModel):
    """A notification for the signed-in user, on ``/ws/user``."""

    type: Literal["notification"] = "notification"
    data: UserNotificationPayload


__all__ = [
    "ClientAuthFrame",
    "ControlFrame",
    "JobUpdateData",
    "JobUpdateFrame",
    "UserNotificationFrame",
    "UserNotificationPayload",
    "WS_CLOSE_NOT_FOUND",
    "WS_CLOSE_UNAUTHORIZED",
]
