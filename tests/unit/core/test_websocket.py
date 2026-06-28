"""
Tests for app.core.websocket module — ConnectionManager.
"""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.websocket import ConnectionManager


@pytest.fixture
def manager():
    """Fresh ConnectionManager for each test."""
    return ConnectionManager()


@pytest.fixture
def mock_websocket():
    """Mock WebSocket with connected state."""
    ws = AsyncMock()
    ws.accept = AsyncMock()
    ws.send_text = AsyncMock()
    ws.client_state = MagicMock()
    from starlette.websockets import WebSocketState
    ws.client_state = WebSocketState.CONNECTED
    return ws


class TestJobConnections:
    """Tests for job-based WebSocket connections."""

    @pytest.mark.asyncio
    async def test_connect_job(self, manager, mock_websocket):
        await manager.connect_job(mock_websocket, "job-123")
        assert "job-123" in manager.job_connections
        assert mock_websocket in manager.job_connections["job-123"]
        mock_websocket.accept.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_disconnect_job(self, manager, mock_websocket):
        await manager.connect_job(mock_websocket, "job-123")
        await manager.disconnect_job(mock_websocket, "job-123")
        assert "job-123" not in manager.job_connections

    @pytest.mark.asyncio
    async def test_disconnect_job_removes_empty_set(self, manager, mock_websocket):
        await manager.connect_job(mock_websocket, "job-456")
        await manager.disconnect_job(mock_websocket, "job-456")
        assert "job-456" not in manager.job_connections

    @pytest.mark.asyncio
    async def test_disconnect_nonexistent_job_no_error(self, manager, mock_websocket):
        await manager.disconnect_job(mock_websocket, "nonexistent")

    @pytest.mark.asyncio
    async def test_multiple_connections_same_job(self, manager):
        ws1 = AsyncMock()
        ws1.accept = AsyncMock()
        ws2 = AsyncMock()
        ws2.accept = AsyncMock()

        await manager.connect_job(ws1, "job-abc")
        await manager.connect_job(ws2, "job-abc")

        assert len(manager.job_connections["job-abc"]) == 2

    @pytest.mark.asyncio
    async def test_send_job_update(self, manager, mock_websocket):
        await manager.connect_job(mock_websocket, "job-xyz")
        await manager.send_job_update("job-xyz", {"status": "processing", "progress": 50})

        mock_websocket.send_text.assert_awaited_once()
        sent_data = json.loads(mock_websocket.send_text.call_args[0][0])
        assert sent_data["type"] == "job_update"
        assert sent_data["job_id"] == "job-xyz"
        assert sent_data["data"]["progress"] == 50

    @pytest.mark.asyncio
    async def test_send_job_update_no_connections(self, manager):
        # Should not raise when no connections
        await manager.send_job_update("no-connections", {"status": "done"})

    @pytest.mark.asyncio
    async def test_send_job_update_dead_connection_cleaned_up(self, manager):
        dead_ws = AsyncMock()
        dead_ws.accept = AsyncMock()
        dead_ws.send_text = AsyncMock(side_effect=Exception("Connection closed"))
        dead_ws.client_state = MagicMock()

        from starlette.websockets import WebSocketState
        dead_ws.client_state = WebSocketState.CONNECTED

        await manager.connect_job(dead_ws, "job-dead")
        await manager.send_job_update("job-dead", {"status": "failed"})

        assert "job-dead" not in manager.job_connections

    def test_get_job_connection_count(self, manager):
        assert manager.get_job_connection_count("no-job") == 0


class TestUserConnections:
    """Tests for user-based WebSocket connections."""

    @pytest.mark.asyncio
    async def test_connect_user(self, manager, mock_websocket):
        await manager.connect_user(mock_websocket, 42)
        assert 42 in manager.user_connections
        mock_websocket.accept.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_disconnect_user(self, manager, mock_websocket):
        await manager.connect_user(mock_websocket, 42)
        await manager.disconnect_user(mock_websocket, 42)
        assert 42 not in manager.user_connections

    @pytest.mark.asyncio
    async def test_send_user_notification(self, manager, mock_websocket):
        await manager.connect_user(mock_websocket, 42)
        await manager.send_user_notification(42, {"title": "New message", "body": "Hello"})

        mock_websocket.send_text.assert_awaited_once()
        sent_data = json.loads(mock_websocket.send_text.call_args[0][0])
        assert sent_data["type"] == "notification"
        assert sent_data["data"]["title"] == "New message"

    @pytest.mark.asyncio
    async def test_send_user_notification_no_connections(self, manager):
        await manager.send_user_notification(999, {"title": "No one"})

    def test_get_user_connection_count(self, manager):
        assert manager.get_user_connection_count(99) == 0


class TestBroadcasts:
    """Tests for broadcast methods."""

    @pytest.mark.asyncio
    async def test_broadcast_job_completion(self, manager, mock_websocket):
        job_ws = AsyncMock()
        job_ws.accept = AsyncMock()
        job_ws.send_text = AsyncMock()
        job_ws.client_state = MagicMock()
        from starlette.websockets import WebSocketState
        job_ws.client_state = WebSocketState.CONNECTED

        user_ws = AsyncMock()
        user_ws.accept = AsyncMock()
        user_ws.send_text = AsyncMock()
        user_ws.client_state = MagicMock()
        user_ws.client_state = WebSocketState.CONNECTED

        await manager.connect_job(job_ws, "job-complete")
        await manager.connect_user(user_ws, 10)

        await manager.broadcast_job_completion("job-complete", 10, {"result": "success"})

        # Job connection gets job_update
        job_ws.send_text.assert_awaited()
        job_data = json.loads(job_ws.send_text.call_args[0][0])
        assert job_data["data"]["status"] == "completed"

        # User connection gets notification
        user_ws.send_text.assert_awaited()
        user_data = json.loads(user_ws.send_text.call_args[0][0])
        assert user_data["data"]["type"] == "job_completed"

    @pytest.mark.asyncio
    async def test_broadcast_job_error(self, manager):
        job_ws = AsyncMock()
        job_ws.accept = AsyncMock()
        job_ws.send_text = AsyncMock()
        job_ws.client_state = MagicMock()
        from starlette.websockets import WebSocketState
        job_ws.client_state = WebSocketState.CONNECTED

        user_ws = AsyncMock()
        user_ws.accept = AsyncMock()
        user_ws.send_text = AsyncMock()
        user_ws.client_state = MagicMock()
        user_ws.client_state = WebSocketState.CONNECTED

        await manager.connect_job(job_ws, "job-err")
        await manager.connect_user(user_ws, 20)

        await manager.broadcast_job_error("job-err", 20, "AI model failed")

        job_ws.send_text.assert_awaited()
        job_data = json.loads(job_ws.send_text.call_args[0][0])
        assert job_data["data"]["status"] == "failed"

        user_ws.send_text.assert_awaited()
        user_data = json.loads(user_ws.send_text.call_args[0][0])
        assert user_data["data"]["type"] == "job_failed"
