"""Upload contract: folder vocabulary, response shape, PATCH semantics, batch and confirm rules.

No database and no Cloudinary network calls. Cloudinary and the session are mocks.
"""

from __future__ import annotations

from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

import pytest
from fastapi import HTTPException, UploadFile
from pydantic import ValidationError
from starlette.datastructures import Headers

from app.core.exceptions import BadRequestException, FileTooLargeException, StorageException
from app.schemas.storage import MediaFileResponse, MediaUpdateRequest, StorageFolderType
from app.services.cloudinary.service import CloudinaryService
from app.services.storage.service import StorageService
from app.services.storage_paths import StorageFolder, generate_cloudinary_public_id

JPEG = b"\xff\xd8\xff\xe0" + b"0" * 64


def _upload(content: bytes, content_type: str, filename: str) -> UploadFile:
    return UploadFile(
        file=BytesIO(content),
        filename=filename,
        headers=Headers({"content-type": content_type}),
    )


# ---------------------------------------------------------------------------
# Folder vocabulary and paths
# ---------------------------------------------------------------------------


def test_tour_originals_have_their_own_folder():
    path = generate_cloudinary_public_id(
        StorageFolder.TOUR_ORIGINAL, original_filename="pano.jpg", tour_id="t1"
    )
    assert path.startswith("tours/t1/originals/")


def test_legacy_tour_folder_value_is_rejected():
    with pytest.raises(ValueError):
        StorageFolderType("tour")
    assert StorageFolderType("tour_thumbnail") is StorageFolderType.TOUR_THUMBNAIL
    assert StorageFolderType("tour_original") is StorageFolderType.TOUR_ORIGINAL


# ---------------------------------------------------------------------------
# Response and PATCH shape
# ---------------------------------------------------------------------------


def test_media_response_hides_storage_internals():
    assert "storage_path" not in MediaFileResponse.model_fields
    assert "bucket_name" not in MediaFileResponse.model_fields


def test_media_patch_null_clears_nullable_field():
    body = MediaUpdateRequest.model_validate({"thumbnail_url": None})
    assert body.thumbnail_url is None
    assert "thumbnail_url" in body.model_fields_set


def test_media_patch_null_on_not_null_field_is_422():
    with pytest.raises(ValidationError):
        MediaUpdateRequest.model_validate({"visibility": None})


def test_media_patch_rejects_non_http_urls():
    with pytest.raises(ValidationError):
        MediaUpdateRequest.model_validate({"cdn_url": "javascript:alert(1)"})
    assert MediaUpdateRequest.model_validate({"cdn_url": "https://cdn.example.com/a.jpg"}).cdn_url


def test_private_delivery_url_is_signed_and_authenticated():
    svc = CloudinaryService.__new__(CloudinaryService)
    svc._url = MagicMock(return_value=("https://res.example/signed", {}))

    url = svc.private_delivery_url("360ghar/documents/general/a.pdf", resource_type="raw")

    assert url == "https://res.example/signed"
    kwargs = svc._url.call_args.kwargs
    assert kwargs["type"] == "authenticated"
    assert kwargs["sign_url"] is True
    assert kwargs["resource_type"] == "raw"


def test_public_url_uses_the_asset_resource_type():
    svc = CloudinaryService.__new__(CloudinaryService)
    svc._url = MagicMock(return_value=("https://res.example/x", {}))
    svc.get_url("360ghar/a.pdf", resource_type="raw")
    assert svc._url.call_args.kwargs["resource_type"] == "raw"


# ---------------------------------------------------------------------------
# Batch: validate first, one result per file
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_batch_rejects_whole_batch_before_any_cloudinary_call():
    service = StorageService()
    files = [
        _upload(JPEG, "image/jpeg", "ok.jpg"),
        _upload(b"MZ-binary", "application/x-msdownload", "bad.exe"),
    ]
    with patch.object(service, "upload_with_path", new_callable=AsyncMock) as mock_upload:
        with pytest.raises(HTTPException) as exc_info:
            await service.upload_batch(files, db=None, user_id=1)

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail["code"] == "INVALID_FILE"
    assert exc_info.value.detail["files"][0]["index"] == 1
    mock_upload.assert_not_awaited()


@pytest.mark.asyncio
async def test_batch_reports_one_result_per_file():
    service = StorageService()
    files = [_upload(JPEG, "image/jpeg", "a.jpg"), _upload(JPEG, "image/jpeg", "b.jpg")]
    ok = {
        "file_path": "360ghar/uploads/1/a.jpg",
        "public_url": "https://res.example/a.jpg",
        "file_type": "generic_upload",
        "file_size": 68,
        "content_type": "image/jpeg",
        "original_filename": "a.jpg",
        "media": None,
    }
    with patch.object(
        service,
        "upload_with_path",
        new_callable=AsyncMock,
        side_effect=[ok, StorageException(detail="Cloudinary upload failed")],
    ):
        results = await service.upload_batch(files, db=None, user_id=1)

    assert [r["status"] for r in results] == ["uploaded", "failed"]
    assert [r["index"] for r in results] == [0, 1]
    assert results[1]["error"]["code"] == "STORAGE_ERROR"


# ---------------------------------------------------------------------------
# Confirm: idempotent, size-checked, failed status survives the request
# ---------------------------------------------------------------------------


def _db_returning(media) -> MagicMock:
    db = MagicMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = media
    db.execute = AsyncMock(return_value=result)
    db.flush = AsyncMock()
    db.refresh = AsyncMock()
    db.commit = AsyncMock()
    return db


@pytest.mark.asyncio
async def test_confirm_is_idempotent_for_complete_upload():
    media = SimpleNamespace(upload_status="complete", storage_path="x", file_url="u", file_size=10)
    service = StorageService()
    service._cloudinary = MagicMock()

    result = await service.confirm_upload(db=_db_returning(media), upload_id="m1", user_id=1)

    assert result is media
    service._cloudinary.get_file_info.assert_not_called()


