"""
Tests for the Daytona sandbox tour generation service.

The sandbox SDK is faked entirely (no network, no real API key): we verify the
orchestration contract — upload agent + prompt + images, run the agent, read
back tour.json, destroy the sandbox and close the client even on failure.
"""
from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from app.config.settings import settings
from app.services.ai import AIProviderError
from app.services.tour_ai import daytona_service

VALID_PLAN = {
    "title": "Sunset Villa",
    "initial_scene_id": "living",
    "scenes": [
        {
            "id": "living",
            "image_key": "img_1",
            "room_type": "living_room",
            "title": "Living Room",
            "hotspots": [],
        },
        {
            "id": "kitchen",
            "image_key": "img_2",
            "room_type": "kitchen",
            "title": "Kitchen",
            "hotspots": [],
        },
    ],
}


class _FakeResponse:
    """Minimal httpx response stand-in for the shared client."""

    def __init__(self, *, text: str = "", status_code: int = 200) -> None:
        self.text = text
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise AssertionError(f"unexpected status {self.status_code}")


class _ExecResult:
    """Stand-in for the SDK ExecuteResponse (exit_code + result)."""

    def __init__(self, *, exit_code: int, result: str) -> None:
        self.exit_code = exit_code
        self.result = result


class _FakeProcess:
    def __init__(self, exec_result: Any) -> None:
        self._exec_result = exec_result
        self.exec = AsyncMock(return_value=exec_result)


class _FakeSandbox:
    def __init__(self, process: _FakeProcess) -> None:
        self.id = "sbx-test-1"
        self.process = process
        self.upload_url = AsyncMock(side_effect=lambda path: f"https://upload.invalid/{path}")
        self.download_url = AsyncMock(side_effect=lambda path: f"https://download.invalid/{path}")


class _FakeDaytona:
    def __init__(self, sandbox: _FakeSandbox) -> None:
        self.sandbox = sandbox
        self.created: list[Any] = []
        self.deleted: list[Any] = []
        self.closed = False
        self.create = AsyncMock(side_effect=self._create)
        self.delete = AsyncMock(side_effect=self._delete)
        self.close = AsyncMock(side_effect=self._close)

    async def _create(self, params: Any, timeout: float = 60) -> _FakeSandbox:
        self.created.append((params, timeout))
        return self.sandbox

    async def _delete(self, sandbox: Any, wait: bool = False) -> None:
        self.deleted.append(sandbox)

    async def _close(self) -> None:
        self.closed = True


class _FakeHttp:
    """Stand-in for the shared httpx client used for upload/download."""

    def __init__(self, plan: dict[str, Any] | None) -> None:
        self._plan = plan
        self.post = AsyncMock(return_value=_FakeResponse())
        self.get = AsyncMock(
            return_value=_FakeResponse(text=json.dumps(plan) if plan else "{}")
        )


@pytest.fixture
def sandbox_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "DAYTONA_API_KEY", "dtn_test_key")
    monkeypatch.setattr(settings, "DAYTONA_API_URL", "https://app.daytona.io/api")
    monkeypatch.setattr(settings, "DAYTONA_TARGET", "us")
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "test-gemini-key")
    monkeypatch.setattr(settings, "DAYTONA_AGENT_GEMINI_MODEL", "gemini-2.5-flash")


def _images() -> list[dict[str, Any]]:
    return [
        {"key": "img_1", "mime_type": "image/jpeg", "image_base64": "aGVsbG8=", "image_url": "https://cdn/x/1.jpg"},
        {"key": "img_2", "mime_type": "image/jpeg", "image_base64": "d29ybGQ=", "image_url": "https://cdn/x/2.jpg"},
    ]


@pytest.mark.asyncio
async def test_generate_tour_in_sandbox_happy_path(
    sandbox_settings: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    process = _FakeProcess(_ExecResult(exit_code=0, result="TOUR_PLAN_WRITTEN"))
    sandbox = _FakeSandbox(process)
    fake_daytona = _FakeDaytona(sandbox)
    fake_http = _FakeHttp(VALID_PLAN)

    with patch.object(daytona_service, "get_general_client", return_value=fake_http), \
            patch("daytona.AsyncDaytona", return_value=fake_daytona):
        plan = await daytona_service.generate_tour_in_sandbox(
            images_base64=_images(),
            title="Sunset Villa",
            description="A villa",
        )

    assert plan["initial_scene_id"] == "living"
    assert len(plan["scenes"]) == 2

    # Agent script, prompt, and images must all have been uploaded.
    assert len(fake_http.post.await_args_list) == 3

    # The agent ran inside the sandbox (exec #1 = mkdir, #2 = agent run).
    assert process.exec.await_count == 2
    agent_call = process.exec.await_args_list[1]
    assert "python3 /home/daytona/tourgen/agent.py" in agent_call.args[0]
    # The agent reads images.json/prompt.txt with relative paths, so the run
    # must cd into the upload workdir first.
    assert agent_call.args[0].startswith("cd /home/daytona/tourgen &&")

    # Output was read back from tour.json and the plan was parsed.
    assert fake_http.get.await_count == 1

    # Sandbox destroyed and client closed — no leaks.
    assert fake_daytona.deleted == [sandbox]
    assert fake_daytona.closed is True

    # Create params carry the TTL backstop and sandbox-only env.
    created_params = fake_daytona.created[0][0]
    assert created_params.image == "python:3.11"
    assert created_params.env_vars["GEMINI_API_KEY"] == "test-gemini-key"
    assert created_params.ephemeral is True
    assert created_params.ttl_minutes >= 1


@pytest.mark.asyncio
async def test_generate_tour_in_sandbox_missing_key_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "DAYTONA_API_KEY", None)
    with pytest.raises(AIProviderError, match="DAYTONA_API_KEY is missing"):
        await daytona_service.generate_tour_in_sandbox(images_base64=_images())


@pytest.mark.asyncio
async def test_generate_tour_in_sandbox_agent_failure_cleans_up(
    sandbox_settings: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    process = _FakeProcess(_ExecResult(exit_code=1, result="boom"))
    sandbox = _FakeSandbox(process)
    fake_daytona = _FakeDaytona(sandbox)
    fake_http = _FakeHttp(VALID_PLAN)

    with patch.object(daytona_service, "get_general_client", return_value=fake_http), \
            patch("daytona.AsyncDaytona", return_value=fake_daytona):
        with pytest.raises(AIProviderError, match="agent failed"):
            await daytona_service.generate_tour_in_sandbox(images_base64=_images())

    # Even on failure the sandbox is destroyed and the client closed.
    assert fake_daytona.deleted == [sandbox]
    assert fake_daytona.closed is True


@pytest.mark.asyncio
async def test_generate_tour_in_sandbox_invalid_plan_raises(
    sandbox_settings: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    process = _FakeProcess(_ExecResult(exit_code=0, result="done"))
    sandbox = _FakeSandbox(process)
    fake_daytona = _FakeDaytona(sandbox)
    fake_http = _FakeHttp({"title": "no scenes"})

    with patch.object(daytona_service, "get_general_client", return_value=fake_http), \
            patch("daytona.AsyncDaytona", return_value=fake_daytona):
        with pytest.raises(AIProviderError, match="no usable scenes"):
            await daytona_service.generate_tour_in_sandbox(images_base64=_images())

    assert fake_daytona.deleted == [sandbox]
    assert fake_daytona.closed is True
