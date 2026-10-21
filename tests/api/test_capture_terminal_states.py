"""Capture session terminal states: ready, failed and cancelled (decisions.md, Wave 3d).

The name is `ready`. There is no `done` state. Nothing moves out of a terminal state, and a
repeat of the same terminal status returns the row unchanged.
"""

from __future__ import annotations

import pytest
from sqlalchemy import update

from app.models.capture import CaptureSession
from app.models.enums import CaptureSessionStatus
from app.services.capture.sessions import _TERMINAL


def test_the_state_names_and_the_terminal_set():
    assert {status.value for status in CaptureSessionStatus} == {
        "draft",
        "capturing",
        "review",
        "uploading",
        "processing",
        "ready",
        "failed",
        "cancelled",
    }
    assert _TERMINAL == {
        CaptureSessionStatus.ready,
        CaptureSessionStatus.failed,
        CaptureSessionStatus.cancelled,
    }


@pytest.mark.asyncio
async def test_done_is_not_a_status(user_client):
    created = await user_client.post("/api/v1/capture-sessions", json={"title": "Capture"})
    session_id = created.json()["id"]

    response = await user_client.patch(
        f"/api/v1/capture-sessions/{session_id}", json={"status": "done"}
    )

    assert response.status_code == 422, response.text


@pytest.mark.asyncio
@pytest.mark.parametrize("terminal", ["ready", "cancelled"])
async def test_ready_and_cancelled_are_terminal(user_client, db_session, terminal):
    created = await user_client.post("/api/v1/capture-sessions", json={"title": "Capture"})
    session_id = created.json()["id"]
    await db_session.execute(
        update(CaptureSession)
        .where(CaptureSession.id == session_id)
        .values(status=CaptureSessionStatus(terminal))
    )
    await db_session.flush()

    moved = await user_client.patch(
        f"/api/v1/capture-sessions/{session_id}", json={"status": "capturing"}
    )
    repeat = await user_client.patch(
        f"/api/v1/capture-sessions/{session_id}", json={"status": terminal}
    )

    assert moved.status_code == 400, moved.text
    assert repeat.status_code == 200, repeat.text
    assert repeat.json()["status"] == terminal