@pytest.mark.asyncio
async def test_confirm_size_mismatch_fails_and_commits_the_failure():
    media = SimpleNamespace(
        upload_status="pending",
        storage_path="360ghar/x.jpg",
        file_url="u",
        file_size=100,
        mime_type="image/jpeg",
        width=None,
        height=None,
        is_processed=False,
    )
    db = _db_returning(media)
    service = StorageService()
    service._cloudinary = MagicMock()
    service._cloudinary.get_file_info.return_value = {"bytes": 50, "width": 10, "height": 10}

    with pytest.raises(BadRequestException) as exc_info:
        await service.confirm_upload(db=db, upload_id="m1", user_id=1)

    assert exc_info.value.error_code == "UPLOAD_SIZE_MISMATCH"
    assert media.upload_status == "failed"
    db.commit.assert_awaited()
    service._cloudinary.delete_file.assert_called_once_with(
        "360ghar/x.jpg", resource_type="image", delivery_type="upload"
    )


@pytest.mark.asyncio
async def test_confirm_stores_bytes_and_dimensions():
    media = SimpleNamespace(
        upload_status="pending",
        storage_path="360ghar/x.jpg",
        file_url="u",
        file_size=50,
        mime_type="image/jpeg",
        width=None,
        height=None,
        is_processed=True,
    )
    service = StorageService()
    service._cloudinary = MagicMock()
    service._cloudinary.get_file_info.return_value = {"bytes": 50, "width": 640, "height": 480}

    await service.confirm_upload(db=_db_returning(media), upload_id="m1", user_id=1)

    assert media.upload_status == "complete"
    assert (media.file_size, media.width, media.height) == (50, 640, 480)


# ---------------------------------------------------------------------------
# Batch delete reports storage failures
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_batch_delete_reports_storage_warning_when_object_not_removed():
    media = SimpleNamespace(
        id="m1",
        file_url=None,
        storage_path="360ghar/x.jpg",
        filename="x.jpg",
        folder=None,
        bucket_name="cloudinary",
    )
    db = MagicMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = [media]
    db.execute = AsyncMock(return_value=result)
    db.delete = AsyncMock()
    db.flush = AsyncMock()

    service = StorageService()
    with patch.object(service, "delete_file", return_value=False):
        outcome = await service.delete_batch(db, ["m1"], SimpleNamespace(id=1))

    # The storage object still exists, so the row is kept and the id is failed.
    assert outcome == {"deleted": [], "failed": ["m1"], "storage_warnings": ["m1"]}
    db.delete.assert_not_awaited()


# ---------------------------------------------------------------------------
# Batch limits and presign shape
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_batch_rejects_total_size_over_the_batch_limit(monkeypatch):
    import app.services.storage.service as storage_module

    monkeypatch.setattr(storage_module, "MAX_BATCH_UPLOAD_TOTAL_BYTES", 100)
    service = StorageService()
    files = [_upload(JPEG, "image/jpeg", "a.jpg"), _upload(JPEG, "image/jpeg", "b.jpg")]
    with patch.object(service, "upload_with_path", new_callable=AsyncMock) as mock_upload:
        with pytest.raises(FileTooLargeException) as exc_info:
            await service.upload_batch(files, db=None, user_id=1)

    assert exc_info.value.status_code == 413
    assert exc_info.value.error_code == "BATCH_TOO_LARGE"
    mock_upload.assert_not_awaited()


def _presign_cloudinary() -> MagicMock:
    cloud = MagicMock()
    cloud._resource_type = CloudinaryService._resource_type
    cloud.generate_signed_upload_params.side_effect = (
        lambda *, public_id, folder=None, resource_type="auto", delivery_type="upload": {
            "upload_url": "https://api.example/upload",
            "api_key": "key",
            "signature": "sig",
            "timestamp": 1700000000,
            "public_id": f"{folder}/{public_id}" if folder else public_id,
            "type": delivery_type if delivery_type != "upload" else None,
        }
    )
    cloud.get_url.return_value = "https://res.example/asset"
    return cloud


async def _presign(filename: str, content_type: str, folder: StorageFolder) -> tuple[dict, str]:
    service = StorageService()
    cloud = _presign_cloudinary()
    media = SimpleNamespace(id="upload-1")
    with (
        patch.object(StorageService, "cloudinary", new_callable=PropertyMock, return_value=cloud),
        patch.object(service, "_create_media_record", new_callable=AsyncMock, return_value=media),
    ):
        result = await service.create_presigned_upload(
            filename=filename,
            content_type=content_type,
            file_size=68,
            user_id=1,
            db=MagicMock(),
            folder=folder,
            property_id=7,
            visibility="private",
        )
    return result, cloud.generate_signed_upload_params.call_args.kwargs["public_id"]


@pytest.mark.asyncio
async def test_presign_image_public_id_has_no_extension_and_returns_signature():
    result, signed_public_id = await _presign(
        "kitchen.jpg", "image/jpeg", StorageFolder.PROPERTY_IMAGE
    )

    assert not signed_public_id.endswith(".jpg")
    assert result["signature"] == "sig"
    assert result["api_key"] == "key"
    assert result["timestamp"] == 1700000000
    assert result["public_id"].endswith(signed_public_id)
    assert "token" not in result


@pytest.mark.asyncio
async def test_presign_raw_document_public_id_keeps_its_extension():
    _, signed_public_id = await _presign(
        "lease.pdf", "application/pdf", StorageFolder.PROPERTY_DOCUMENT
    )

    assert signed_public_id.endswith(".pdf")
