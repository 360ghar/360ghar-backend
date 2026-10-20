"""WebSocket endpoints for AI job progress and user notifications.

The token is not in the URL. The server accepts the socket, then waits for one
``auth`` frame (see ``app.schemas.realtime``). Close codes: 4001 for a missing
or invalid token, 4004 for a job the caller cannot see.

NOTE: Active WebSocket connections keep the server alive because the
underlying TCP connection generates outbound ACK packets. Railway's
serverless idle detection monitors outbound traffic, so any active
WebSocket session will prevent scale-to-zero. This is expected —
clients maintaining real-time connections need the server running.
"""

import asyncio

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import verify_supabase_token
from app.core.database import get_db
from app.core.logging import get_logger
from app.core.websocket import job_frame, manager
from app.schemas.realtime import (
    WS_CLOSE_NOT_FOUND,
    WS_CLOSE_UNAUTHORIZED,
    ClientAuthFrame,
    ControlFrame,
)
from app.services import tour_ai
from app.services.user import get_or_create_user_from_supabase

router = APIRouter()
logger = get_logger(__name__)

# Heartbeat interval in seconds
HEARTBEAT_INTERVAL = 30
# Time allowed between accept and the auth frame
AUTH_TIMEOUT_SECONDS = 10.0


async def resolve_websocket_user_id(token: str, db: AsyncSession) -> int | None:
    """
    Verify Supabase access token and resolve the local user id.

    Args:
        token: JWT access token

    Returns:
        Local user ID if valid, None otherwise
    """
    try:
        supabase_user_data = await verify_supabase_token(token)
        if supabase_user_data is None:
            return None

        user = await get_or_create_user_from_supabase(db, supabase_user_data)
        if not user or getattr(user, "id", None) is None:
            return None

        return int(user.id)
    except Exception as e:
        logger.warning("Token verification failed: %s", e, exc_info=True)
        return None


async def _read_auth_token(websocket: WebSocket) -> str | None:
    """Read the first frame after accept. Returns the token, or None when the frame is missing or invalid.

    A binary frame, a timeout and a disconnect are not valid auth frames.
    """
    try:
        message = await asyncio.wait_for(websocket.receive(), timeout=AUTH_TIMEOUT_SECONDS)
    except (asyncio.TimeoutError, WebSocketDisconnect):
        return None
    raw = message.get("text")
    if raw is None:
        return None
    try:
        return ClientAuthFrame.model_validate_json(raw).token
    except (ValidationError, ValueError):
        return None


async def _authenticate(websocket: WebSocket) -> int | None:
    """Read the auth frame and resolve the user. None means the caller must close with 4001."""
    token = await _read_auth_token(websocket)
    if token is None:
        return None
    async for db in get_db():
        return await resolve_websocket_user_id(token, db)
    return None


async def _close(websocket: WebSocket, code: int, reason: str) -> None:
    try:
        await websocket.close(code=code, reason=reason)
    except Exception:
        logger.debug("WebSocket close failed (code %s)", code, exc_info=True)


async def _serve(websocket: WebSocket, label: str) -> None:
    """Answer ``ping`` and send heartbeats until the client leaves or a send fails."""
    while True:
        try:
            message = await asyncio.wait_for(websocket.receive(), timeout=HEARTBEAT_INTERVAL)
        except asyncio.TimeoutError:
            try:
                await websocket.send_text(ControlFrame(type="heartbeat").model_dump_json())
            except Exception:
                logger.debug("Heartbeat send failed for %s; closing", label, exc_info=True)
                return
            continue
        if message["type"] == "websocket.disconnect":
            raise WebSocketDisconnect(message.get("code", 1000))
        # Binary frames are ignored. Only a text ping gets a reply.
        if message.get("text") == "ping":
            await websocket.send_text("pong")


@router.websocket("/ws/jobs/{job_id}")
async def websocket_job_updates(websocket: WebSocket, job_id: str):
    """AI job progress. Frames: ``job_update`` (data: status, progress, error_message, result), ``heartbeat``.

    First frame from the client: ``{"type": "auth", "token": "<JWT>"}``.
    """
    await websocket.accept()
    user_id = await _authenticate(websocket)
    if user_id is None:
        await _close(websocket, WS_CLOSE_UNAUTHORIZED, "Invalid or expired token")
        return

    job = None
    async for db in get_db():
        try:
            job = await tour_ai.get_ai_job(db, job_id, user_id)
        except HTTPException:
            job = None
        break
    if job is None:
        await _close(websocket, WS_CLOSE_NOT_FOUND, "Job not found or not authorized")
        return

    await manager.connect_job(websocket, job_id)
    try:
        await websocket.send_text(
            job_frame(
                job_id,
                {
                    "status": job.status,
                    "progress": job.progress,
                    "error_message": job.error_message,
                    "result": getattr(job, "result", None),
                },
            ).model_dump_json()
        )
        await _serve(websocket, f"job {job_id}")
    except WebSocketDisconnect:
        logger.debug("WebSocket disconnected for job %s", job_id)
    except Exception as e:
        logger.error("WebSocket error for job %s: %s", job_id, e, exc_info=True)
    finally:
        await manager.disconnect_job(websocket, job_id)


@router.websocket("/ws/user")
async def websocket_user_updates(websocket: WebSocket):
    """User notifications. Frames: ``notification`` (data: id, type, title, message, created_at), ``heartbeat``.

    First frame from the client: ``{"type": "auth", "token": "<JWT>"}``.
    """
    await websocket.accept()
    user_id = await _authenticate(websocket)
    if user_id is None:
        await _close(websocket, WS_CLOSE_UNAUTHORIZED, "Invalid or expired token")
        return

    await manager.connect_user(websocket, user_id)
    try:
        await websocket.send_text(
            ControlFrame(
                type="connected", message="Connected to user notifications"
            ).model_dump_json()
        )
        await _serve(websocket, f"user {user_id}")
    except WebSocketDisconnect:
        logger.debug("WebSocket disconnected for user %s", user_id)
    except Exception as e:
        logger.error("WebSocket error for user %s: %s", user_id, e, exc_info=True)
    finally:
        await manager.disconnect_user(websocket, user_id)
