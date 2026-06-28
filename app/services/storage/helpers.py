"""
Validation helpers for the storage service.

MIME type checks, file size checks, and extension inference.
"""
from __future__ import annotations

import os

from fastapi import UploadFile

from app.config import settings

# ── Valid MIME type sets ────────────────────────────────────────────────

VALID_IMAGE_TYPES: set[str] = {
    "image/jpeg",
    "image/jpg",
    "image/png",
    "image/webp",
    "image/gif",
}

VALID_AUDIO_TYPES: set[str] = {
    "audio/mpeg",
    "audio/mp3",
    "audio/wav",
    "audio/ogg",
    "audio/webm",
    "audio/aac",
    "audio/mp4",
}

VALID_VIDEO_TYPES: set[str] = {
    "video/mp4",
    "video/webm",
    "video/quicktime",
    "video/x-matroska",
    "video/ogg",
}

VALID_DOCUMENT_TYPES: set[str] = {
    "application/pdf",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


def get_max_upload_bytes() -> int:
    """Return the maximum upload size in bytes (from settings)."""
    return int(getattr(settings, "MAX_UPLOAD_SIZE_MB", 50)) * 1024 * 1024


def is_valid_upload(file: UploadFile, *, allow_documents: bool = False) -> bool:
    """Validate upload content types.

    Args:
        file: UploadFile with content_type attribute.
        allow_documents: Whether to accept document MIME types.

    Returns:
        True if the file's content_type is in the valid set.
    """
    valid = VALID_IMAGE_TYPES | VALID_AUDIO_TYPES | VALID_VIDEO_TYPES
    if allow_documents:
        valid |= VALID_DOCUMENT_TYPES
    return file.content_type in valid


def is_valid_content_type(content_type: str, *, allow_documents: bool = False) -> bool:
    """Validate a content-type string.

    Args:
        content_type: MIME type string.
        allow_documents: Whether to accept document MIME types.

    Returns:
        True if the content_type is in the valid set.
    """
    valid = VALID_IMAGE_TYPES | VALID_AUDIO_TYPES | VALID_VIDEO_TYPES
    if allow_documents:
        valid |= VALID_DOCUMENT_TYPES
    return content_type in valid


def infer_content_type_from_extension(ext: str) -> str | None:
    """Infer MIME type from a file extension.

    Args:
        ext: File extension including dot (e.g. ``".jpg"``).

    Returns:
        Inferred MIME type, or ``None`` if unknown.
    """
    if ext in {".jpg", ".jpeg"}:
        return "image/jpeg"
    if ext == ".png":
        return "image/png"
    if ext == ".webp":
        return "image/webp"
    if ext == ".gif":
        return "image/gif"
    if ext == ".mp4":
        return "video/mp4"
    if ext == ".webm":
        return "video/webm"
    if ext == ".pdf":
        return "application/pdf"
    if ext == ".mp3":
        return "audio/mpeg"
    if ext == ".wav":
        return "audio/wav"
    if ext == ".ogg":
        return "audio/ogg"
    if ext == ".mov":
        return "video/quicktime"
    if ext == ".mkv":
        return "video/x-matroska"
    if ext == ".aac":
        return "audio/aac"
    if ext == ".doc":
        return "application/msword"
    if ext == ".docx":
        return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    return None


def expected_type_from_content_type(content_type: str | None) -> str | None:
    """Map a MIME content_type to a magic-byte validation category.

    Returns one of ``"image"``, ``"pdf"``, ``"mp4"``, ``"webm"``,
    ``"quicktime"``, ``"mp3"``, ``"wav"`` — or ``None`` for types that have
    no magic-byte check defined (e.g. ogg/aac/matroska/msword).
    """
    if not content_type:
        return None
    if content_type.startswith("image/"):
        return "image"
    if content_type == "application/pdf":
        return "pdf"
    if content_type == "video/mp4":
        return "mp4"
    if content_type == "video/webm":
        return "webm"
    if content_type == "video/quicktime":
        return "quicktime"
    if content_type in ("audio/mpeg", "audio/mp3"):
        return "mp3"
    if content_type == "audio/wav":
        return "wav"
    return None


def validate_magic_bytes(content: bytes, expected_type: str) -> bool:
    """Verify that ``content`` starts with the known magic header for ``expected_type``.

    Images are delegated to PIL downstream (``image_processing.optimize_for_web``)
    so this function returns ``True`` immediately for ``"image"``.

    Args:
        content: Raw file bytes (at least the first ~12 bytes are inspected).
        expected_type: One of the categories returned by
            :func:`expected_type_from_content_type`.

    Returns:
        ``True`` if the magic bytes match, ``False`` otherwise.
    """
    if expected_type == "image":
        if not content or len(content) < 4:
            return False
        # JPEG: FF D8 FF
        if content[:3] == b"\xff\xd8\xff":
            return True
        # PNG: 89 50 4E 47
        if content[:4] == b"\x89PNG":
            return True
        # GIF: GIF8
        if content[:4] == b"GIF8":
            return True
        # WebP: RIFF....WEBP
        if content[:4] == b"RIFF" and len(content) >= 12 and content[8:12] == b"WEBP":
            return True
        # BMP: BM
        if content[:2] == b"BM":
            return True
        # TIFF: II (little-endian) or MM (big-endian)
        if content[:2] in (b"II", b"MM"):
            return True
        return False
    if not content:
        return False
    if expected_type == "pdf":
        return content[:5] == b"%PDF-"
    if expected_type == "mp4":
        return content[4:8] == b"ftyp"
    if expected_type == "webm":
        return content.startswith(b"\x1a\x45\xdf\xa3")
    if expected_type == "quicktime":
        return content[4:8] in (b"free", b"moov", b"mdat", b"qt  ")
    if expected_type == "mp3":
        if content.startswith(b"ID3"):
            return True
        return len(content) >= 2 and content[0] == 0xFF and 0xE0 <= content[1] <= 0xFF
    if expected_type == "wav":
        return content[:4] == b"RIFF" and content[8:12] == b"WAVE"
    # Unknown expected_type: no magic-byte rule defined, allow.
    return True


def get_file_extension(filename: str, *, content_type: str | None = None) -> str:
    """Get file extension from filename, with a safe fallback by content-type.

    Args:
        filename: Original filename.
        content_type: MIME type used as fallback when filename has no extension.

    Returns:
        File extension including dot (e.g. ``".jpg"``).
    """
    if filename:
        ext = os.path.splitext(filename)[1]
        if ext:
            return ext

    if content_type == "application/pdf":
        return ".pdf"
    if content_type == "application/msword":
        return ".doc"
    if content_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
        return ".docx"
    if content_type in VALID_AUDIO_TYPES:
        return ".mp3"
    if content_type == "video/webm":
        return ".webm"
    if content_type == "video/quicktime":
        return ".mov"
    if content_type == "video/x-matroska":
        return ".mkv"
    if content_type in VALID_VIDEO_TYPES:
        return ".mp4"
    return ".jpg"
