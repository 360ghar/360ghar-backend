from __future__ import annotations

import os
import uuid
from typing import TYPE_CHECKING, Any

from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    BadRequestException,
    BaseAPIException,
    FileTooLargeException,
    InvalidFileException,
    NotFoundException,
    StorageException,
)
from app.core.logging import get_logger
from app.models.tours import MediaFile
from app.services import image_processing
from app.services.cloudinary import get_cloudinary_service
from app.services.storage_paths import (
    StorageFolder,
    generate_cloudinary_public_id,
)

from .helpers import (
    VALID_AUDIO_TYPES,
    VALID_DOCUMENT_TYPES,
    VALID_IMAGE_TYPES,
    VALID_VIDEO_TYPES,
    expected_type_from_content_type,
    get_file_extension,
    get_max_upload_bytes,
    infer_content_type_from_extension,
    is_valid_content_type,
    is_valid_upload,
    validate_magic_bytes,
)
from .processing import process_existing_scene_image as _process_existing_scene_image
from .processing import upload_scene_image as _upload_scene_image

if TYPE_CHECKING:
    from app.services.cloudinary.service import CloudinaryService

logger = get_logger(__name__)

OPTIMIZE_SETTINGS: dict[StorageFolder, tuple[int, int]] = {
    StorageFolder.AVATAR: (512, 85),
    StorageFolder.AGENT_AVATAR: (512, 85),
    StorageFolder.PROPERTY_IMAGE: (2048, 80),
    StorageFolder.BLOG_COVER: (2048, 80),
}


