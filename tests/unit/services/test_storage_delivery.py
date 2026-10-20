"""Upload delivery: access from the folder, resource type from Cloudinary, typed delete and confirm.

No database and no Cloudinary network calls. The SDK handles are mocks.
"""

from __future__ import annotations

from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

import pytest
from fastapi import UploadFile
from starlette.datastructures import Headers

from app.core.exceptions import BadRequestException
from app.services.cloudinary.service import CloudinaryService, delivery_from_url, resource_type_for
from app.services.storage.service import StorageService
from app.services.storage_paths import StorageFolder, generate_cloudinary_public_id

PDF = b"%PDF-1.4\n" + b"0" * 64
JPEG = b"\xff\xd8\xff\xe0" + b"0" * 64
PDF_URL = "https://res.cloudinary.com/c/raw/authenticated/v1/360ghar/documents/general/a.pdf"


def _upload(content: bytes, content_type: str, filename: str) -> UploadFile:
    return UploadFile(
        file=BytesIO(content), filename=filename, headers=Headers({"content-type": content_type})
    )


def _cloud() -> CloudinaryService:
    svc = CloudinaryService.__new__(CloudinaryService)
    svc.root = "360ghar"
    svc._uploader = MagicMock()
    svc._api = MagicMock()
    svc._url = MagicMock(return_value=("https://res.example/x", {}))
    return svc


def _db_returning(obj):
    result = MagicMock()
    result.scalar_one_or_none.return_value = obj
    db = AsyncMock()
    db.execute = AsyncMock(return_value=result)
    return db


# --- Cloudinary service: what it sends and what it stores ----------------------------------


def test_pdf_upload_keeps_the_explicit_raw_resource_type():
    svc = _cloud()
    svc._uploader.upload.return_value = {
        "public_id": "360ghar/documents/general/a.pdf",
        "secure_url": PDF_URL,
        "bytes": 10,
        "resource_type": "raw",
    }
    result = svc.upload_file(
        PDF,
        public_id="a.pdf",
        folder="documents/general",
        content_type="application/pdf",
        type="authenticated",
    )
    kwargs = svc._uploader.upload.call_args.kwargs
    assert kwargs["resource_type"] == "raw"
    assert kwargs["type"] == "authenticated"
    assert "fetch_format" not in kwargs
    assert result["resource_type"] == "raw"


def test_delete_sends_the_stored_resource_and_delivery_type():
    svc = _cloud()
    svc._api.delete_resources.return_value = {"deleted": {"360ghar/a.pdf": "deleted"}}
    assert svc.delete_file("360ghar/a.pdf", resource_type="raw", delivery_type="authenticated")
    svc._api.delete_resources.assert_called_once_with(
        ["360ghar/a.pdf"], resource_type="raw", type="authenticated"
    )


def test_delete_treats_an_already_absent_asset_as_removed():
    svc = _cloud()
    svc._api.delete_resources.return_value = {"deleted": {"360ghar/a.jpg": "not_found"}}
    assert svc.delete_file("360ghar/a.jpg") is True


def test_delete_reports_a_removal_that_did_not_happen():
    svc = _cloud()
    svc._api.delete_resources.return_value = {"deleted": {}}
    assert svc.delete_file("360ghar/a.jpg") is False


def test_signed_params_cover_the_delivery_type():
    svc = _cloud()
    with patch("time.time", return_value=1700000000):
        upload = svc.generate_signed_upload_params(
            public_id="a", folder="documents/general", resource_type="raw"
        )
        auth = svc.generate_signed_upload_params(
            public_id="a",
            folder="documents/general",
            resource_type="raw",
            delivery_type="authenticated",
        )
    assert upload["type"] is None
    assert auth["type"] == "authenticated"
    assert upload["signature"] != auth["signature"]


def test_stored_url_names_the_resource_and_delivery_type():
    assert delivery_from_url(PDF_URL) == ("raw", "authenticated")
    assert delivery_from_url("https://res.cloudinary.com/c/image/upload/v1/a.jpg") == (
        "image",
        "upload",
    )
    assert delivery_from_url("https://cdn.example.com/a.jpg") is None
    assert resource_type_for("application/pdf") == "raw"
    assert resource_type_for("video/mp4") == "video"


# --- Public id builder ---------------------------------------------------------------------


def test_public_id_drops_the_extension_only_for_images_and_videos():
    image = generate_cloudinary_public_id(
        StorageFolder.PROPERTY_IMAGE,
        original_filename="a.jpg",
        property_id=1,
        resource_type="image",
    )
    video = generate_cloudinary_public_id(
        StorageFolder.PROPERTY_VIDEO,
        original_filename="a.mp4",
        property_id=1,
        resource_type="video",
    )
    raw = generate_cloudinary_public_id(
        StorageFolder.DOCUMENT_GENERAL, original_filename="a.pdf", resource_type="raw"
    )
    assert "." not in image.rsplit("/", 1)[-1]
    assert "." not in video.rsplit("/", 1)[-1]
    assert raw.endswith(".pdf")


# --- Upload path: access follows the folder ------------------------------------------------


@pytest.mark.asyncio
async def test_document_folder_upload_is_stored_authenticated():
    service = StorageService()
    service._cloudinary = MagicMock()
    service._cloudinary.upload_file.return_value = {
        "public_id": "360ghar/documents/general/a.pdf",
        "secure_url": PDF_URL,
        "bytes": len(PDF),
        "width": None,
        "height": None,
        "resource_type": "raw",
    }
    await service.upload_with_path(
        _upload(PDF, "application/pdf", "a.pdf"),
        user_id=1,
        folder=StorageFolder.DOCUMENT_GENERAL,
        db=None,
    )
    assert service._cloudinary.upload_file.call_args.kwargs["type"] == "authenticated"


