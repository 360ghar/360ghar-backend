"""Tests for the media bulk-delete endpoint (POST /api/v1/upload/media/batch-delete)."""

from __future__ import annotations

import uuid
from unittest.mock import patch

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tours import MediaFile
from tests.fixtures.factories import UserFactory

pytestmark = pytest.mark.asyncio


async def _make_media(db: AsyncSession, user_id: int, count: int = 1) -> list[MediaFile]:
    media_list: list[MediaFile] = []
    for _ in range(count):
        media = MediaFile(
            id=str(uuid.uuid4()),
            user_id=user_id,
            filename="test.jpg",
            original_filename="test.jpg",
            file_url="https://res.cloudinary.com/example/image/upload/v1/test.jpg",
            file_size=1024,
            mime_type="image/jpeg",
            folder="uploads",
            visibility="private",
            is_processed=False,
            upload_status="complete",
            bucket_name="cloudinary",
            storage_path="uploads/test.jpg",
        )
        db.add(media)
        media_list.append(media)
    await db.flush()
    return media_list


@pytest_asyncio.fixture
async def owned_media(db_session: AsyncSession, test_user):
    return await _make_media(db_session, test_user.id, count=2)


@patch("app.api.api_v1.endpoints.upload.storage_service.delete_file", return_value=True)
async def test_batch_delete_deletes_owned_media(
    _mock_delete,
    authenticated_client: AsyncClient,
    owned_media,
):
    ids = [m.id for m in owned_media]
    response = await authenticated_client.post(
        "/api/v1/upload/media/batch-delete",
        json={"media_ids": ids},
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert set(data["deleted"]) == set(ids)
    assert data["failed"] == []


@patch("app.api.api_v1.endpoints.upload.storage_service.delete_file", return_value=True)
async def test_batch_delete_rejects_media_owned_by_others(
    _mock_delete,
    db_session: AsyncSession,
    authenticated_client: AsyncClient,
    test_user,
):
    # Media owned by a different user.
    other = await UserFactory.create(db_session)
    others_media = await _make_media(db_session, other.id, count=1)

    response = await authenticated_client.post(
        "/api/v1/upload/media/batch-delete",
        json={"media_ids": [others_media[0].id]},
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["deleted"] == []
    assert others_media[0].id in data["failed"]


async def test_batch_delete_rejects_empty_list(authenticated_client: AsyncClient):
    response = await authenticated_client.post(
        "/api/v1/upload/media/batch-delete",
        json={"media_ids": []},
    )
    assert response.status_code == 422, response.text


async def test_batch_delete_caps_at_fifty(authenticated_client: AsyncClient):
    ids = [str(uuid.uuid4()) for _ in range(51)]
    response = await authenticated_client.post(
        "/api/v1/upload/media/batch-delete",
        json={"media_ids": ids},
    )
    assert response.status_code == 422, response.text


@patch("app.api.api_v1.endpoints.upload.storage_service.delete_file", return_value=True)
async def test_batch_delete_unauthorized(
    _mock_delete,
    client: AsyncClient,
):
    response = await client.post(
        "/api/v1/upload/media/batch-delete",
        json={"media_ids": ["abc"]},
    )
    assert response.status_code == 401


@patch("app.api.api_v1.endpoints.upload.storage_service.delete_file", return_value=True)
async def test_batch_delete_partial_success(
    _mock_delete,
    db_session: AsyncSession,
    authenticated_client: AsyncClient,
    test_user,
):
    owned = await _make_media(db_session, test_user.id, count=1)
    other = await UserFactory.create(db_session)
    others = await _make_media(db_session, other.id, count=1)

    response = await authenticated_client.post(
        "/api/v1/upload/media/batch-delete",
        json={"media_ids": [owned[0].id, others[0].id]},
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["deleted"] == [owned[0].id]
    assert data["failed"] == [others[0].id]
