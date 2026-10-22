"""Photo intake for the AI tools: decode, check, shrink. Every check runs before a model call.

A photo arrives as base64 or as a Cloudinary URL of this account. The checks are the decoded
size, the magic bytes against the declared MIME type, and a full pixel decode.
"""

from __future__ import annotations

import base64
import binascii
import io
import re
from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx

from app.config import settings
from app.core.exceptions import BadRequestException
from app.core.http import get_general_client
from app.services.ai.base import VisionInput

ALLOWED_MIME = ("image/jpeg", "image/png", "image/webp")
MAX_PHOTO_BYTES = 3 * 1024 * 1024  # decoded
MAX_PIXELS = 40_000_000
MODEL_SIDE = 768  # longest side sent to the model
MIN_SIDE = 600  # below this a photo is flagged as low resolution
_DATA_URL = re.compile(r"^data:(?P<mime>[\w/+.-]+);base64,", re.IGNORECASE)


@dataclass(frozen=True)
class Photo:
    data: bytes
    mime: str
    width: int
    height: int


def sniff_mime(data: bytes) -> str | None:
    """The MIME type the bytes really are, for the three types the tools accept."""
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def _bad(message: str) -> BadRequestException:
    return BadRequestException(message, error_code="INVALID_PHOTO")


def decode_base64(
    value: str, declared_mime: str | None, *, max_bytes: int = MAX_PHOTO_BYTES
) -> tuple[bytes, str | None]:
    """(bytes, declared MIME type). Strict base64; the size is checked before the decode, from the
    text length. A data URL's own MIME type must agree with ``declared_mime`` when both are given."""
    match = _DATA_URL.match(value)
    if match:
        embedded = match.group("mime").lower()
        if declared_mime and declared_mime.lower() != embedded:
            raise _bad("A photo's mime_type does not match its data URL")
        declared_mime = declared_mime or embedded
        value = value[match.end() :]
    if len(value) > (max_bytes * 4) // 3 + 8:
        raise _bad(f"A photo is larger than {max_bytes // (1024 * 1024)} MB")
    try:
        data = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise _bad("A photo is not valid base64") from exc
    if len(data) > max_bytes:
        raise _bad(f"A photo is larger than {max_bytes // (1024 * 1024)} MB")
    return data, declared_mime


def check_photo(data: bytes, declared_mime: str | None) -> Photo:
    """Magic bytes must match the declared type, and the pixels must decode."""
    from PIL import Image

    real = sniff_mime(data)
    if real is None or real not in ALLOWED_MIME:
        raise _bad("A photo must be a JPEG, PNG or WebP image")
    if declared_mime and declared_mime.lower() != real:
        raise _bad("A photo's mime_type does not match its content")
    try:
        with Image.open(io.BytesIO(data)) as img:
            width, height = img.size
            if width * height > MAX_PIXELS:
                raise _bad("A photo has too many pixels")
            img.load()
    except BadRequestException:
        raise
    except Exception as exc:
        raise _bad("A photo could not be read as an image") from exc
    return Photo(data, real, width, height)


def is_cloudinary_url(url: str) -> bool:
    """https, host res.cloudinary.com, this account's cloud name, an image delivery path."""
    cloud = settings.CLOUDINARY_CLOUD_NAME
    try:
        parts = urlsplit(url)
        port = parts.port  # raises ValueError on a malformed port
    except ValueError:
        return False
    return bool(
        cloud
        and len(url) <= 600
        and parts.scheme == "https"
        and parts.hostname == "res.cloudinary.com"
        and port is None
        and parts.username is None
        and parts.path.startswith(f"/{cloud}/image/upload/")
    )


async def fetch_cloudinary(url: str, *, max_bytes: int = MAX_PHOTO_BYTES) -> bytes:
    if not is_cloudinary_url(url):
        raise _bad("A photo URL must be a Cloudinary image URL of this account")
    try:
        async with get_general_client().stream("GET", url, timeout=20.0, follow_redirects=False) as resp:
            if resp.status_code != 200:
                raise _bad("A photo URL could not be fetched")
            body = bytearray()
            async for chunk in resp.aiter_bytes():
                body.extend(chunk)
                if len(body) > max_bytes:
                    raise _bad(f"A photo is larger than {max_bytes // (1024 * 1024)} MB")
    except httpx.HTTPError as exc:
        raise _bad("A photo URL could not be fetched") from exc
    return bytes(body)


def shrink(photo: Photo, side: int = MODEL_SIDE, quality: int = 85) -> VisionInput:
    """The photo as a JPEG with its longest side at most ``side``, for the model."""
    from PIL import Image, ImageOps

    with Image.open(io.BytesIO(photo.data)) as img:
        rgb = ImageOps.exif_transpose(img).convert("RGB")
        rgb.thumbnail((side, side))
        out = io.BytesIO()
        rgb.save(out, "JPEG", quality=quality)
    return VisionInput(image_base64=base64.b64encode(out.getvalue()).decode("ascii"), mime_type="image/jpeg")
