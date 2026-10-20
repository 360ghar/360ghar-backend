from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException, UploadFile
from starlette.datastructures import Headers

from app.core.exceptions import FileTooLargeException, InvalidFileException
from app.services.storage import StorageService
from app.services.storage.helpers import read_upload_file_limited
from app.services.storage_paths import StorageFolder


class _LimitedReadFile:
    def __init__(self, content: bytes):
        self._content = BytesIO(content)

    async def read(self, size: int = -1) -> bytes:
        return self._content.read(size)

    @property
    def position(self) -> int:
        return self._content.tell()


class TestStorageServiceErrors:
    """Regression tests for storage exception handling."""

    @pytest.mark.asyncio
    async def test_upload_agent_avatar_preserves_invalid_file_error(self):
        service = StorageService()
        service.supabase = MagicMock()

        file = UploadFile(
            filename="avatar.txt",
            file=BytesIO(b"not-an-image"),
            headers=Headers({"content-type": "text/plain"}),
        )

        with pytest.raises(InvalidFileException):
            await service.upload_agent_avatar(file, agent_id=1)

    @pytest.mark.asyncio
    async def test_create_presigned_upload_oversize_returns_413_exception(self):
        service = StorageService()
        db = MagicMock()

        with pytest.raises(FileTooLargeException) as exc_info:
            await service.create_presigned_upload(
                filename="huge.jpg",
                content_type="image/jpeg",
                file_size=service._max_upload_bytes + 1,
                user_id=1,
                db=db,
                folder=StorageFolder.GENERIC_UPLOAD,
            )

        assert exc_info.value.status_code == 413

    @pytest.mark.asyncio
    async def test_limited_reader_reads_at_most_one_byte_past_limit(self):
        file = _LimitedReadFile(b"abcdef")

        with pytest.raises(FileTooLargeException):
            await read_upload_file_limited(file, 3, chunk_size=10)  # type: ignore[arg-type]

        assert file.position == 4

    @pytest.mark.asyncio
    async def test_upload_with_path_rejects_oversize_file_before_storage_upload(self):
        service = StorageService()
        service._max_upload_bytes = 4
        service._cloudinary = MagicMock()

        file = UploadFile(
            filename="avatar.jpg",
            file=BytesIO(b"\xff\xd8\xffabcdef"),
            headers=Headers({"content-type": "image/jpeg"}),
        )

        with pytest.raises(FileTooLargeException):
            await service.upload_with_path(
                file,
                user_id=1,
                folder=StorageFolder.AVATAR,
            )

        service.cloudinary.upload_file.assert_not_called()

    @pytest.mark.asyncio
    async def test_upload_agent_avatar_rejects_oversize_file_before_storage_upload(self):
        service = StorageService()
        service._max_upload_bytes = 4
        service._cloudinary = MagicMock()

        file = UploadFile(
            filename="avatar.jpg",
            file=BytesIO(b"\xff\xd8\xffabcdef"),
            headers=Headers({"content-type": "image/jpeg"}),
        )

        with pytest.raises(FileTooLargeException):
            await service.upload_agent_avatar(file, agent_id=1)

        service.cloudinary.upload_file.assert_not_called()

    @pytest.mark.asyncio
    async def test_legacy_upload_file_rejects_oversize_file_before_storage_upload(self):
        service = StorageService()
        service._max_upload_bytes = 4
        service._cloudinary = MagicMock()

        file = UploadFile(
            filename="avatar.jpg",
            file=BytesIO(b"\xff\xd8\xffabcdef"),
            headers=Headers({"content-type": "image/jpeg"}),
        )

        with pytest.raises(FileTooLargeException):
            await service._upload_file(file, "uploads", "generic")

        service.cloudinary.upload_file.assert_not_called()

    @pytest.mark.asyncio
    async def test_upload_batch_rejects_more_than_twenty_files(self):
        service = StorageService()
        files = [
            UploadFile(
                filename=f"{idx}.jpg",
                file=BytesIO(b"\xff\xd8\xff"),
                headers=Headers({"content-type": "image/jpeg"}),
            )
            for idx in range(21)
        ]

        with pytest.raises(HTTPException) as exc_info:
            await service.upload_batch(files, db=None, user_id=1)

        assert exc_info.value.status_code == 400
        assert exc_info.value.detail["code"] == "BATCH_TOO_MANY_FILES"

    def test_storage_service_does_not_expose_noop_list_files(self):
        assert not hasattr(StorageService, "list_files")


class TestStorageDeleteBatch:
    """Regression tests for bulk media delete path."""

    @pytest.mark.asyncio
    async def test_delete_batch_by_id_and_url_uses_found_media(self):
        """Successful match must not raise NameError from incomplete rename."""
        service = StorageService()
        service.delete_file = MagicMock()

        media = SimpleNamespace(
            id="media-1",
            file_url="https://cdn.example.com/a.jpg",
            storage_path="folder/a.jpg",
            filename="a.jpg",
            folder="folder",
            bucket_name="media",
            mime_type="image/jpeg",
        )
        result_proxy = MagicMock()
        result_proxy.scalars.return_value.all.return_value = [media]
        db = AsyncMock()
        db.execute = AsyncMock(return_value=result_proxy)
        db.delete = AsyncMock()
        db.flush = AsyncMock()
        actor = SimpleNamespace(id=42)

        result = await service.delete_batch(
            db,
            media_ids=["media-1", "https://cdn.example.com/a.jpg", "missing-id"],
            actor=actor,
        )

        assert result["deleted"] == ["media-1", "https://cdn.example.com/a.jpg"]
        assert result["failed"] == ["missing-id"]
        assert result["storage_warnings"] == []
        service.delete_file.assert_called_once_with(
            "folder/a.jpg",
            bucket_name="media",
            resource_type="image",
            delivery_type="upload",
        )
        db.delete.assert_awaited_once_with(media)
        db.flush.assert_awaited_once()
