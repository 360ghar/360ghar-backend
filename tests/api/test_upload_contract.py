"""Upload routes: folder types per route, document access, presign type, single delete.

Storage is mocked at the Cloudinary boundary. The database is real.
"""

from __future__ import annotations

import uuid
from io import BytesIO
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tours import MediaFile
from app.services.storage.service import StorageService

pytestmark = pytest.mark.asyncio

UPLOAD = "/api/v1/upload/"
BATCH = "/api/v1/upload/batch"
PRESIGN = "/api/v1/upload/presigned"
JPEG = b"\xff\xd8\xff\xe0" + b"0" * 64
PDF = b"%PDF-1.4\n" + b"0" * 64
PDF_URL = "https://res.cloudinary.com/c/raw/authenticated/v1/360ghar/documents/general/a.pdf"
NEEDS_IDS = ["property_image", "property_video", "property_document", "scene"]
ACCEPTED = ["avatar", "document_lease", "document_maintenance", "document_general", "generic"]


def _stored(public_id: str, *, resource_type: str, url: str) -> dict:
    return {
        "public_id": public_id,
        "secure_url": url,
        "bytes": len(PDF),
        "width": None,
        "height": None,
        "resource_type": resource_type,
    }


def _cloud_for_upload(result: dict) -> MagicMock:
    cloud = MagicMock()
    cloud.upload_file.return_value = result
    cloud.extract_public_id_from_url.return_value = None
    return cloud


@pytest.mark.parametrize("folder_type", NEEDS_IDS)
async def test_upload_rejects_folder_types_that_need_a_property_or_scene(
    authenticated_client: AsyncClient, folder_type: str
):
    with patch("app.api.api_v1.endpoints.upload.storage_service") as storage:
        storage.upload_and_track = AsyncMock()
        response = await authenticated_client.post(
            UPLOAD,
            data={"folder_type": folder_type},
            files={"file": ("a.jpg", BytesIO(JPEG), "image/jpeg")},
        )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "FOLDER_TYPE_NOT_ALLOWED"
    storage.upload_and_track.assert_not_awaited()


@pytest.mark.parametrize("folder_type", NEEDS_IDS)
async def test_batch_rejects_folder_types_that_need_a_property_or_scene(
    authenticated_client: AsyncClient, folder_type: str
):
    with patch("app.api.api_v1.endpoints.upload.storage_service") as storage:
        storage.upload_batch = AsyncMock()
        response = await authenticated_client.post(
            BATCH,
            data={"folder_type": folder_type},
            files=[("files", ("a.jpg", BytesIO(JPEG), "image/jpeg"))],
        )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "FOLDER_TYPE_NOT_ALLOWED"
    storage.upload_batch.assert_not_awaited()


@pytest.mark.parametrize("folder_type", ["tour_thumbnail", "tour_original"])
async def test_tour_folder_without_tour_id_is_422(
    authenticated_client: AsyncClient, folder_type: str
):
    with patch("app.api.api_v1.endpoints.upload.storage_service") as storage:
        storage.upload_and_track = AsyncMock()
        response = await authenticated_client.post(
            UPLOAD,
            data={"folder_type": folder_type},
            files={"file": ("a.jpg", BytesIO(JPEG), "image/jpeg")},
        )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "TOUR_ID_REQUIRED"
    storage.upload_and_track.assert_not_awaited()


@pytest.mark.parametrize("folder_type", ACCEPTED)
async def test_upload_accepts_each_folder_type_without_a_property_or_scene(
    authenticated_client: AsyncClient, folder_type: str
):
    stored = {
        "file_path": "360ghar/uploads/1/a.jpg",
        "public_url": "https://res.example/a.jpg",
        "file_type": "generic_upload",
        "file_size": 68,
        "content_type": "image/jpeg",
        "original_filename": "a.jpg",
        "media": None,
    }
    with patch("app.api.api_v1.endpoints.upload.storage_service") as storage:
        storage.upload_and_track = AsyncMock(return_value=stored)
        response = await authenticated_client.post(
            UPLOAD,
            data={"folder_type": folder_type},
            files={"file": ("a.jpg", BytesIO(JPEG), "image/jpeg")},
        )
    assert response.status_code == 201, response.text
    assert storage.upload_and_track.await_count == 1


@pytest.mark.parametrize("folder_type", ["tour_thumbnail", "tour_original"])
async def test_tour_folder_with_tour_id_is_accepted(
    authenticated_client: AsyncClient, folder_type: str
):
    stored = {
        "file_path": "360ghar/tours/t1/originals/a.jpg",
        "public_url": "https://res.example/a.jpg",
        "file_type": "tour_original",
        "file_size": 68,
        "content_type": "image/jpeg",
        "original_filename": "a.jpg",
        "media": None,
    }
    with (
        patch("app.api.api_v1.endpoints.upload.assert_upload_targets", AsyncMock()),
        patch("app.api.api_v1.endpoints.upload.storage_service") as storage,
    ):
        storage.upload_and_track = AsyncMock(return_value=stored)
        response = await authenticated_client.post(
            UPLOAD,
            data={"folder_type": folder_type, "tour_id": "t1"},
            files={"file": ("a.jpg", BytesIO(JPEG), "image/jpeg")},
        )
    assert response.status_code == 201, response.text


