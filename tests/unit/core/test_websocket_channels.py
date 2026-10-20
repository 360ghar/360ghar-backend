"""WebSocket channels: first-frame auth, close codes and typed frame shapes.

The DB session, token verification and job lookup are patched, so these run
without a database.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI, HTTPException
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.api.api_v1.endpoints import websocket as ws_module
from app.schemas.realtime import (
    ClientAuthFrame,
    JobUpdateData,
    JobUpdateFrame,
    UserNotificationFrame,
    UserNotificationPayload,
)

MODULE = "app.api.api_v1.endpoints.websocket"


async def _fake_get_db():
    yield object()


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(ws_module.router)
    return TestClient(app)


def _job(status: str = "processing") -> SimpleNamespace:
    return SimpleNamespace(status=status, progress=40, error_message=None, result=None)


def test_job_channel_authenticates_with_first_frame(client):
    with (
        patch(f"{MODULE}.get_db", _fake_get_db),
        patch(f"{MODULE}.resolve_websocket_user_id", AsyncMock(return_value=7)),
        patch(f"{MODULE}.tour_ai.get_ai_job", AsyncMock(return_value=_job())),
        client.websocket_connect("/ws/jobs/job-1") as ws,
    ):
        ws.send_text(json.dumps({"type": "auth", "token": "good-token"}))
        frame = json.loads(ws.receive_text())

    assert frame == {
        "type": "job_update",
        "job_id": "job-1",
        "data": {
            "status": "processing",
            "progress": 40,
            "error_message": None,
            "result": None,
        },
    }


def test_token_in_query_string_is_not_accepted(client):
    """A token in the URL is ignored. Without an auth frame the socket closes with 4001."""
    with (
        patch(f"{MODULE}.get_db", _fake_get_db),
        patch(f"{MODULE}.resolve_websocket_user_id", AsyncMock(return_value=7)),
        client.websocket_connect("/ws/user?token=good-token") as ws,
    ):
        ws.send_text(json.dumps({"type": "hello"}))
        with pytest.raises(WebSocketDisconnect) as exc_info:
            ws.receive_text()
    assert exc_info.value.code == 4001


def test_invalid_token_closes_with_4001(client):
    with (
        patch(f"{MODULE}.get_db", _fake_get_db),
        patch(f"{MODULE}.resolve_websocket_user_id", AsyncMock(return_value=None)),
        client.websocket_connect("/ws/user") as ws,
    ):
        ws.send_text(json.dumps({"type": "auth", "token": "bad"}))
        with pytest.raises(WebSocketDisconnect) as exc_info:
            ws.receive_text()
    assert exc_info.value.code == 4001


def test_unknown_job_closes_with_4004(client):
    with (
        patch(f"{MODULE}.get_db", _fake_get_db),
        patch(f"{MODULE}.resolve_websocket_user_id", AsyncMock(return_value=7)),
        patch(
            f"{MODULE}.tour_ai.get_ai_job", AsyncMock(side_effect=HTTPException(status_code=404))
        ),
        client.websocket_connect("/ws/jobs/missing") as ws,
    ):
        ws.send_text(json.dumps({"type": "auth", "token": "good-token"}))
        with pytest.raises(WebSocketDisconnect) as exc_info:
            ws.receive_text()
    assert exc_info.value.code == 4004


def test_tour_channel_is_not_mounted():
    """No client connects to /ws/tours, and nothing emits to it, so the route is gone."""
    paths = {getattr(route, "path", None) for route in ws_module.router.routes}
    assert "/ws/tours/{tour_id}" not in paths
    assert {"/ws/jobs/{job_id}", "/ws/user"} <= paths


def test_user_channel_sends_connected_frame(client):
    with (
        patch(f"{MODULE}.get_db", _fake_get_db),
        patch(f"{MODULE}.resolve_websocket_user_id", AsyncMock(return_value=7)),
        client.websocket_connect("/ws/user") as ws,
    ):
        ws.send_text(json.dumps({"type": "auth", "token": "good-token"}))
        frame = json.loads(ws.receive_text())
    assert frame["type"] == "connected"


def test_auth_frame_rejects_unknown_keys():
    with pytest.raises(ValueError):
        ClientAuthFrame.model_validate({"type": "auth", "token": "t", "extra": 1})


def test_job_frame_schema_nests_status_under_data():
    frame = JobUpdateFrame(job_id="j", data=JobUpdateData(status="failed", error_message="boom"))
    payload = json.loads(frame.model_dump_json())
    assert set(payload) == {"type", "job_id", "data"}
    assert set(payload["data"]) == {"status", "progress", "error_message", "result"}
    assert payload["data"]["status"] == "failed"


def test_notification_frame_schema_fields_and_utc_timestamp():
    from datetime import datetime

    frame = UserNotificationFrame(
        data=UserNotificationPayload(
            id="n1",
            type="booking_confirmed",
            title="Booked",
            message="Your booking is confirmed",
            created_at=datetime(2026, 10, 14, 9, 30),
        )
    )
    payload = json.loads(frame.model_dump_json())
    assert payload["type"] == "notification"
    assert set(payload["data"]) == {"id", "type", "title", "message", "created_at"}
    assert payload["data"]["created_at"] == "2026-10-14T09:30:00Z"
