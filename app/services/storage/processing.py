from __future__ import annotations

import asyncio
import uuid
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from fastapi import UploadFile

from app.core.exceptions import InvalidFileException, StorageException
from app.core.logging import get_logger
from app.services import image_processing

from .helpers import VALID_IMAGE_TYPES

if TYPE_CHECKING:
    from PIL.Image import Image as PILImage

    from app.services.cloudinary.service import CloudinaryService

logger = get_logger(__name__)

_IMAGE_PROCESSING_SEMAPHORE = asyncio.Semaphore(2)


def _folder_for_scene(tour_id: str, scene_id: str, user_id: int) -> str:
    return f"tours/{tour_id}/scenes/{scene_id}"


async def upload_scene_image(
    cloudinary: CloudinaryService,
    file: UploadFile,
    *,
    tour_id: str,
    scene_id: str,
    user_id: int,
    create_media_record: Callable | None = None,
    db: Any | None = None,
) -> dict[str, Any]:
    try:
        from PIL import Image

        if file.content_type not in VALID_IMAGE_TYPES:
            raise InvalidFileException(detail="Invalid image type")

        async with _IMAGE_PROCESSING_SEMAPHORE:
            file_content = await file.read()

            import io
            with Image.open(io.BytesIO(file_content)) as img:
                width, height = img.size
                aspect_ratio = width / height if height > 0 else 0
                is_panorama = abs(aspect_ratio - 2.0) <= 0.1
                if not is_panorama:
                    logger.warning("Image may not be a valid 360 panorama for scene %s", scene_id)

                image_info = image_processing.get_image_info(img=img, file_size=len(file_content))
                rgb_img, _ = image_processing._normalize_image_mode(img)

                try:
                    thumbnail_bytes = _thumbnail_from_image(rgb_img, max_size=512)
                    web_bytes = _webp_from_image(rgb_img, max_dimension=4096)
                finally:
                    if rgb_img is not img:
                        rgb_img.close()

        file_size = len(file_content)
        file_id = str(uuid.uuid4())[:8]
        base_folder = _folder_for_scene(tour_id, scene_id, user_id)

        original_result = cloudinary.upload_file(
            file_bytes=file_content,
            public_id=f"{file_id}_original",
            folder=f"{base_folder}/original",
            content_type=file.content_type,
            is_image=True,
        )
        original_url = original_result["secure_url"]
        del file_content

        thumbnail_result = cloudinary.upload_file(
            file_bytes=thumbnail_bytes,
            public_id=f"{file_id}_thumb",
            folder=f"{base_folder}/thumbnail",
            content_type="image/webp",
            is_image=True,
        )
        thumbnail_url = thumbnail_result["secure_url"]
        del thumbnail_bytes

        web_result = cloudinary.upload_file(
            file_bytes=web_bytes,
            public_id=f"{file_id}_web",
            folder=f"{base_folder}/web",
            content_type="image/webp",
            is_image=True,
        )
        web_url = web_result["secure_url"]
        del web_bytes

        if db and create_media_record:
            await create_media_record(
                db=db,
                user_id=user_id,
                upload_result={
                    "file_path": original_result["public_id"],
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
    except Exception:
        logger.exception("Scene image upload error")
        raise StorageException(
            detail="Scene image upload failed", error_code="UPLOAD_FAILED"
        ) from None


def _thumbnail_from_image(img: PILImage, max_size: int = 512) -> bytes:
    import io as _io

    from PIL import Image

    thumb = img.copy()
    try:
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
        return buf.getvalue()
    finally:
        thumb.close()


def _webp_from_image(
    img: PILImage,
    max_dimension: int = 4096,
    quality: int = image_processing.WEBP_QUALITY,
) -> bytes:
    import io as _io

    from PIL import Image

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
    try:
        buf = _io.BytesIO()
        web_img.save(buf, format="WEBP", quality=quality, optimize=True)
        return buf.getvalue()
    finally:
        if web_img is not img:
            web_img.close()


async def process_existing_scene_image(
    cloudinary: CloudinaryService,
    image_url: str,
    tour_id: str,
    scene_id: str,
    user_id: int,
) -> dict[str, Any]:
    from app.core.http import get_general_client

    try:
        client = get_general_client()
        response = await client.get(image_url, timeout=60.0)
        response.raise_for_status()
        file_content = response.content

        image_info = image_processing.get_image_info(file_content)

        file_id = str(uuid.uuid4())[:8]
        base_folder = _folder_for_scene(tour_id, scene_id, user_id)

        thumbnail_bytes = image_processing.generate_thumbnail(file_content, max_size=512)

        result = cloudinary.upload_file(
            file_bytes=thumbnail_bytes,
            public_id=f"{file_id}_thumb",
            folder=f"{base_folder}/thumbnail",
            content_type="image/webp",
            is_image=True,
        )
        thumbnail_url = result["secure_url"]

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