async def test_document_upload_is_stored_authenticated(authenticated_client: AsyncClient):
    cloud = _cloud_for_upload(
        _stored("360ghar/documents/general/a.pdf", resource_type="raw", url=PDF_URL)
    )
    with patch.object(StorageService, "cloudinary", new_callable=PropertyMock, return_value=cloud):
        response = await authenticated_client.post(
            UPLOAD,
            data={"folder_type": "document_general"},
            files={"file": ("a.pdf", BytesIO(PDF), "application/pdf")},
        )
    assert response.status_code == 201, response.text
    assert cloud.upload_file.call_args.kwargs["type"] == "authenticated"


async def test_batch_document_upload_is_stored_authenticated(authenticated_client: AsyncClient):
    cloud = _cloud_for_upload(
        _stored("360ghar/documents/leases/a.pdf", resource_type="raw", url=PDF_URL)
    )
    with patch.object(StorageService, "cloudinary", new_callable=PropertyMock, return_value=cloud):
        response = await authenticated_client.post(
            BATCH,
            data={"folder_type": "document_lease"},
            files=[("files", ("a.pdf", BytesIO(PDF), "application/pdf"))],
        )
    assert response.status_code == 201, response.text
    item = response.json()["items"][0]
    assert item["status"] == "uploaded"
    assert cloud.upload_file.call_args.kwargs["type"] == "authenticated"


async def test_presigned_document_returns_the_authenticated_type(authenticated_client: AsyncClient):
    cloud = MagicMock()
    cloud.generate_signed_upload_params.side_effect = lambda **kw: {
        "upload_url": "https://api.example/upload",
        "api_key": "key",
        "signature": "sig",
        "timestamp": 1700000000,
        "public_id": kw["public_id"],
        "type": kw.get("delivery_type") if kw.get("delivery_type") != "upload" else None,
    }
    cloud.get_url.return_value = PDF_URL
    with patch.object(StorageService, "cloudinary", new_callable=PropertyMock, return_value=cloud):
        response = await authenticated_client.post(
            PRESIGN,
            json={
                "files": [
                    {
                        "filename": "lease.pdf",
                        "content_type": "application/pdf",
                        "file_size": 68,
                        "folder_type": "document_lease",
                    }
                ]
            },
        )
    assert response.status_code == 201, response.text
    assert response.json()["items"][0]["type"] == "authenticated"
    assert cloud.generate_signed_upload_params.call_args.kwargs["delivery_type"] == "authenticated"


async def test_presigned_image_sends_no_type(authenticated_client: AsyncClient):
    cloud = MagicMock()
    cloud.generate_signed_upload_params.side_effect = lambda **kw: {
        "upload_url": "https://api.example/upload",
        "api_key": "key",
        "signature": "sig",
        "timestamp": 1700000000,
        "public_id": kw["public_id"],
        "type": None,
    }
    cloud.get_url.return_value = "https://res.example/a.jpg"
    with patch.object(StorageService, "cloudinary", new_callable=PropertyMock, return_value=cloud):
        response = await authenticated_client.post(
            PRESIGN,
            json={
                "files": [
                    {
                        "filename": "tour.jpg",
                        "content_type": "image/jpeg",
                        "file_size": 68,
                        "folder_type": "generic",
                    }
                ]
            },
        )
    assert response.status_code == 201, response.text
    assert response.json()["items"][0]["type"] is None


async def test_single_delete_keeps_the_row_when_storage_fails(
    authenticated_client: AsyncClient, db_session: AsyncSession, test_user
):
    media = MediaFile(
        id=str(uuid.uuid4()),
        user_id=test_user.id,
        filename="a.jpg",
        original_filename="a.jpg",
        file_url="https://res.cloudinary.com/c/image/upload/v1/360ghar/a.jpg",
        file_size=10,
        mime_type="image/jpeg",
        folder="360ghar",
        visibility="private",
        is_processed=False,
        upload_status="complete",
        bucket_name="cloudinary",
        storage_path="360ghar/a.jpg",
    )
    db_session.add(media)
    await db_session.flush()
    with patch("app.api.api_v1.endpoints.upload.storage_service.delete_file", return_value=False):
        response = await authenticated_client.delete(f"/api/v1/upload/media/{media.id}")
    assert response.status_code == 503
    assert response.headers["Retry-After"] == "30"
    assert response.json()["error"]["code"] == "STORAGE_DELETE_FAILED"
    assert await db_session.get(MediaFile, media.id) is not None


async def test_single_delete_removes_an_authenticated_document_with_its_type(
    authenticated_client: AsyncClient, db_session: AsyncSession, test_user
):
    media = MediaFile(
        id=str(uuid.uuid4()),
        user_id=test_user.id,
        filename="a.pdf",
        original_filename="a.pdf",
        file_url=PDF_URL,
        file_size=len(PDF),
        mime_type="application/pdf",
        folder="360ghar/documents/general",
        visibility="private",
        is_processed=False,
        upload_status="complete",
        bucket_name="cloudinary",
        storage_path="360ghar/documents/general/a.pdf",
    )
    db_session.add(media)
    await db_session.flush()
    cloud = MagicMock()
    cloud.extract_public_id_from_url.return_value = None
    cloud.delete_file.return_value = True
    with patch.object(StorageService, "cloudinary", new_callable=PropertyMock, return_value=cloud):
        response = await authenticated_client.delete(f"/api/v1/upload/media/{media.id}")
    assert response.status_code == 204, response.text
    cloud.delete_file.assert_called_once_with(
        "360ghar/documents/general/a.pdf", resource_type="raw", delivery_type="authenticated"
    )
