"""
Image processing pipeline for the storage service.

Thumbnail generation, WebP conversion, and scene-image upload orchestration
that was previously embedded in the StorageService class.
"""
import uuid
from collections.abc import Callable
from typing import Any

from fastapi import UploadFile
from PIL import Image

from app.core.exceptions import InvalidFileException, StorageException
from app.core.logging import get_logger
from app.services import image_processing

from .helpers import VALID_IMAGE_TYPES

logger = get_logger(__name__)


async def upload_scene_image(
    supabase: Any,
    bucket_name: str,
    file: UploadFile,
    *,
    tour_id: str,
    scene_id: str,
    user_id: int,
    create_media_record: Callable | None = None,
    db: Any | None = None,
) -> dict[str, Any]:
    """
    Upload a 360 scene image with automatic thumbnail generation.

    Opens the source image once and reuses it for all operations to minimize
    peak memory usage.

    Uses user-scoped path: users/{user_id}/tours/{tour_id}/scenes/{scene_id}/...

    Args:
        supabase: Supabase storage client.
        bucket_name: Name of the storage bucket.
        file: The image file to upload.
        tour_id: The tour ID.
        scene_id: The scene ID.
        user_id: User ID for path scoping (REQUIRED).
        create_media_record: Optional async callback to create a MediaFile DB record.
        db: Database session (passed through to create_media_record).

    Returns:
        Dict with image_url, thumbnail_url, web_url, and metadata.
    """
    try:
        # Validate file type
        if file.content_type not in VALID_IMAGE_TYPES:
            raise InvalidFileException(detail="Invalid image type")

        # Read file content
        file_content = await file.read()

        # Open image once for all operations
        import io
        with Image.open(io.BytesIO(file_content)) as img:
            width, height = img.size
            aspect_ratio = width / height if height > 0 else 0
            is_panorama = abs(aspect_ratio - 2.0) <= 0.1
            if not is_panorama:
                logger.warning("Image may not be a valid 360 panorama for scene %s", scene_id)

            # Extract metadata using the already-open image (no extra opens)
            image_info = image_processing.get_image_info(img=img, file_size=len(file_content))

            # Generate thumbnail from the open image
            rgb_img = img
            if img.mode in ("RGBA", "P"):
                rgb_img = img.convert("RGB")  # type: ignore[assignment]
            thumbnail_bytes = _thumbnail_from_image(rgb_img, max_size=512)

            # Generate WebP from the open image
            web_bytes = _webp_from_image(rgb_img, max_dimension=4096)

        # Release file_content early — the derived buffers are much smaller
        file_size = len(file_content)

        # Generate unique filenames with user-scoped paths
        file_id = str(uuid.uuid4())
        base_folder = f"users/{user_id}/tours/{tour_id}/scenes/{scene_id}"

        # Upload original image
        original_path = f"{base_folder}/original/{file_id}.jpg"
        original_result = supabase.storage.from_(bucket_name).upload(
            path=original_path,
            file=file_content,
            file_options={
                "content-type": file.content_type,
                "cache-control": "31536000",
                "upsert": False,
            },
        )

        if hasattr(original_result, "error") and original_result.error:
            raise StorageException(detail="Failed to upload original image")

        original_url = supabase.storage.from_(bucket_name).get_public_url(original_path)

        # Free the original content now that it's uploaded
        del file_content

        # Upload thumbnail
        thumbnail_path = f"{base_folder}/thumbnail/{file_id}.webp"
        thumbnail_result = supabase.storage.from_(bucket_name).upload(
            path=thumbnail_path,
            file=thumbnail_bytes,
            file_options={
                "content-type": "image/webp",
                "cache-control": "31536000",
                "upsert": False,
            },
        )

        if hasattr(thumbnail_result, "error") and thumbnail_result.error:
            logger.warning("Failed to upload thumbnail for scene %s", scene_id)
            thumbnail_url = None
        else:
            thumbnail_url = supabase.storage.from_(bucket_name).get_public_url(thumbnail_path)

        # Upload WebP optimized version
        del thumbnail_bytes
        web_path = f"{base_folder}/web/{file_id}.webp"
        web_result = supabase.storage.from_(bucket_name).upload(
            path=web_path,
            file=web_bytes,
            file_options={
                "content-type": "image/webp",
                "cache-control": "31536000",
                "upsert": False,
            },
        )

        if hasattr(web_result, "error") and web_result.error:
            logger.warning("Failed to upload WebP version for scene %s", scene_id)
            web_url = original_url
        else:
            web_url = supabase.storage.from_(bucket_name).get_public_url(web_path)

        del web_bytes

        # Track in database if available
        if db and create_media_record:
            await create_media_record(
                db=db,
                user_id=user_id,
                upload_result={
                    "file_path": original_path,
                    "public_url": original_url,
                    "file_type": "scene_image",
                    "file_size": file_size,
                    "content_type": file.content_type,
                    "original_filename": file.filename,
                },
                tour_id=tour_id,
                visibility="public",
            )

        return {
            "image_url": original_url,
            "thumbnail_url": thumbnail_url,
            "web_url": web_url,
            "width": image_info["width"],
            "height": image_info["height"],
            "is_panorama": is_panorama,
            "exif": image_info.get("exif"),
            "file_size": file_size,
        }

    except InvalidFileException:
        raise
    except StorageException:
        raise
    except Exception as e:
        logger.error("Scene image upload error: %s", e)
        raise StorageException(detail=f"Scene image upload failed: {str(e)}") from None


