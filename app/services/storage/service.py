from __future__ import annotations

import os
import uuid
from typing import TYPE_CHECKING, Any

from fastapi import HTTPException, UploadFile
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    BadRequestException,
    BaseAPIException,
    FileTooLargeException,
    InvalidFileException,
    NotFoundException,
    ServiceUnavailableException,
    StorageException,
)
from app.core.logging import get_logger
from app.models.tours import MediaFile
from app.services import image_processing
from app.services.cloudinary import get_cloudinary_service
from app.services.cloudinary.service import StorageLookupError, delivery_from_url, resource_type_for
from app.services.storage_paths import (
    DOCUMENT_FOLDERS,
    StorageFolder,
    delivery_type_for_folder,
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
    read_upload_file_limited,
    validate_magic_bytes,
)
from .processing import process_existing_scene_image as _process_existing_scene_image
from .processing import upload_scene_image as _upload_scene_image

if TYPE_CHECKING:
    from app.services.cloudinary.service import CloudinaryService

logger = get_logger(__name__)

MAX_BATCH_UPLOAD_FILES = 20
# Total bytes across one batch. The per-file limit is MAX_UPLOAD_SIZE_MB.
MAX_BATCH_UPLOAD_TOTAL_BYTES = 200 * 1024 * 1024


def _upload_size(file: UploadFile) -> int:
    """Byte size of an upload. Uses the parsed size, else measures the stream. Rewinds it."""
    if file.size is not None:
        return file.size
    stream = file.file
    stream.seek(0, os.SEEK_END)
    size = stream.tell()
    stream.seek(0)
    return size


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
        """Upload one file to Cloudinary and, when ``db`` is set, record a MediaFile row.

        The folder sets the delivery type: document folders are ``authenticated``.
        ``visibility`` is the media library flag. It does not change delivery.
        """
        try:
            if not is_valid_upload(file, allow_documents=folder in DOCUMENT_FOLDERS):
                raise InvalidFileException(detail="Invalid file type")

            file_content = await self._read_upload_content(file)

            # Magic-byte validation: reject spoofed content_type headers for
            # non-image types (PIL already validates images downstream).
            expected_type = expected_type_from_content_type(file.content_type)
            if expected_type and not validate_magic_bytes(file_content, expected_type):
                raise InvalidFileException(
                    detail="Invalid file type", error_code="INVALID_FILE_TYPE"
                )

            content_type = file.content_type
            is_image = bool(content_type and content_type.startswith("image/"))
            if is_image:
                try:
                    # Use folder-specific settings if available, otherwise defaults
                    max_dim, quality = OPTIMIZE_SETTINGS.get(folder, (2048, 80))
                    optimized_bytes, new_content_type = image_processing.optimize_for_web(
                        file_content,
                        max_dimension=max_dim,
                        quality=quality,
                    )
                    file_content = optimized_bytes
                    content_type = new_content_type
                except Exception as exc:
                    logger.warning("Image optimization failed, uploading original: %s", exc)

            # The public id depends on the final content type (an optimized image is WebP).
            resource_type = resource_type_for(content_type or "application/octet-stream")
            public_id = generate_cloudinary_public_id(
                folder=folder,
                original_filename=file.filename,
                user_id=user_id,
                property_id=property_id,
                tour_id=tour_id,
                scene_id=scene_id,
                resource_type=resource_type,
            )
            delivery_type = delivery_type_for_folder(folder)
            delivery_options: dict[str, Any] = (
                {"type": delivery_type} if delivery_type != "upload" else {}
            )
            result = self.cloudinary.upload_file(
                file_bytes=file_content,
                public_id=public_id.split("/")[-1],
                folder="/".join(public_id.split("/")[:-1]),
                content_type=content_type or "application/octet-stream",
                is_image=is_image,
                **delivery_options,
            )
            # What Cloudinary stored. A PDF stays raw.
            resource_type = result.get("resource_type", resource_type)
            upload_result = {
                "file_path": result["public_id"],
                "public_url": result["secure_url"],
                "file_type": folder.name.lower(),
                "file_size": result["bytes"],
                "content_type": content_type or "application/octet-stream",
                "original_filename": file.filename,
                "width": result.get("width"),
                "height": result.get("height"),
                "resource_type": resource_type,
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

            file_content = await self._read_upload_content(file)
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
                    max_dim, quality = OPTIMIZE_SETTINGS.get(StorageFolder.AGENT_AVATAR, (512, 85))
                    optimized_bytes, new_content_type = image_processing.optimize_for_web(
                        file_content,
                        max_dimension=max_dim,
                        quality=quality,
                    )
                    file_content = optimized_bytes
                    content_type = new_content_type
                except Exception as exc:
                    logger.warning(
                        "Image optimization failed for agent avatar, uploading original: %s", exc
                    )

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
        user_id: int,
        folder: StorageFolder = StorageFolder.GENERIC_UPLOAD,
        tour_id: str | None = None,
        visibility: str = "private",
    ) -> dict[str, Any]:
        """Upload one file to the caller's folder and record it as a media row."""
        return await self.upload_with_path(
            file,
            user_id=user_id,
            folder=folder,
            db=db,
            tour_id=tour_id,
            visibility=visibility,
        )

    async def upload_batch(
        self,
        files: list[UploadFile],
        *,
        db: AsyncSession | None,
        user_id: int,
        folder: StorageFolder = StorageFolder.GENERIC_UPLOAD,
        tour_id: str | None = None,
        visibility: str = "private",
    ) -> list[dict[str, Any]]:
        """Upload several files. Returns one result per file, in request order.

        Every file is validated before the first Cloudinary call. One invalid
        file rejects the whole batch with 400 and nothing is uploaded. A
        Cloudinary failure on one file is reported for that file only.
        """
        if len(files) > MAX_BATCH_UPLOAD_FILES:
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "BATCH_TOO_MANY_FILES",
                    "message": f"Batch upload supports at most {MAX_BATCH_UPLOAD_FILES} files",
                },
            )
        total_bytes = sum(_upload_size(file) for file in files)
        if total_bytes > MAX_BATCH_UPLOAD_TOTAL_BYTES:
            raise FileTooLargeException(
                detail=(
                    "Batch is too large. Maximum total size is "
                    f"{MAX_BATCH_UPLOAD_TOTAL_BYTES // (1024 * 1024)}MB"
                ),
                error_code="BATCH_TOO_LARGE",
            )

        problems: list[dict[str, Any]] = []
        for index, file in enumerate(files):
            try:
                await self._validate_file(file, folder=folder)
            except BaseAPIException as exc:
                problems.append(
                    {
                        "index": index,
                        "filename": file.filename,
                        "code": exc.error_code,
                        "message": str(exc.detail),
                    }
                )
        if problems:
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "INVALID_FILE",
                    "message": "One or more files are invalid",
                    "files": problems,
                },
            )

        results: list[dict[str, Any]] = []
        for index, file in enumerate(files):
            try:
                upload = await self.upload_with_path(
                    file,
                    user_id=user_id,
                    folder=folder,
                    db=db,
                    tour_id=tour_id,
                    visibility=visibility,
                )
                results.append(
                    {
                        "index": index,
                        "filename": file.filename,
                        "status": "uploaded",
                        "result": upload,
                    }
                )
            except BaseAPIException as exc:
                results.append(
                    {
                        "index": index,
                        "filename": file.filename,
                        "status": "failed",
                        "error": {
                            "code": exc.error_code or "UPLOAD_FAILED",
                            "message": str(exc.detail),
                        },
                    }
                )
        return results

    async def _validate_file(self, file: UploadFile, *, folder: StorageFolder) -> None:
        """Check type, size and magic bytes without uploading. Rewinds the file."""
        if not is_valid_upload(file, allow_documents=folder in DOCUMENT_FOLDERS):
            raise InvalidFileException(detail="Invalid file type")
        content = await self._read_upload_content(file)
        expected_type = expected_type_from_content_type(file.content_type)
        if expected_type and not validate_magic_bytes(content, expected_type):
            raise InvalidFileException(detail="Invalid file type", error_code="INVALID_FILE_TYPE")
        await file.seek(0)

    # ============================================================
    # Presigned Upload Methods
    # ============================================================

    async def create_presigned_upload(
        self,
        *,
        filename: str,
        content_type: str | None,
        file_size: int,
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

        if file_size < 0:
            raise BadRequestException(detail="Invalid file_size")
        if file_size > self._max_upload_bytes:
            raise FileTooLargeException(
                detail=f"File too large. Maximum size is {self._max_upload_bytes // (1024 * 1024)}MB",
            )

        allow_documents = folder in DOCUMENT_FOLDERS

        normalized_content_type = content_type or "application/octet-stream"
        if not is_valid_content_type(normalized_content_type, allow_documents=allow_documents):
            ext = os.path.splitext(filename)[1].lower()
            inferred = infer_content_type_from_extension(ext)
            if inferred and is_valid_content_type(inferred, allow_documents=allow_documents):
                normalized_content_type = inferred
            else:
                raise InvalidFileException(detail="Invalid file type")

        # Use ONE public_id (rooted) end-to-end: sign it, store it on the
        # media row, and return it to the client. Previously the code signed a
        # rooted id but stored/returned the unrooted one, so confirm_upload's
        # get_file_info() looked up a nonexistent id and marked every direct
        # upload as failed.
        resource_type = resource_type_for(normalized_content_type)
        delivery_type = delivery_type_for_folder(folder)
        file_name_part = generate_cloudinary_public_id(
            folder=folder,
            original_filename=filename,
            user_id=user_id,
            property_id=property_id,
            tour_id=tour_id,
            scene_id=scene_id,
            resource_type=resource_type,
        )
        # generate_signed_upload_params adds the cloudinary root, so pass the unrooted id.
        signed_params = self.cloudinary.generate_signed_upload_params(
            public_id=file_name_part.split("/")[-1],
            folder="/".join(file_name_part.split("/")[:-1]),
            resource_type=resource_type,
            delivery_type=delivery_type,
        )
        full_public_id = signed_params["public_id"]

        public_url = self.cloudinary.get_url(
            full_public_id, resource_type=resource_type, delivery_type=delivery_type
        )

        media = await self._create_media_record(
            db=db,
            user_id=user_id,
            upload_result={
                "file_path": full_public_id,
                "public_url": public_url,
                "file_type": folder.name.lower(),
                "file_size": file_size,
                "content_type": normalized_content_type,
                "original_filename": filename,
            },
            tour_id=tour_id,
            visibility=visibility,
            upload_status="pending",
        )

        return {
            "upload_id": media.id,
            "signed_url": signed_params["upload_url"],
            "signature": signed_params["signature"],
            "api_key": signed_params["api_key"],
            "timestamp": signed_params["timestamp"],
            "public_id": full_public_id,
            "path": full_public_id,
            "public_url": public_url,
            "type": signed_params["type"],
        }

    async def confirm_upload(
        self,
        *,
        db: AsyncSession,
        upload_id: str,
        user_id: int,
    ) -> MediaFile:
        """Confirm a direct upload. Idempotent: a complete upload is returned as is.

        A failed check commits the ``failed`` status before the error is raised.
        The request rollback would otherwise discard it.
        """
        query = select(MediaFile).where(
            MediaFile.id == upload_id,
            MediaFile.user_id == user_id,
        )
        result = await db.execute(query)
        media = result.scalar_one_or_none()

        if not media:
            raise NotFoundException(detail="Upload not found", error_code="UPLOAD_NOT_FOUND")

        if media.upload_status == "complete":
            return media

        lookup_id = media.storage_path
        if not lookup_id and media.file_url:
            lookup_id = self.cloudinary.extract_public_id_from_url(media.file_url)
        delivery = self.delivery_kwargs(media)
        try:
            file_info = self.cloudinary.get_file_info(lookup_id, **delivery) if lookup_id else None
        except StorageLookupError as exc:
            # Cloudinary did not answer. Keep the row pending so the client can retry.
            logger.warning("Upload confirmation lookup failed for %s: %s", lookup_id, exc)
            raise ServiceUnavailableException(
                detail="Storage lookup failed. Retry later",
                error_code="STORAGE_LOOKUP_FAILED",
                headers={"Retry-After": "30"},
            ) from None
        if lookup_id is None or not file_info:
            logger.warning("Upload confirmation failed: file not found at %s", lookup_id)
            media.upload_status = "failed"
            await db.commit()
            raise NotFoundException(
                detail="File not found in storage", error_code="UPLOAD_NOT_IN_STORAGE"
            )

        stored_bytes = file_info.get("bytes")
        if stored_bytes is not None and int(stored_bytes) != int(media.file_size):
            # The client declared a size that the stored object does not match.
            # Cloudinary does not bind the size at presign time, so check it here.
            # A declared size of 0 is checked too.
            self.cloudinary.delete_file(lookup_id, **delivery)
            media.upload_status = "failed"
            await db.commit()
            raise BadRequestException(
                detail="Uploaded file size does not match the declared size",
                error_code="UPLOAD_SIZE_MISMATCH",
            )

        media.upload_status = "complete"
        media.is_processed = False
        if stored_bytes is not None:
            media.file_size = int(stored_bytes)
        media.width = file_info.get("width")
        media.height = file_info.get("height")
        await db.flush()
        await db.refresh(media)
        return media

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

    def delete_file(
        self,
        file_path: str,
        bucket_name: str | None = None,
        *,
        resource_type: str = "image",
        delivery_type: str = "upload",
    ) -> bool:
        """Delete one stored asset. Rows of document folders pass ``delivery_kwargs(media)``."""
        try:
            public_id = self.cloudinary.extract_public_id_from_url(file_path) or file_path
            return self.cloudinary.delete_file(
                public_id, resource_type=resource_type, delivery_type=delivery_type
            )
        except Exception as e:
            logger.error("File deletion error: %s", e)
            return False

    def delivery_kwargs(self, media: MediaFile) -> dict[str, str]:
        """Resource type and delivery type a stored asset was created with.

        The stored URL carries both, so an authenticated document is found and removed.
        A row without a Cloudinary URL falls back to its MIME type and the upload type.
        """
        parsed = delivery_from_url(media.file_url)
        if parsed is None:
            return {
                "resource_type": resource_type_for(media.mime_type or ""),
                "delivery_type": "upload",
            }
        return {"resource_type": parsed[0], "delivery_type": parsed[1]}

    def get_file_url(self, file_path: str, bucket_name: str | None = None) -> str:
        return self.cloudinary.get_url(file_path)

    def extract_path_from_url(self, public_url: str, bucket_name: str | None = None) -> str | None:
        return self.cloudinary.extract_public_id_from_url(public_url)

    # ============================================================
    # Private Helper Methods
    # ============================================================

    async def _read_upload_content(self, file: UploadFile) -> bytes:
        return await read_upload_file_limited(file, self._max_upload_bytes)

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

            file_content = await self._read_upload_content(file)
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
            width=upload_result.get("width"),
            height=upload_result.get("height"),
            mime_type=upload_result.get("content_type") or "application/octet-stream",
            folder=os.path.dirname(upload_result["file_path"]) or None,
            visibility=visibility,
            is_processed=False,
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

        Each entry may be a ``MediaFile.id`` (UUID) or a full ``public_url``.
        Only media whose ``user_id`` matches the actor are deleted. IDs/URLs
        that are not found or are owned by another user are returned in
        ``failed`` rather than aborting the batch. Underlying storage objects
        are best-effort deleted via ``delete_file``.
        """
        from app.schemas.storage import BatchDeleteResponse

        deleted: list[str] = []
        failed: list[str] = []
        storage_warnings: list[str] = []

        if not media_ids:
            return BatchDeleteResponse(
                deleted=deleted, failed=failed, storage_warnings=storage_warnings
            ).model_dump()

        # Deduplicate while preserving order.
        unique_inputs: list[str] = []
        seen: set[str] = set()
        for mid in media_ids:
            if mid not in seen:
                seen.add(mid)
                unique_inputs.append(mid)

        id_inputs: list[str] = []
        url_inputs: list[str] = []
        for item in unique_inputs:
            if item.startswith(("http://", "https://")):
                url_inputs.append(item)
            else:
                id_inputs.append(item)

        or_conditions: list[Any] = []
        if id_inputs:
            or_conditions.append(MediaFile.id.in_(id_inputs))
        if url_inputs:
            or_conditions.append(MediaFile.file_url.in_(url_inputs))

        by_id: dict[str, MediaFile] = {}
        by_url: dict[str, MediaFile] = {}
        if or_conditions:
            stmt = select(MediaFile).where(
                MediaFile.user_id == actor.id,
                or_(*or_conditions),
            )
            result = await db.execute(stmt)
            for media in result.scalars().all():
                by_id[media.id] = media
                if media.file_url:
                    by_url[media.file_url] = media

        deleted_media: set[str] = set()
        failed_media: set[str] = set()
        for item in unique_inputs:
            # Prefer URL lookup when the request string is a URL; otherwise id.
            found: MediaFile | None = by_url.get(item) or by_id.get(item)
            if found is None:
                failed.append(item)
                continue
            if found.id in failed_media:
                failed.append(item)
                continue
            if found.id in deleted_media:
                # Same media was referenced twice (once by id and once by URL).
                # Echo the original request identifier for client correlation.
                deleted.append(item)
                continue

            file_path: str | None = found.storage_path
            if not file_path and found.filename:
                file_path = f"{found.folder}/{found.filename}" if found.folder else found.filename
            if file_path:
                bucket_name = found.bucket_name if found.bucket_name else None
                try:
                    removed = self.delete_file(
                        file_path, bucket_name=bucket_name, **self.delivery_kwargs(found)
                    )
                except Exception as e:  # noqa: BLE001
                    logger.error("Storage deletion failed for media %s: %s", found.id, e)
                    removed = False
                if not removed:
                    # The stored object still exists. Keep the row so it is not orphaned,
                    # and report the id as failed (with a warning) for a retry.
                    failed_media.add(found.id)
                    failed.append(item)
                    storage_warnings.append(found.id)
                    continue
            deleted_media.add(found.id)
            await db.delete(found)
            # Always echo the original request item (id or URL), not found.id.
            deleted.append(item)

        await db.flush()
        return BatchDeleteResponse(
            deleted=deleted, failed=failed, storage_warnings=storage_warnings
        ).model_dump()


storage_service = StorageService()
