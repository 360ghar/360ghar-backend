"""The first WebSocket frame carries the token. Binary or missing frames are not auth."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.api.api_v1.endpoints.websocket import _read_auth_token


def _socket(message: dict) -> MagicMock:
    ws = MagicMock()
    ws.receive = AsyncMock(return_value=message)
    return ws


@pytest.mark.asyncio
async def test_text_auth_frame_returns_the_token():
    ws = _socket({"type": "websocket.receive", "text": '{"type": "auth", "token": "abc"}'})
    assert await _read_auth_token(ws) == "abc"


@pytest.mark.asyncio
async def test_binary_first_frame_is_not_an_auth_frame():
    ws = _socket({"type": "websocket.receive", "bytes": b"\x00\x01"})
    assert await _read_auth_token(ws) is None


@pytest.mark.asyncio
async def test_disconnect_before_auth_returns_none():
    ws = _socket({"type": "websocket.disconnect", "code": 1000})
    assert await _read_auth_token(ws) is None