class StorageService:
    def __init__(self):
        # ``self.cloudinary`` is NOT resolved here: building the CloudinaryService
        # singleton loads the heavy ``cloudinary`` package (~12MB). It is resolved
        # lazily via the ``cloudinary`` property on first real use, so importing
        # this module (and the eager ``storage_service`` singleton below) does
        # not pull cloudinary into RAM at startup.
        self._cloudinary: CloudinaryService | None = None
        self._valid_image_types = VALID_IMAGE_TYPES
        self._valid_audio_types = VALID_AUDIO_TYPES
        self._valid_video_types = VALID_VIDEO_TYPES
        self._valid_document_types = VALID_DOCUMENT_TYPES
        self._max_upload_bytes = get_max_upload_bytes()

    @property
    def cloudinary(self) -> CloudinaryService:
        """Lazy CloudinaryService accessor — built on first call."""
        if self._cloudinary is None:
            self._cloudinary = get_cloudinary_service()
        return self._cloudinary

    # ============================================================
    # User-Scoped Upload Methods
    # ============================================================

    async def upload_with_path(
        self,
        file: UploadFile,
        *,
        user_id: int,
        folder: StorageFolder,
        db: AsyncSession | None = None,
        property_id: int | None = None,
        tour_id: str | None = None,
        scene_id: str | None = None,
        visibility: str = "private",
    ) -> dict[str, Any]:
        try:
            allow_documents = folder in (
                StorageFolder.PROPERTY_DOCUMENT,
                StorageFolder.DOCUMENT_LEASE,
                StorageFolder.DOCUMENT_MAINTENANCE,
                StorageFolder.DOCUMENT_GENERAL,
            )
            if not is_valid_upload(file, allow_documents=allow_documents):
                raise InvalidFileException(detail="Invalid file type")

            public_id = generate_cloudinary_public_id(
                folder=folder,
                original_filename=file.filename,
                user_id=user_id,
                property_id=property_id,
                tour_id=tour_id,
                scene_id=scene_id,
            )

            file_content = await file.read()

            # Magic-byte validation: reject spoofed content_type headers for
            # non-image types (PIL already validates images downstream).
            expected_type = expected_type_from_content_type(file.content_type)
            if expected_type and not validate_magic_bytes(file_content, expected_type):
                raise StorageException(
                    detail="Invalid file type",
                    error_code="INVALID_FILE_TYPE",
                )

            content_type = file.content_type
            is_image = content_type and content_type.startswith("image/")
            if is_image:
                try:
                    # Use folder-specific settings if available, otherwise defaults
                    max_dim, quality = OPTIMIZE_SETTINGS.get(folder, (2048, 80))
                    optimized_bytes, new_content_type = image_processing.optimize_for_web(
                        file_content,
                        max_dimension=max_dim,
                        quality=quality,
                    )
                    if new_content_type != content_type:
                        public_id = public_id.rsplit(".", 1)[0] + ".webp" if "." in public_id else public_id
                    file_content = optimized_bytes
                    content_type = new_content_type
                except Exception as exc:
                    logger.warning("Image optimization failed, uploading original: %s", exc)

            result = self.cloudinary.upload_file(
                file_bytes=file_content,
                public_id=public_id.split("/")[-1],
                folder="/".join(public_id.split("/")[:-1]),
                content_type=content_type or "application/octet-stream",
                is_image=is_image,
            )

            upload_result = {
                "file_path": result["public_id"],
                "public_url": result["secure_url"],
                "file_type": folder.name.lower(),
                "file_size": result["bytes"],
                "content_type": content_type or "application/octet-stream",
                "original_filename": file.filename,
            }

            media = None
            if db:
                media = await self._create_media_record(
                    db=db,
                    user_id=user_id,
                    upload_result=upload_result,
                    tour_id=tour_id,
                    visibility=visibility,
                    upload_status="complete",
                )

            return {**upload_result, "media": media}

        except BaseAPIException:
            raise
        except Exception:
            logger.exception("File upload error")
            raise StorageException(
                detail="File upload failed", error_code="UPLOAD_FAILED"
            ) from None

    # ============================================================
    # Legacy Upload Methods
    # ============================================================

    async def upload_property_image(
        self,
        file: UploadFile,
        property_id: int,
        user_id: int | None = None,
        db: AsyncSession | None = None,
    ) -> dict[str, Any]:
        if user_id:
            return await self.upload_with_path(
                file,
                user_id=user_id,
                folder=StorageFolder.PROPERTY_IMAGE,
                db=db,
                property_id=property_id,
                visibility="public",
            )
        return await self._upload_file(file, f"properties/{property_id}", "property_image")

    async def upload_user_avatar(
        self,
        file: UploadFile,
        user_id: int,
        db: AsyncSession | None = None,
    ) -> dict[str, Any]:
        return await self.upload_with_path(
            file,
            user_id=user_id,
            folder=StorageFolder.AVATAR,
            db=db,
            visibility="public",
        )

    async def upload_agent_avatar(
        self,
        file: UploadFile,
        agent_id: int,
        user_id: int | None = None,
    ) -> dict[str, Any]:
        try:
            if not is_valid_upload(file):
                raise InvalidFileException(detail="Invalid file type")

            file_content = await file.read()
            content_type = file.content_type or "application/octet-stream"

            # Magic-byte validation: reject spoofed content_type headers for
            # non-image types (PIL already validates images downstream).
            expected_type = expected_type_from_content_type(content_type)
            if expected_type and not validate_magic_bytes(file_content, expected_type):
                raise StorageException(
                    detail="Invalid file type",
                    error_code="INVALID_FILE_TYPE",
                )

            is_image = content_type.startswith("image/")

            # Optimize images to WebP before uploading
            if is_image:
                try:
                    max_dim, quality = OPTIMIZE_SETTINGS.get(
                        StorageFolder.AGENT_AVATAR, (512, 85)
                    )
                    optimized_bytes, new_content_type = image_processing.optimize_for_web(
                        file_content,
                        max_dimension=max_dim,
                        quality=quality,
                    )
                    file_content = optimized_bytes
                    content_type = new_content_type
                except Exception as exc:
                    logger.warning("Image optimization failed for agent avatar, uploading original: %s", exc)

            file_extension = get_file_extension(
                file.filename or "",
                content_type=content_type,
            )
            unique_name = f"{uuid.uuid4()}{file_extension}"

            result = self.cloudinary.upload_file(
                file_bytes=file_content,
                public_id=unique_name,
                folder=f"agents/{agent_id}/avatars",
                content_type=content_type,
                is_image=is_image,
            )

            return {
                "file_path": result["public_id"],
                "public_url": result["secure_url"],
                "file_type": "avatar",
                "file_size": result["bytes"],
                "content_type": content_type,
                "original_filename": file.filename,
            }

        except BaseAPIException:
            raise
        except Exception:
            logger.exception("Agent avatar upload error")
            raise StorageException(
                detail="File upload failed", error_code="UPLOAD_FAILED"
            ) from None

    async def upload_generic(
        self,
        file: UploadFile,
        folder: str = "uploads",
        user_id: int | None = None,
        db: AsyncSession | None = None,
    ) -> dict[str, Any]:
        if user_id:
            return await self.upload_with_path(
                file,
                user_id=user_id,
                folder=StorageFolder.GENERIC_UPLOAD,
                db=db,
                visibility="private",
            )
        return await self._upload_file(file, folder, "generic")

    async def upload_and_track(
        self,
        file: UploadFile,
        *,
        db: AsyncSession | None,
        user_id: int | None,
        folder: str = "uploads",
        tour_id: str | None = None,
        visibility: str = "private",
    ) -> dict[str, Any]:
        if user_id:
            return await self.upload_with_path(
                file,
                user_id=user_id,
                folder=StorageFolder.GENERIC_UPLOAD,
                db=db,
                tour_id=tour_id,
                visibility=visibility,
            )
        upload_result = await self._upload_file(file, folder, "generic")
        return {**upload_result, "media": None}

    async def upload_batch(
        self,
        files: list[UploadFile],
        *,
        db: AsyncSession | None,
        user_id: int | None,
        folder: str = "uploads",
        tour_id: str | None = None,
        visibility: str = "private",
    ) -> list[dict[str, Any]]:
        results = []
        for f in files:
            results.append(
                await self.upload_and_track(
                    f,
                    db=db,
                    user_id=user_id,
                    folder=folder,
                    tour_id=tour_id,
                    visibility=visibility,
                )
            )
        return results

    # ============================================================
    # Presigned Upload Methods
    # ============================================================

    async def create_presigned_upload(
        self,
        *,
        filename: str,
        content_type: str | None,
        file_size: int | None,
        user_id: int,
        db: AsyncSession,
        folder: StorageFolder = StorageFolder.GENERIC_UPLOAD,
        property_id: int | None = None,
        tour_id: str | None = None,
        scene_id: str | None = None,
        visibility: str = "private",
    ) -> dict[str, Any]:
        if not filename:
            raise BadRequestException(detail="Filename is required")

        if file_size is not None:
            try:
                parsed_size = int(file_size)
            except (TypeError, ValueError):
                raise BadRequestException(detail="Invalid file_size") from None
            if parsed_size < 0:
                raise BadRequestException(detail="Invalid file_size")
            if parsed_size > self._max_upload_bytes:
                raise FileTooLargeException(
                    detail=f"File too large. Maximum size is {self._max_upload_bytes // (1024 * 1024)}MB",
                )

        allow_documents = folder in (
            StorageFolder.PROPERTY_DOCUMENT,
            StorageFolder.DOCUMENT_LEASE,
            StorageFolder.DOCUMENT_MAINTENANCE,
            StorageFolder.DOCUMENT_GENERAL,
        )

        normalized_content_type = content_type or "application/octet-stream"
        if not is_valid_content_type(normalized_content_type, allow_documents=allow_documents):
            ext = os.path.splitext(filename)[1].lower()
            inferred = infer_content_type_from_extension(ext)
            if inferred and is_valid_content_type(inferred, allow_documents=allow_documents):
                normalized_content_type = inferred
            else:
                raise InvalidFileException(detail="Invalid file type")

        public_id = generate_cloudinary_public_id(
            folder=folder,
            original_filename=filename,
            user_id=user_id,
            property_id=property_id,
            tour_id=tour_id,
            scene_id=scene_id,
        )

        public_url = self.cloudinary.get_url(public_id)

        media = await self._create_media_record(
            db=db,
            user_id=user_id,
            upload_result={
                "file_path": public_id,
                "public_url": public_url,
                "file_type": folder.name.lower(),
                "file_size": file_size or 0,
                "content_type": normalized_content_type,
                "original_filename": filename,
            },
            tour_id=tour_id,
            visibility=visibility,
            upload_status="pending",
        )

        return {
            "upload_id": media.id,
            "signed_url": None,
            "token": None,
            "path": public_id,
            "public_url": public_url,
        }

    async def confirm_upload(
        self,
        *,
        db: AsyncSession,
        upload_id: str,
        user_id: int,
    ) -> MediaFile:
        query = select(MediaFile).where(
            MediaFile.id == upload_id,
            MediaFile.user_id == user_id,
        )
        result = await db.execute(query)
        media = result.scalar_one_or_none()

        if not media:
            raise NotFoundException(detail="Upload not found")

        if media.upload_status == "complete":
            return media

        file_info = self.cloudinary.get_file_info(media.storage_path or media.file_url)
        if not file_info:
            logger.warning("Upload confirmation failed: file not found at %s", media.storage_path)
            media.upload_status = "failed"
            await db.flush()
            raise NotFoundException(detail="File not found in storage")

        media.upload_status = "complete"
        media.is_processed = False
        await db.flush()
        await db.refresh(media)
        return media

    async def upload_document(
        self,
        file: UploadFile,
        user_id: int,
        db: AsyncSession | None = None,
    ) -> dict[str, Any]:
        return await self.upload_with_path(
            file,
            user_id=user_id,
            folder=StorageFolder.DOCUMENT_GENERAL,
            db=db,
            visibility="private",
        )

    # ============================================================
    # Scene Image Methods
    # ============================================================

    async def upload_scene_image(
        self,
        file: UploadFile,
        *,
        tour_id: str,
        scene_id: str,
        user_id: int,
        db: AsyncSession | None = None,
    ) -> dict[str, Any]:
        return await _upload_scene_image(
            self.cloudinary,
            file,
            tour_id=tour_id,
            scene_id=scene_id,
            user_id=user_id,
            create_media_record=self._create_media_record,
            db=db,
        )

    async def process_existing_scene_image(
        self,
        image_url: str,
        tour_id: str,
        scene_id: str,
        user_id: int,
    ) -> dict[str, Any]:
        return await _process_existing_scene_image(
            self.cloudinary,
            image_url,
            tour_id,
            scene_id,
            user_id,
        )

    # ============================================================
    # File Management Methods
    # ============================================================

    def delete_file(self, file_path: str, bucket_name: str | None = None) -> bool:
        try:
            public_id = self.cloudinary.extract_public_id_from_url(file_path)
            if public_id:
                return self.cloudinary.delete_file(public_id)
            return self.cloudinary.delete_file(file_path)
        except Exception as e:
            logger.error("File deletion error: %s", e)
            return False

    def get_file_url(self, file_path: str, bucket_name: str | None = None) -> str:
        return self.cloudinary.get_url(file_path)

    def extract_path_from_url(self, public_url: str, bucket_name: str | None = None) -> str | None:
        return self.cloudinary.extract_public_id_from_url(public_url)

    def list_files(self, folder: str, bucket_name: str | None = None) -> list[dict[str, Any]]:
        return []

    # ============================================================
    # Private Helper Methods
    # ============================================================

    async def _upload_file(
        self,
        file: UploadFile,
        folder: str,
        file_type: str,
        *,
        bucket_name: str | None = None,
        allow_documents: bool = False,
    ) -> dict[str, Any]:
        try:
            if not is_valid_upload(file, allow_documents=allow_documents):
                raise InvalidFileException(detail="Invalid file type")

            file_content = await file.read()
            content_type = file.content_type or "application/octet-stream"

            # Magic-byte validation: reject spoofed content_type headers for
            # non-image types (PIL already validates images downstream).
            expected_type = expected_type_from_content_type(content_type)
            if expected_type and not validate_magic_bytes(file_content, expected_type):
                raise StorageException(
                    detail="Invalid file type",
                    error_code="INVALID_FILE_TYPE",
                )

            is_image = content_type.startswith("image/")

            # Optimize images to WebP before uploading
            if is_image:
                try:
                    optimized_bytes, new_content_type = image_processing.optimize_for_web(
                        file_content,
                        max_dimension=2048,
                        quality=80,
                    )
                    file_content = optimized_bytes
                    content_type = new_content_type
                except Exception as exc:
                    logger.warning("Image optimization failed, uploading original: %s", exc)

            file_extension = get_file_extension(
                file.filename or "",
                content_type=content_type,
            )
            unique_name = f"{uuid.uuid4()}{file_extension}"

            result = self.cloudinary.upload_file(
                file_bytes=file_content,
                public_id=unique_name,
                folder=folder or None,
                content_type=content_type,
                is_image=is_image,
            )

            return {
                "file_path": result["public_id"],
                "public_url": result["secure_url"],
                "file_type": file_type,
                "file_size": result["bytes"],
                "content_type": content_type,
                "original_filename": file.filename,
            }

        except BaseAPIException:
            raise
        except Exception:
            logger.exception("File upload error")
            raise StorageException(
                detail="File upload failed", error_code="UPLOAD_FAILED"
            ) from None

    async def _create_media_record(
        self,
        *,
        db: AsyncSession,
        user_id: int,
        upload_result: dict[str, Any],
        tour_id: str | None = None,
        visibility: str = "private",
        upload_status: str = "complete",
    ) -> MediaFile:
        filename = os.path.basename(upload_result["file_path"])
        media = MediaFile(
            id=str(uuid.uuid4()),
            user_id=user_id,
            tour_id=tour_id,
            filename=filename,
            original_filename=upload_result.get("original_filename"),
            file_url=upload_result["public_url"],
            file_size=upload_result.get("file_size") or 0,
            mime_type=upload_result.get("content_type") or "application/octet-stream",
            folder=os.path.dirname(upload_result["file_path"]) or None,
            visibility=visibility,
            is_processed=False,
            processing_metadata=None,
            upload_status=upload_status,
            bucket_name="cloudinary",
            storage_path=upload_result["file_path"],
        )
        db.add(media)
        await db.flush()
        await db.refresh(media)
        return media

    def _is_valid_upload(self, file: UploadFile, *, allow_documents: bool = False) -> bool:
        return is_valid_upload(file, allow_documents=allow_documents)

    def _is_valid_content_type(self, content_type: str, *, allow_documents: bool = False) -> bool:
        return is_valid_content_type(content_type, allow_documents=allow_documents)

    def _infer_content_type_from_extension(self, ext: str) -> str | None:
        return infer_content_type_from_extension(ext)

    def _get_file_extension(self, filename: str, *, content_type: str | None = None) -> str:
        return get_file_extension(filename, content_type=content_type)

    async def delete_batch(
        self,
        db: AsyncSession,
        media_ids: list[str],
        actor: Any,
    ) -> dict[str, list[str]]:
        """Bulk-delete media files owned by ``actor``.

        Reuses the single-delete ownership rule: only media whose ``user_id``
        matches the actor are deleted. IDs that are not found or are owned by
        another user are returned in ``failed`` rather than aborting the batch.
        Underlying storage objects are best-effort deleted via ``delete_file``.
        """
        from app.schemas.storage import BatchDeleteResponse

        deleted: list[str] = []
        failed: list[str] = []

        if not media_ids:
            return BatchDeleteResponse(deleted=deleted, failed=failed).model_dump()

        # Deduplicate while preserving order.
        unique_ids: list[str] = []
        seen: set[str] = set()
        for mid in media_ids:
            if mid not in seen:
                seen.add(mid)
                unique_ids.append(mid)

        stmt = select(MediaFile).where(
            MediaFile.id.in_(unique_ids),
            MediaFile.user_id == actor.id,
        )
        result = await db.execute(stmt)
        owned = {m.id: m for m in result.scalars().all()}

        owned_set = set(owned.keys())
        # Requested but not owned/found → failed (preserve input order).
        for mid in unique_ids:
            if mid not in owned_set:
                failed.append(mid)

        for mid, media in owned.items():
            file_path: str | None = media.storage_path
            if not file_path and media.filename:
                file_path = (
                    f"{media.folder}/{media.filename}" if media.folder else media.filename
                )
            if file_path:
                bucket_name = media.bucket_name if media.bucket_name else None
                try:
                    self.delete_file(file_path, bucket_name=bucket_name)
                except Exception as e:  # noqa: BLE001
                    logger.error("Storage deletion failed for media %s: %s", mid, e)
            await db.delete(media)
            deleted.append(mid)

        await db.flush()
        return BatchDeleteResponse(deleted=deleted, failed=failed).model_dump()


storage_service = StorageService()
