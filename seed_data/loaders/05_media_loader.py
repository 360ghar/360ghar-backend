"""
MediaUploader — uploads local media files to Cloudinary.

Scans seed/media/ and seed_data/media/ for local files, uploads them
to Cloudinary, and returns a mapping of local references to public URLs.
"""

from __future__ import annotations

import asyncio
import importlib
from pathlib import Path

from app.core.logging import get_logger
from app.services.cloudinary import cloudinary_service
from app.services.image_processing import optimize_for_web
from app.services.storage_paths import StorageFolder

_base = importlib.import_module("seed_data.loaders.01_base")
MEDIA_DIR = _base.MEDIA_DIR
SEED_DIR = _base.SEED_DIR
MEDIA_USERS_DIR = SEED_DIR.parent / "media" / "users"
HARDCODED_DIR = _base.HARDCODED_DIR
HARDCODED_PROPERTIES_DIR = HARDCODED_DIR / "properties"

logger = get_logger(__name__)


async def upload_media(
    dry_run: bool = False,
    user_id_override: int = 1,
) -> dict[str, str]:
    """Upload all local media files to Cloudinary.

    Returns a mapping of local refs (e.g. "media/users/female_25yr_divya_9d17a082.webp")
    to Cloudinary secure_urls. Uses parallel uploads with a semaphore for concurrency.
    """
    media_urls: dict[str, str] = {}

    if not MEDIA_DIR.exists():
        logger.warning("Media directory not found: %s", MEDIA_DIR)
        return media_urls

    # Collect all files to upload
    files_to_upload: list[tuple[Path, str]] = []

    # Files from seed/media/ directory
    for local_path in MEDIA_DIR.rglob("*"):
        if not local_path.is_file() or local_path.name.startswith("."):
            continue
        relative = local_path.relative_to(SEED_DIR)
        media_ref = str(relative).replace("\\", "/")
        files_to_upload.append((local_path, media_ref))

    # Files from seed_data/media/users/ directory (real avatar images)
    if MEDIA_USERS_DIR.exists():
        for local_path in MEDIA_USERS_DIR.iterdir():
            if not local_path.is_file() or local_path.name.startswith("."):
                continue
            media_ref = f"media/users/{local_path.name}"
            files_to_upload.append((local_path, media_ref))

    # Listing images and floor plans from hardcoded/properties/ directories
    if HARDCODED_PROPERTIES_DIR.exists():
        for prop_dir in HARDCODED_PROPERTIES_DIR.iterdir():
            if not prop_dir.is_dir() or not prop_dir.name.startswith("00"):
                continue
            slug = prop_dir.name
            listing_dir = prop_dir / "listing_images"
            if listing_dir.exists():
                for img_file in listing_dir.iterdir():
                    if not img_file.is_file() or img_file.name.startswith("."):
                        continue
                    media_ref = f"media/hc_properties/{slug}/listing_images/{img_file.name}"
                    files_to_upload.append((img_file, media_ref))
            floor_plan = prop_dir / "floor_plan.png"
            if floor_plan.exists():
                media_ref = f"media/hc_properties/{slug}/floor_plan.png"
                files_to_upload.append((floor_plan, media_ref))

    if not files_to_upload:
        logger.info("No media files found to upload.")
        return media_urls

    if dry_run:
        for _, media_ref in files_to_upload:
            logger.info("[DRY RUN] Would upload: %s", media_ref)
            media_urls[media_ref] = f"placeholder://{media_ref}"
        return media_urls

    # Upload in parallel with semaphore
    semaphore = asyncio.Semaphore(10)

    async def _upload_one(local_path: Path, media_ref: str) -> tuple[str, str]:
        """Upload a single file to Cloudinary. Returns (media_ref, url)."""
        async with semaphore:
            try:
                file_bytes = local_path.read_bytes()
                content_type = _infer_content_type(local_path.name)
                is_image = content_type.startswith("image/")

                # Optimize images for web delivery (convert to WebP)
                if is_image:
                    relative = _compute_relative(local_path, media_ref)
                    folder, _ = _resolve_storage_folder(relative, user_id_override)
                    max_dim = 2048 if folder in (StorageFolder.PROPERTY_IMAGE, StorageFolder.BLOG_COVER) else 512
                    try:
                        optimized_bytes, opt_content_type = optimize_for_web(
                            file_bytes, max_dimension=max_dim, quality=85
                        )
                        if optimized_bytes is not None:
                            file_bytes = optimized_bytes
                            if opt_content_type:
                                content_type = opt_content_type
                    except Exception:
                        logger.warning("Image optimization failed for %s, using original", media_ref)

                # Path-unique public_id derived from the full media_ref so files
                # that share a filename (living_room.webp, floor_plan.png) across
                # entities do not collide. NO extension in the public_id —
                # Cloudinary appends the detected format itself, so the delivered
                # URL always has one clean extension and never a double one
                # (.webp.jpg) when a source's true format differs from its name.
                rel = media_ref[len("media/"):] if media_ref.startswith("media/") else media_ref
                rel = rel.replace("\\", "/")
                p = Path(rel)
                parent = f"{p.parent}/" if str(p.parent) != "." else ""
                public_id = f"seed/{parent}{p.stem}"

                loop = asyncio.get_event_loop()

                def _sync_upload() -> str:
                    result = cloudinary_service.upload_file(
                        file_bytes=file_bytes,
                        public_id=public_id,
                        folder="360ghar",
                        content_type=content_type or "application/octet-stream",
                        is_image=is_image,
                        overwrite=True,
                    )
                    return result["secure_url"]

                url = await loop.run_in_executor(None, _sync_upload)
                logger.info("Uploaded: %s → %s", media_ref, url)
                return media_ref, url
            except Exception as exc:
                logger.error("Failed to upload %s: %s", media_ref, exc)
                return media_ref, f"placeholder://{media_ref}"

    upload_tasks = [_upload_one(path, ref) for path, ref in files_to_upload]
    results = await asyncio.gather(*upload_tasks)

    for media_ref, url in results:
        media_urls[media_ref] = url

    logger.info("Media upload complete: %d files mapped", len(media_urls))
    return media_urls


