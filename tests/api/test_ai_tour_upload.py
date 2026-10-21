"""POST /api/v1/ai/tours/generate: the image upload path uses the real upload_batch shape.

Cloudinary is mocked at the SDK boundary. upload_batch runs for real, so the
route reads the same {index, filename, status, result, error} items that
production returns.
"""

from __future__ import annotations

from datetime import UTC, datetime
from io import BytesIO
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.api_v1.dependencies.auth import get_current_active_user_short_session
from app.models.enums import AIJobStatus, AIJobType
from app.schemas.tour import AIJobBase
from app.schemas.user import SelfUser
from app.services.storage import storage_service

pytestmark = pytest.mark.asyncio

GENERATE = "/api/v1/ai/tours/generate"
JPEG = b"\xff\xd8\xff\xe0" + b"0" * 64
OK_URL_1 = "https://res.cloudinary.com/c/image/upload/v1/360ghar/uploads/1/a.webp"
OK_URL_2 = "https://res.cloudinary.com/c/image/upload/v1/360ghar/uploads/1/c.webp"


def _stored(public_id: str, url: str) -> dict:
    return {
        "public_id": public_id,
        "secure_url": url,
        "bytes": len(JPEG),
        "width": 4096,
        "height": 2048,
        "resource_type": "image",
    }


@pytest.fixture
async def ai_client(test_app, test_user):
    user_schema = SelfUser.model_validate(test_user, from_attributes=True)

    async def _override():
        return user_schema

    test_app.dependency_overrides[get_current_active_user_short_session] = _override
    try:
        async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as c:
            yield c
    finally:
        test_app.dependency_overrides.pop(get_current_active_user_short_session, None)


def _job() -> AIJobBase:
    return AIJobBase(
        id="job-1",
        job_type=AIJobType.analyze_scene,
        status=AIJobStatus.pending,
        progress=0,
        created_at=datetime.now(UTC),
    )


def _session_factory() -> MagicMock:
    session = MagicMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    return MagicMock(return_value=session)


async def test_generate_tour_passes_stored_urls_from_real_upload_batch(ai_client: AsyncClient):
    cloud = MagicMock()
    cloud.upload_file.side_effect = [
        _stored("360ghar/uploads/1/a", OK_URL_1),
        _stored("360ghar/uploads/1/c", OK_URL_2),
    ]
    tour = MagicMock(id="tour-1")
    generate = AsyncMock(return_value=(_job(), tour, ["scene-1", "scene-2"]))

    with (
        patch.object(storage_service, "_cloudinary", cloud),
        patch("app.api.api_v1.endpoints.ai.get_bg_session_factory", _session_factory()),
        patch("app.api.api_v1.endpoints.ai.tour_ai.generate_tour", generate),
    ):
        response = await ai_client.post(
            GENERATE,
            data={"title": "Flat"},
            files=[
                ("images", ("a.jpg", BytesIO(JPEG), "image/jpeg")),
                ("images", ("c.jpg", BytesIO(JPEG), "image/jpeg")),
            ],
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["tour_id"] == "tour-1"
    assert body["scene_ids"] == ["scene-1", "scene-2"]
    payload = generate.await_args.kwargs["data"]
    assert payload.image_urls == [OK_URL_1, OK_URL_2]
    assert cloud.upload_file.call_count == 2


async def test_generate_tour_skips_failed_files_and_keeps_uploaded_ones(ai_client: AsyncClient):
    cloud = MagicMock()
    cloud.upload_file.side_effect = [
        RuntimeError("cloudinary down"),
        _stored("360ghar/uploads/1/c", OK_URL_2),
    ]
    tour = MagicMock(id="tour-2")
    generate = AsyncMock(return_value=(_job(), tour, ["scene-9"]))

    with (
        patch.object(storage_service, "_cloudinary", cloud),
        patch("app.api.api_v1.endpoints.ai.get_bg_session_factory", _session_factory()),
        patch("app.api.api_v1.endpoints.ai.tour_ai.generate_tour", generate),
    ):
        response = await ai_client.post(
            GENERATE,
            files=[
                ("images", ("a.jpg", BytesIO(JPEG), "image/jpeg")),
                ("images", ("c.jpg", BytesIO(JPEG), "image/jpeg")),
            ],
        )

    assert response.status_code == 200, response.text
    payload = generate.await_args.kwargs["data"]
    assert payload.image_urls == [OK_URL_2]


async def test_generate_tour_returns_500_when_every_file_fails(ai_client: AsyncClient):
    cloud = MagicMock()
    cloud.upload_file.side_effect = RuntimeError("cloudinary down")
    generate = AsyncMock()

    with (
        patch.object(storage_service, "_cloudinary", cloud),
        patch("app.api.api_v1.endpoints.ai.get_bg_session_factory", _session_factory()),
        patch("app.api.api_v1.endpoints.ai.tour_ai.generate_tour", generate),
    ):
        response = await ai_client.post(
            GENERATE,
            files=[("images", ("a.jpg", BytesIO(JPEG), "image/jpeg"))],
        )

    assert response.status_code == 500
    assert "error" in response.json()
    generate.assert_not_awaited()