@pytest.mark.asyncio
async def test_public_folder_upload_sends_no_type_and_no_image_extension():
    service = StorageService()
    service._cloudinary = MagicMock()
    service._cloudinary.upload_file.return_value = {
        "public_id": "360ghar/properties/7/x",
        "secure_url": "https://res.example/x",
        "bytes": 68,
        "width": 1,
        "height": 1,
        "resource_type": "image",
    }
    await service.upload_with_path(
        _upload(JPEG, "image/jpeg", "kitchen.jpg"),
        user_id=1,
        folder=StorageFolder.PROPERTY_IMAGE,
        db=None,
        property_id=7,
    )
    kwargs = service._cloudinary.upload_file.call_args.kwargs
    assert "type" not in kwargs
    assert "." not in kwargs["public_id"]


@pytest.mark.asyncio
async def test_private_non_document_upload_keeps_upload_delivery_until_lead_decides():
    """Deferred (decisions.md, "Private delivery for non-document folders"). visibility
    private does not change delivery for these folders yet. /upload defaults to private,
    and the public tour and property viewers read these URLs. When the lead picks
    authenticated delivery, this test flips to assert type == "authenticated"."""
    service = StorageService()
    service._cloudinary = MagicMock()
    service._cloudinary.upload_file.return_value = {
        "public_id": "360ghar/uploads/1/x",
        "secure_url": "https://res.example/x",
        "bytes": 68,
        "width": 1,
        "height": 1,
        "resource_type": "image",
    }
    await service.upload_with_path(
        _upload(JPEG, "image/jpeg", "room.jpg"),
        user_id=1,
        folder=StorageFolder.GENERIC_UPLOAD,
        db=None,
        visibility="private",
    )
    assert "type" not in service._cloudinary.upload_file.call_args.kwargs


@pytest.mark.asyncio
async def test_presign_document_signs_the_authenticated_type():
    service = StorageService()
    cloud = MagicMock()
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
    cloud.get_url.return_value = "https://res.example/a"
    with (
        patch.object(StorageService, "cloudinary", new_callable=PropertyMock, return_value=cloud),
        patch.object(
            service,
            "_create_media_record",
            new_callable=AsyncMock,
            return_value=SimpleNamespace(id="u1"),
        ),
    ):
        result = await service.create_presigned_upload(
            filename="lease.pdf",
            content_type="application/pdf",
            file_size=68,
            user_id=1,
            db=MagicMock(),
            folder=StorageFolder.DOCUMENT_LEASE,
        )
    assert cloud.generate_signed_upload_params.call_args.kwargs["delivery_type"] == "authenticated"
    assert cloud.get_url.call_args.kwargs["delivery_type"] == "authenticated"
    assert result["type"] == "authenticated"


# --- Delete and confirm use the stored delivery --------------------------------------------


def test_row_delivery_kwargs_come_from_the_stored_url():
    row = SimpleNamespace(file_url=PDF_URL, mime_type="application/pdf")
    assert StorageService().delivery_kwargs(row) == {
        "resource_type": "raw",
        "delivery_type": "authenticated",
    }


@pytest.mark.asyncio
async def test_batch_delete_removes_an_authenticated_document_with_its_type():
    service = StorageService()
    service._cloudinary = _cloud()
    service._cloudinary._api.delete_resources.return_value = {
        "deleted": {"360ghar/documents/general/a.pdf": "deleted"}
    }
    doc = SimpleNamespace(
        id="d1",
        file_url=PDF_URL,
        storage_path="360ghar/documents/general/a.pdf",
        filename="a.pdf",
        folder="360ghar/documents/general",
        bucket_name="cloudinary",
        mime_type="application/pdf",
    )
    result_proxy = MagicMock()
    result_proxy.scalars.return_value.all.return_value = [doc]
    db = AsyncMock()
    db.execute = AsyncMock(return_value=result_proxy)

    result = await service.delete_batch(db, media_ids=["d1"], actor=SimpleNamespace(id=1))

    assert result["storage_warnings"] == []
    service._cloudinary._api.delete_resources.assert_called_once_with(
        ["360ghar/documents/general/a.pdf"], resource_type="raw", type="authenticated"
    )


@pytest.mark.asyncio
async def test_confirm_looks_up_an_authenticated_document_with_its_type():
    media = SimpleNamespace(
        id="m1",
        user_id=1,
        upload_status="pending",
        storage_path="360ghar/documents/general/a.pdf",
        file_url=PDF_URL,
        file_size=3,
        mime_type="application/pdf",
        width=None,
        height=None,
        is_processed=False,
    )
    service = StorageService()
    service._cloudinary = MagicMock()
    service._cloudinary.get_file_info.return_value = {"bytes": 3}

    await service.confirm_upload(db=_db_returning(media), upload_id="m1", user_id=1)

    service._cloudinary.get_file_info.assert_called_once_with(
        "360ghar/documents/general/a.pdf", resource_type="raw", delivery_type="authenticated"
    )
    assert media.upload_status == "complete"


@pytest.mark.asyncio
async def test_confirm_checks_a_declared_size_of_zero():
    media = SimpleNamespace(
        id="m1",
        user_id=1,
        upload_status="pending",
        storage_path="360ghar/x.jpg",
        file_url="u",
        file_size=0,
        mime_type="image/jpeg",
        width=None,
        height=None,
        is_processed=False,
    )
    service = StorageService()
    service._cloudinary = MagicMock()
    service._cloudinary.get_file_info.return_value = {"bytes": 50}

    with pytest.raises(BadRequestException) as exc_info:
        await service.confirm_upload(db=_db_returning(media), upload_id="m1", user_id=1)

    assert exc_info.value.error_code == "UPLOAD_SIZE_MISMATCH"
    assert media.upload_status == "failed"
