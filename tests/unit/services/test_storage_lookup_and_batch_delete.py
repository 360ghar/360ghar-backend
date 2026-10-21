"""Cloudinary lookup errors vs misses on confirm, and batch delete that keeps rows on storage failure.

No database and no Cloudinary network calls. The SDK handles and the session are mocks.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from cloudinary.exceptions import GeneralError, NotFound

from app.core.exceptions import NotFoundException, ServiceUnavailableException
from app.services.cloudinary.service import CloudinaryService, StorageLookupError
from app.services.storage.service import StorageService

PDF_URL = "https://res.cloudinary.com/c/raw/authenticated/v1/360ghar/documents/general/a.pdf"


def _cloud() -> CloudinaryService:
    svc = CloudinaryService.__new__(CloudinaryService)
    svc.root = "360ghar"
    svc._uploader = MagicMock()
    svc._api = MagicMock()
    return svc


def test_get_file_info_returns_none_for_a_definitive_miss():
    svc = _cloud()
    svc._api.resource.side_effect = NotFound("no such asset")
    assert (
        svc.get_file_info("360ghar/x", resource_type="raw", delivery_type="authenticated") is None
    )


def test_get_file_info_raises_for_a_transient_failure():
    svc = _cloud()
    svc._api.resource.side_effect = GeneralError("timeout")
    with pytest.raises(StorageLookupError):
        svc.get_file_info("360ghar/x")


def _pending_media() -> SimpleNamespace:
    return SimpleNamespace(
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


def _db_for(media: SimpleNamespace) -> AsyncMock:
    result = MagicMock()
    result.scalar_one_or_none.return_value = media
    db = AsyncMock()
    db.execute = AsyncMock(return_value=result)
    return db


@pytest.mark.asyncio
async def test_confirm_returns_503_with_retry_after_on_a_lookup_error_and_keeps_pending():
    media = _pending_media()
    service = StorageService()
    service._cloudinary = MagicMock()
    service._cloudinary.get_file_info.side_effect = StorageLookupError("cloudinary timeout")

    with pytest.raises(ServiceUnavailableException) as exc_info:
        await service.confirm_upload(db=_db_for(media), upload_id="m1", user_id=1)

    assert exc_info.value.status_code == 503
    assert exc_info.value.error_code == "STORAGE_LOOKUP_FAILED"
    assert exc_info.value.headers == {"Retry-After": "30"}
    assert media.upload_status == "pending"


@pytest.mark.asyncio
async def test_confirm_keeps_404_and_marks_failed_for_a_definitive_miss():
    media = _pending_media()
    service = StorageService()
    service._cloudinary = MagicMock()
    service._cloudinary.get_file_info.return_value = None

    with pytest.raises(NotFoundException) as exc_info:
        await service.confirm_upload(db=_db_for(media), upload_id="m1", user_id=1)

    assert exc_info.value.error_code == "UPLOAD_NOT_IN_STORAGE"
    assert media.upload_status == "failed"


def _batch_db(rows: list[SimpleNamespace]) -> AsyncMock:
    result = MagicMock()
    result.scalars.return_value.all.return_value = rows
    db = AsyncMock()
    db.execute = AsyncMock(return_value=result)
    return db


def _doc(media_id: str = "m1") -> SimpleNamespace:
    return SimpleNamespace(
        id=media_id,
        file_url=PDF_URL,
        storage_path="360ghar/documents/general/a.pdf",
        filename="a.pdf",
        folder="360ghar/documents/general",
        bucket_name="cloudinary",
        mime_type="application/pdf",
    )


@pytest.mark.asyncio
async def test_batch_delete_keeps_the_row_when_storage_delete_fails():
    service = StorageService()
    doc = _doc()
    db = _batch_db([doc])
    with patch.object(service, "delete_file", return_value=False):
        result = await service.delete_batch(db, media_ids=["m1"], actor=SimpleNamespace(id=1))

    db.delete.assert_not_awaited()
    assert result["deleted"] == []
    assert result["failed"] == ["m1"]
    assert result["storage_warnings"] == ["m1"]


@pytest.mark.asyncio
async def test_batch_delete_keeps_the_row_when_storage_delete_raises():
    service = StorageService()
    db = _batch_db([_doc()])
    with patch.object(service, "delete_file", side_effect=RuntimeError("boom")):
        result = await service.delete_batch(db, media_ids=["m1"], actor=SimpleNamespace(id=1))

    db.delete.assert_not_awaited()
    assert result["failed"] == ["m1"]


@pytest.mark.asyncio
async def test_batch_delete_reports_a_failed_id_as_failed_for_every_reference():
    """The same row referenced by id and by URL: a storage failure reports both as failed."""
    service = StorageService()
    doc = _doc()
    db = _batch_db([doc])
    with patch.object(service, "delete_file", return_value=False):
        result = await service.delete_batch(
            db, media_ids=["m1", PDF_URL], actor=SimpleNamespace(id=1)
        )

    db.delete.assert_not_awaited()
    assert result["deleted"] == []
    assert result["failed"] == ["m1", PDF_URL]


@pytest.mark.asyncio
async def test_batch_delete_removes_the_row_when_storage_succeeds():
    service = StorageService()
    db = _batch_db([_doc()])
    with patch.object(service, "delete_file", return_value=True):
        result = await service.delete_batch(db, media_ids=["m1"], actor=SimpleNamespace(id=1))

    db.delete.assert_awaited_once()
    assert result["deleted"] == ["m1"]
    assert result["failed"] == []
    assert result["storage_warnings"] == []
