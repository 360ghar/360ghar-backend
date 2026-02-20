"""
WebSocket API Endpoints.

This module provides WebSocket endpoints for real-time updates:
- AI job progress tracking
- User notifications
"""
import asyncio
from typing import Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.logging import get_logger
from app.core.websocket import manager
from app.core.auth import verify_supabase_token
from app.services import tour_ai
from app.services.user import get_or_create_user_from_supabase

router = APIRouter()
logger = get_logger(__name__)

# Heartbeat interval in seconds
HEARTBEAT_INTERVAL = 30


async def resolve_websocket_user_id(token: str, db: AsyncSession) -> Optional[int]:
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
        logger.warning(f"Token verification failed: {e}")
        return None


@router.websocket("/ws/jobs/{job_id}")
async def websocket_job_updates(
    websocket: WebSocket,
    job_id: str,
    token: str = Query(..., description="JWT access token"),
):
    """
    WebSocket endpoint for real-time AI job progress updates.

    Connect to receive updates for a specific AI job including:
    - Progress percentage
    - Status changes
    - Final results or errors

    Query Parameters:
        token: JWT access token for authentication

    Messages sent:
        {
            "type": "job_update",
            "job_id": "...",
            "data": {
                "status": "processing",
                "progress": 50,
                "result": null
            }
        }
    """
    async for db in get_db():
        user_id = await resolve_websocket_user_id(token, db)
        if user_id is None:
            await websocket.close(code=4001, reason="Invalid or expired token")
            return

        try:
            job = await tour_ai.get_ai_job(db, job_id, user_id)
        except HTTPException:
            await websocket.close(code=4004, reason="Job not found or not authorized")
            return

        # Connect to job updates (accept websocket)
        await manager.connect_job(websocket, job_id)

        await websocket.send_json({
            "type": "job_update",
            "job_id": job_id,
            "data": {
                "status": job.status,
                "progress": job.progress,
                "result": job.result if hasattr(job, "result") else None,
                "error_message": job.error_message,
            },
        })
        break

    try:

        # Keep connection alive and handle incoming messages
        while True:
            try:
                # Wait for message or timeout (heartbeat)
                message = await asyncio.wait_for(
                    websocket.receive_text(),
                    timeout=HEARTBEAT_INTERVAL
                )

                # Handle ping/pong for keep-alive
                if message == "ping":
                    await websocket.send_text("pong")

            except asyncio.TimeoutError:
                # Send heartbeat
                try:
                    await websocket.send_json({"type": "heartbeat"})
                except Exception:
                    break

    except WebSocketDisconnect:
        logger.debug(f"WebSocket disconnected for job {job_id}")
    except Exception as e:
        logger.error(f"WebSocket error for job {job_id}: {e}")
    finally:
        manager.disconnect_job(websocket, job_id)


@router.websocket("/ws/user")
async def websocket_user_updates(
    websocket: WebSocket,
    token: str = Query(..., description="JWT access token"),
):
    """
    WebSocket endpoint for user-level notifications.

    Connect to receive notifications including:
    - AI job completions
    - Tour updates
    - System notifications

    Query Parameters:
        token: JWT access token for authentication

    Messages sent:
        {
            "type": "notification",
            "data": {
                "type": "job_completed",
                "job_id": "...",
                "result": {...}
            }
        }
    """
    async for db in get_db():
        user_id = await resolve_websocket_user_id(token, db)
        if user_id is None:
            await websocket.close(code=4001, reason="Invalid or expired token")
            return

        await manager.connect_user(websocket, user_id)
        break

    try:
        # Send welcome message
        await websocket.send_json({
            "type": "connected",
            "message": "Connected to user notifications"
        })

        # Keep connection alive
        while True:
            try:
                message = await asyncio.wait_for(
                    websocket.receive_text(),
                    timeout=HEARTBEAT_INTERVAL
                )

                if message == "ping":
                    await websocket.send_text("pong")

            except asyncio.TimeoutError:
                try:
                    await websocket.send_json({"type": "heartbeat"})
                except Exception:
                    break

    except WebSocketDisconnect:
        logger.debug(f"WebSocket disconnected for user {user_id}")
    except Exception as e:
        logger.error(f"WebSocket error for user {user_id}: {e}")
    finally:
        manager.disconnect_user(websocket, user_id)


@router.websocket("/ws/tours/{tour_id}")
async def websocket_tour_updates(
    websocket: WebSocket,
    tour_id: str,
    token: str = Query(..., description="JWT access token"),
):
    """
    WebSocket endpoint for tour-specific updates.

    Connect to receive real-time updates for a specific tour:
    - Scene processing status
    - Hotspot changes (for collaborative editing)
    - AI processing results

    Query Parameters:
        token: JWT access token for authentication
    """
    async for db in get_db():
        user_id = await resolve_websocket_user_id(token, db)
        if user_id is None:
            await websocket.close(code=4001, reason="Invalid or expired token")
            return
        break

    # Use tour_id as a "job_id" for connection management
    connection_key = f"tour:{tour_id}"
    await manager.connect_job(websocket, connection_key)

    try:
        await websocket.send_json({
            "type": "connected",
            "message": f"Connected to tour {tour_id} updates"
        })

        while True:
            try:
                message = await asyncio.wait_for(
                    websocket.receive_text(),
                    timeout=HEARTBEAT_INTERVAL
                )

                if message == "ping":
                    await websocket.send_text("pong")

            except asyncio.TimeoutError:
                try:
                    await websocket.send_json({"type": "heartbeat"})
                except Exception:
                    break

    except WebSocketDisconnect:
        logger.debug(f"WebSocket disconnected for tour {tour_id}")
    except Exception as e:
        logger.error(f"WebSocket error for tour {tour_id}: {e}")
    finally:
        manager.disconnect_job(websocket, connection_key)