def _compute_relative(local_path: Path, media_ref: str) -> Path:
    """Compute a relative Path from media_ref for folder resolution."""
    if media_ref.startswith("media/"):
        return Path(media_ref)
    return Path(media_ref)


def _resolve_storage_folder(relative: Path, default_user_id: int) -> tuple[StorageFolder, int]:
    """Determine the StorageFolder enum and user_id for a file path."""
    parts = relative.parts

    if "avatars" in parts or ("users" in parts and "hc_properties" not in parts):
        return StorageFolder.AVATAR, default_user_id
    elif "hc_properties" in parts:
        return StorageFolder.GENERIC_UPLOAD, default_user_id
    elif "properties" in parts:
        return StorageFolder.PROPERTY_IMAGE, default_user_id
    elif "tours" in parts:
        return StorageFolder.GENERIC_UPLOAD, default_user_id
    elif "documents" in parts:
        return StorageFolder.DOCUMENT_GENERAL, default_user_id
    elif "floor_plans" in parts:
        return StorageFolder.GENERIC_UPLOAD, default_user_id
    elif "blogs" in parts:
        return StorageFolder.BLOG_COVER, default_user_id
    else:
        return StorageFolder.GENERIC_UPLOAD, default_user_id


def _infer_content_type(filename: str) -> str:
    """Infer MIME type from file extension."""
    ext = Path(filename).suffix.lower()
    content_types = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
        ".gif": "image/gif",
        ".pdf": "application/pdf",
        ".mp4": "video/mp4",
        ".webm": "video/webm",
    }
    return content_types.get(ext, "application/octet-stream")