def _thumbnail_from_image(img: Image.Image, max_size: int = 512) -> bytes:
    """Generate thumbnail bytes from an already-open Pillow Image."""
    import io as _io
    thumb = img.copy()
    w, h = thumb.size
    aspect_ratio = w / h
    if w > h:
        new_w = min(max_size, w)
        new_h = int(new_w / aspect_ratio)
    else:
        new_h = min(max_size, h)
        new_w = int(new_h * aspect_ratio)
    thumb.thumbnail((new_w, new_h), Image.Resampling.LANCZOS)
    buf = _io.BytesIO()
    thumb.save(buf, format="WEBP", quality=image_processing.WEBP_QUALITY, optimize=True)
    thumb.close()
    return buf.getvalue()


def _webp_from_image(img: Image.Image, max_dimension: int = 4096, quality: int = image_processing.WEBP_QUALITY) -> bytes:
    """Generate WebP bytes from an already-open Pillow Image."""
    import io as _io
    web_img = img.copy()
    w, h = web_img.size
    if w > max_dimension or h > max_dimension:
        ar = w / h
        if w > h:
            new_w = max_dimension
            new_h = int(max_dimension / ar)
        else:
            new_h = max_dimension
            new_w = int(new_h * ar)
        web_img = web_img.resize((new_w, new_h), Image.Resampling.LANCZOS)
    buf = _io.BytesIO()
    web_img.save(buf, format="WEBP", quality=quality, optimize=True)
    web_img.close()
    return buf.getvalue()


async def process_existing_scene_image(
    supabase: Any,
    bucket_name: str,
    image_url: str,
    tour_id: str,
    scene_id: str,
    user_id: int,
) -> dict[str, Any]:
    """
    Process an existing scene image URL to generate thumbnails.

    Uses user-scoped path for generated files.

    Args:
        supabase: Supabase storage client.
        bucket_name: Name of the storage bucket.
        image_url: URL of the existing image.
        tour_id: Tour ID.
        scene_id: Scene ID.
        user_id: User ID for path scoping.

    Returns:
        Dict with thumbnail_url and metadata.
    """
    import httpx

    try:
        # Download the image
        async with httpx.AsyncClient() as client:
            response = await client.get(image_url, timeout=60)
            response.raise_for_status()
            file_content = response.content

        # Get image info
        image_info = image_processing.get_image_info(file_content)

        # Generate unique filenames with user-scoped path
        file_id = str(uuid.uuid4())
        folder = f"users/{user_id}/tours/{tour_id}/scenes/{scene_id}"

        # Generate and upload thumbnail
        thumbnail_bytes = image_processing.generate_thumbnail(file_content, max_size=512)
        thumbnail_path = f"{folder}/thumbnail/{file_id}.webp"

        thumbnail_result = supabase.storage.from_(bucket_name).upload(
            path=thumbnail_path,
            file=thumbnail_bytes,
            file_options={
                "content-type": "image/webp",
                "cache-control": "31536000",
                "upsert": False,
            },
        )

        if hasattr(thumbnail_result, "error") and thumbnail_result.error:
            logger.warning("Failed to upload thumbnail for scene %s", scene_id)
            return {"thumbnail_url": None, "metadata": image_info}

        thumbnail_url = supabase.storage.from_(bucket_name).get_public_url(thumbnail_path)

        return {
            "thumbnail_url": thumbnail_url,
            "width": image_info["width"],
            "height": image_info["height"],
            "is_panorama": image_info.get("is_360_panorama", False),
            "exif": image_info.get("exif"),
        }

    except Exception as e:
        logger.error("Failed to process existing scene image: %s", e)
        return {"thumbnail_url": None, "error": str(e)}
