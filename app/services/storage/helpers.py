"""
Validation helpers for the storage service.

MIME type checks, file size checks, and extension inference.
"""
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
    return None


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
    if content_type in VALID_AUDIO_TYPES:
        return ".mp3"
    if content_type in VALID_VIDEO_TYPES:
        return ".mp4"
    return ".jpg"
