"""Unit tests for storage magic-byte validation (Security #7).

Covers :func:`app.services.storage.helpers.validate_magic_bytes` for every
supported type, both with genuine magic headers and with spoofed payloads
that should be rejected.
"""

from io import BytesIO

import pytest
from fastapi import UploadFile
from starlette.datastructures import Headers

from app.core.exceptions import StorageException
from app.services.storage.helpers import (
    expected_type_from_content_type,
    validate_magic_bytes,
)
from app.services.storage.service import StorageService
from app.services.storage_paths import StorageFolder

# ── Genuine magic-byte fixtures ───────────────────────────────────────────────

VALID_PDF = b"%PDF-1.5\n..." + b"\x00" * 64
VALID_MP4 = b"\x00\x00\x00\x20ftypisom" + b"\x00" * 64
VALID_WEBM = b"\x1a\x45\xdf\xa3" + b"\x00" * 64
VALID_QUICKTIME = b"\x00\x00\x00\x14moov" + b"\x00" * 64
VALID_MP3_ID3 = b"ID3\x03\x00" + b"\x00" * 64
VALID_MP3_FRAME = b"\xff\xfb" + b"\x00" * 64
VALID_WAV = b"RIFF\x00\x00\x00\x00WAVEfmt " + b"\x00" * 64
VALID_JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64  # image, delegated to PIL

# Spoofed payloads (claim one type, contain another's bytes)
SPOOFED_PDF = b"NOTPDF" + b"\x00" * 64
SPOOFED_MP4 = b"\x00\x00\x00\x00XXXX" + b"\x00" * 64
SPOOFED_WEBM = b"\x00\x00\x00\x00" + b"\x00" * 64
SPOOFED_QUICKTIME = b"\x00\x00\x00\x00yyyy" + b"\x00" * 64
SPOOFED_MP3 = b"XX" + b"\x00" * 64
SPOOFED_WAV = b"RIFF\x00\x00\x00\x00XXXX" + b"\x00" * 64


class TestValidateMagicBytes:
    """Direct tests of validate_magic_bytes + expected_type_from_content_type."""

    @pytest.mark.parametrize(
        "content_type,expected",
        [
            ("image/jpeg", "image"),
            ("image/png", "image"),
            ("image/webp", "image"),
            ("image/gif", "image"),
            ("application/pdf", "pdf"),
            ("video/mp4", "mp4"),
            ("video/webm", "webm"),
            ("video/quicktime", "quicktime"),
            ("audio/mpeg", "mp3"),
            ("audio/mp3", "mp3"),
            ("audio/wav", "wav"),
            ("audio/ogg", None),
            ("video/x-matroska", None),
            ("application/msword", None),
            ("", None),
            (None, None),
        ],
    )
    def test_expected_type_from_content_type(self, content_type, expected):
        assert expected_type_from_content_type(content_type) == expected

    @pytest.mark.parametrize(
        "content,expected_type",
        [
            (VALID_PDF, "pdf"),
            (VALID_MP4, "mp4"),
            (VALID_WEBM, "webm"),
            (VALID_QUICKTIME, "quicktime"),
            (VALID_MP3_ID3, "mp3"),
            (VALID_MP3_FRAME, "mp3"),
            (VALID_WAV, "wav"),
            (VALID_JPEG, "image"),
        ],
    )
    def test_valid_magic_bytes_accepted(self, content, expected_type):
        assert validate_magic_bytes(content, expected_type) is True

    @pytest.mark.parametrize(
        "content,expected_type",
        [
            (SPOOFED_PDF, "pdf"),
            (SPOOFED_MP4, "mp4"),
            (SPOOFED_WEBM, "webm"),
            (SPOOFED_QUICKTIME, "quicktime"),
            (SPOOFED_MP3, "mp3"),
            (SPOOFED_WAV, "wav"),
        ],
    )
    def test_spoofed_magic_bytes_rejected(self, content, expected_type):
        assert validate_magic_bytes(content, expected_type) is False

    def test_empty_content_rejected_for_non_image(self):
        assert validate_magic_bytes(b"", "pdf") is False
        assert validate_magic_bytes(b"", "mp4") is False

    def test_empty_content_rejected_for_image(self):
        assert validate_magic_bytes(b"", "image") is False

    def test_spoofed_image_rejected(self):
        # Non-image content with image content_type should be rejected.
        assert validate_magic_bytes(b"not an image at all", "image") is False

    def test_unknown_expected_type_allows(self):
        # No magic-byte rule defined → allow (don't break valid-but-unmapped types).
        assert validate_magic_bytes(b"anything", "ogg") is True

    def test_mp3_lower_bound_frame_byte(self):
        # 0xE0 is the inclusive lower bound for the second MP3 frame byte.
        assert validate_magic_bytes(b"\xff\xe0" + b"\x00" * 10, "mp3") is True

    def test_mp3_below_lower_bound_rejected(self):
        assert validate_magic_bytes(b"\xff\xdf" + b"\x00" * 10, "mp3") is False


def _make_upload(content: bytes, content_type: str, filename: str = "f") -> UploadFile:
    return UploadFile(
        filename=filename,
        file=BytesIO(content),
        headers=Headers({"content-type": content_type}),
    )


class TestServiceRejectsSpoofedUploads:
    """Integration of validate_magic_bytes into StorageService upload entrypoints.

    Cloudinary is mocked so the magic-byte check is the only thing exercised.
    """

    @pytest.mark.asyncio
    async def test_upload_with_path_rejects_spoofed_pdf(self):
        service = StorageService()
        service._cloudinary = object()  # avoid lazy cloudinary build; never reached

        file = _make_upload(SPOOFED_PDF, "application/pdf", "spoof.pdf")
        with pytest.raises(StorageException) as exc_info:
            await service.upload_with_path(
                file, user_id=1, folder=StorageFolder.DOCUMENT_GENERAL
            )
        assert exc_info.value.error_code == "INVALID_FILE_TYPE"

    @pytest.mark.asyncio
    async def test_upload_with_path_rejects_spoofed_mp4(self):
        service = StorageService()
        service._cloudinary = object()

        file = _make_upload(SPOOFED_MP4, "video/mp4", "spoof.mp4")
        with pytest.raises(StorageException) as exc_info:
            await service.upload_with_path(
                file, user_id=1, folder=StorageFolder.GENERIC_UPLOAD
            )
        assert exc_info.value.error_code == "INVALID_FILE_TYPE"

    @pytest.mark.asyncio
    async def test_upload_agent_avatar_rejects_spoofed_mp4(self):
        service = StorageService()
        service._cloudinary = object()

        file = _make_upload(SPOOFED_MP4, "video/mp4", "avatar.mp4")
        with pytest.raises(StorageException) as exc_info:
            await service.upload_agent_avatar(file, agent_id=1)
        assert exc_info.value.error_code == "INVALID_FILE_TYPE"

    @pytest.mark.asyncio
    async def test_upload_file_rejects_spoofed_webm(self):
        service = StorageService()
        service._cloudinary = object()

        file = _make_upload(SPOOFED_WEBM, "video/webm", "spoof.webm")
        with pytest.raises(StorageException) as exc_info:
            await service._upload_file(file, "uploads", "generic")
        assert exc_info.value.error_code == "INVALID_FILE_TYPE"

    @pytest.mark.asyncio
    async def test_valid_pdf_passes_magic_check_and_fails_at_cloudinary(self):
        """A genuine PDF should pass the magic-byte check and only fail later
        when the (un-mocked) Cloudinary upload is attempted — proving the
        magic-byte gate did not reject it."""
        service = StorageService()
        service._cloudinary = object()

        file = _make_upload(VALID_PDF, "application/pdf", "real.pdf")
        # Cloudinary call will fail because _cloudinary is a bare object, but
        # the failure must NOT be INVALID_FILE_TYPE (it should surface as the
        # generic upload-failed path instead).
        with pytest.raises(StorageException) as exc_info:
            await service._upload_file(
                file, "uploads", "generic", allow_documents=True
            )
        assert exc_info.value.error_code != "INVALID_FILE_TYPE"
