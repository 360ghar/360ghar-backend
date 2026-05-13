"""
StorageService — core upload, delete, and list operations.

The class delegates validation to ``helpers`` and scene-image processing to
``processing``, keeping the public API identical to the original monolith.
"""
import os
import uuid
from typing import Any

from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.auth import get_supabase_storage_client
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
from app.services.storage_paths import (
    StorageFolder,
    generate_storage_path,
)

from .helpers import (
    VALID_AUDIO_TYPES,
    VALID_DOCUMENT_TYPES,
    VALID_IMAGE_TYPES,
    VALID_VIDEO_TYPES,
    get_file_extension,
    get_max_upload_bytes,
    infer_content_type_from_extension,
    is_valid_content_type,
    is_valid_upload,
)
from .processing import process_existing_scene_image as _process_existing_scene_image
from .processing import upload_scene_image as _upload_scene_image

logger = get_logger(__name__)


class StorageService:
    """Service for managing file storage using Supabase Storage.

    All uploads use a single unified bucket with user-scoped paths:
    - users/{user_id}/... for user content
    - agents/{agent_id}/... for agent avatars (public)
    """

    def __init__(self):
        # Server-side storage operations should use the service role key.
        self.supabase = get_supabase_storage_client()
        self.bucket_name = settings.SUPABASE_STORAGE_BUCKET

        self._valid_image_types = VALID_IMAGE_TYPES
        self._valid_audio_types = VALID_AUDIO_TYPES
        self._valid_video_types = VALID_VIDEO_TYPES
        self._valid_document_types = VALID_DOCUMENT_TYPES
        self._max_upload_bytes = get_max_upload_bytes()

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
        """
        Upload a file with user-scoped path using StorageFolder enum.

        This is the recommended method for all new uploads.

        Args:
            file: The file to upload
            user_id: User ID for path scoping
            folder: StorageFolder enum defining the folder structure
            db: Database session for MediaFile tracking
            property_id: Required for PROPERTY_* folders
            tour_id: Required for TOUR_* and SCENE_* folders
            scene_id: Required for SCENE_* folders
            visibility: "private" or "public"

        Returns:
            Dict with file_path, public_url, file_size, media record, etc.
        """
        try:
            # Validate file type
            allow_documents = folder in (
                StorageFolder.PROPERTY_DOCUMENT,
                StorageFolder.DOCUMENT_LEASE,
                StorageFolder.DOCUMENT_MAINTENANCE,
                StorageFolder.DOCUMENT_GENERAL,
            )
            if not is_valid_upload(file, allow_documents=allow_documents):
                raise InvalidFileException(detail="Invalid file type")

            # Generate user-scoped path
            file_path = generate_storage_path(
                user_id=user_id,
                folder=folder,
                original_filename=file.filename,
                property_id=property_id,
                tour_id=tour_id,
                scene_id=scene_id,
            )

            # Read file content
            file_content = await file.read()

            # Upload to storage
            response = self.supabase.storage.from_(self.bucket_name).upload(
                path=file_path,
                file=file_content,
                file_options={
                    "content-type": file.content_type,
                    "cache-control": "3600",
                    "upsert": False,
                },
            )

            if hasattr(response, "error") and response.error:
                logger.error("Storage upload error: %s", response.error)
                raise StorageException(detail="File upload failed")

            # Get public URL
            public_url = self.supabase.storage.from_(self.bucket_name).get_public_url(file_path)

            upload_result = {
                "file_path": file_path,
                "public_url": public_url,
                "file_type": folder.name.lower(),
                "file_size": len(file_content),
                "content_type": file.content_type,
                "original_filename": file.filename,
            }

            # Create MediaFile record if db is available
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

            return {
                **upload_result,
                "media": media,
            }

        except BaseAPIException:
            raise
        except Exception as e:
            logger.error("File upload error: %s", e)
            raise StorageException(detail=f"File upload failed: {str(e)}") from None

    # ============================================================
    # Legacy Upload Methods (maintained for backward compatibility)
    # ============================================================

    async def upload_property_image(
        self,
        file: UploadFile,
        property_id: int,
        user_id: int | None = None,
        db: AsyncSession | None = None,
    ) -> dict[str, Any]:
        """Upload property image with user-scoped path."""
        if user_id:
            return await self.upload_with_path(
                file,
                user_id=user_id,
                folder=StorageFolder.PROPERTY_IMAGE,
                db=db,
                property_id=property_id,
                visibility="public",
            )
        # Legacy fallback (no user_id)
        return await self._upload_file(file, f"properties/{property_id}", "property_image")

    async def upload_user_avatar(
        self,
        file: UploadFile,
        user_id: int,
        db: AsyncSession | None = None,
    ) -> dict[str, Any]:
        """Upload user avatar with user-scoped path."""
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
        """Upload agent avatar (not user-scoped, at root level)."""
        # Agent avatars use a special path at the root level
        try:
            if not is_valid_upload(file):
                raise InvalidFileException(detail="Invalid file type")

            file_extension = get_file_extension(file.filename or "", content_type=file.content_type)
            unique_filename = f"{uuid.uuid4()}{file_extension}"
            file_path = f"agents/{agent_id}/avatars/{unique_filename}"

            file_content = await file.read()

            response = self.supabase.storage.from_(self.bucket_name).upload(
                path=file_path,
                file=file_content,
                file_options={
                    "content-type": file.content_type,
                    "cache-control": "3600",
                    "upsert": False,
                },
            )

            if hasattr(response, "error") and response.error:
                logger.error("Storage upload error: %s", response.error)
                raise StorageException(detail="File upload failed")

            public_url = self.supabase.storage.from_(self.bucket_name).get_public_url(file_path)

            return {
                "file_path": file_path,
                "public_url": public_url,
                "file_type": "avatar",
                "file_size": len(file_content),
                "content_type": file.content_type,
                "original_filename": file.filename,
            }

        except BaseAPIException:
            raise
        except Exception as e:
            logger.error("Agent avatar upload error: %s", e)
            raise StorageException(detail=f"File upload failed: {str(e)}") from None

    async def upload_generic(
        self,
        file: UploadFile,
        folder: str = "uploads",
        user_id: int | None = None,
        db: AsyncSession | None = None,
    ) -> dict[str, Any]:
        """Generic upload for dashboard and misc files."""
        if user_id:
            return await self.upload_with_path(
                file,
                user_id=user_id,
                folder=StorageFolder.GENERIC_UPLOAD,
                db=db,
                visibility="private",
            )
        # Legacy fallback
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
        """Upload a file and create a MediaFile record when DB context is available."""
        if user_id:
            return await self.upload_with_path(
                file,
                user_id=user_id,
                folder=StorageFolder.GENERIC_UPLOAD,
                db=db,
                tour_id=tour_id,
                visibility=visibility,
            )
        # Legacy fallback (no user_id)
        upload_result = await self._upload_file(file, folder, "generic")
        return {
            **upload_result,
            "media": None,
        }

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
        """Upload multiple files with optional MediaFile tracking."""
        results = []
        for file in files:
            results.append(
                await self.upload_and_track(
                    file,
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
        """
        Create a presigned upload URL for direct client-side uploads.

        Always creates a MediaFile record in 'pending' status.
        Client should call confirm_upload() after upload completes.

        Args:
            filename: Original filename
            content_type: MIME type
            file_size: Expected file size in bytes
            user_id: User ID for path scoping (REQUIRED)
            db: Database session (REQUIRED)
            folder: StorageFolder enum for path structure
            property_id: Required for property-related folders
            tour_id: Required for tour-related folders
            scene_id: Required for scene-related folders
            visibility: "private" or "public"

        Returns:
            Dict with upload_id, signed_url, token, path, public_url
        """
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

        # Determine if documents are allowed for this folder
        allow_documents = folder in (
            StorageFolder.PROPERTY_DOCUMENT,
            StorageFolder.DOCUMENT_LEASE,
            StorageFolder.DOCUMENT_MAINTENANCE,
            StorageFolder.DOCUMENT_GENERAL,
        )

        # Validate content type
        normalized_content_type = content_type or "application/octet-stream"
        if not is_valid_content_type(normalized_content_type, allow_documents=allow_documents):
            ext = os.path.splitext(filename)[1].lower()
            inferred = infer_content_type_from_extension(ext)
            if inferred and is_valid_content_type(inferred, allow_documents=allow_documents):
                normalized_content_type = inferred
            else:
                raise InvalidFileException(detail="Invalid file type")

        # Generate user-scoped path
        file_path = generate_storage_path(
            user_id=user_id,
            folder=folder,
            original_filename=filename,
            property_id=property_id,
            tour_id=tour_id,
            scene_id=scene_id,
        )

        # Create signed upload URL
        signed = self.supabase.storage.from_(self.bucket_name).create_signed_upload_url(file_path)
        public_url = self.supabase.storage.from_(self.bucket_name).get_public_url(file_path)

        # Create MediaFile in pending state
        media = await self._create_media_record(
            db=db,
            user_id=user_id,
            upload_result={
                "file_path": file_path,
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
            "signed_url": signed.get("signed_url") or signed.get("signedUrl"),
            "token": signed.get("token"),
            "path": file_path,
            "public_url": public_url,
        }

    async def confirm_upload(
        self,
        *,
        db: AsyncSession,
        upload_id: str,
        user_id: int,
    ) -> MediaFile:
        """
        Confirm a client-side upload completed successfully.

        Called by client after direct upload to storage completes.
        Verifies the file exists and updates MediaFile status.

        Args:
            db: Database session
            upload_id: MediaFile ID from create_presigned_upload
            user_id: User ID for ownership verification

        Returns:
            Updated MediaFile record

        Raises:
            NotFoundException: If upload not found, not owned by user, or file not in storage
        """
        # Find the MediaFile record
        query = select(MediaFile).where(
            MediaFile.id == upload_id,
            MediaFile.user_id == user_id,
        )
        result = await db.execute(query)
        media = result.scalar_one_or_none()

        if not media:
            raise NotFoundException(detail="Upload not found")

        if media.upload_status == "complete":
            return media  # Already confirmed

        # Verify file exists in storage
        storage_path = media.storage_path or (f"{media.folder}/{media.filename}" if media.folder else media.filename)
        try:
            # Try to get file info to verify it exists
            file_list = self.supabase.storage.from_(self.bucket_name).list(
                os.path.dirname(storage_path) or ""
            )
            filename = os.path.basename(storage_path)
            file_exists = any(f.get("name") == filename for f in (file_list or []))

            if not file_exists:
                logger.warning("Upload confirmation failed: file not found at %s", storage_path)
                media.upload_status = "failed"
                await db.flush()
                raise NotFoundException(detail="File not found in storage")

        except BaseAPIException:
            raise
        except Exception as e:
            logger.error("Error verifying upload: %s", e)
            # Don't fail the confirmation if we can't verify - the file may still be there

        # Update status to complete
        media.upload_status = "complete"
        media.is_processed = False  # Mark for any post-processing if needed

        await db.flush()
        await db.refresh(media)

        return media

    async def upload_document(
        self,
        file: UploadFile,
        user_id: int,
        db: AsyncSession | None = None,
    ) -> dict[str, Any]:
        """Upload a document (PDF, etc.) with user-scoped path."""
        return await self.upload_with_path(
            file,
            user_id=user_id,
            folder=StorageFolder.DOCUMENT_GENERAL,
            db=db,
            visibility="private",
        )

    # ============================================================
    # Scene Image Methods (360 Virtual Tours) — delegated to processing.py
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
        """
        Upload a 360 scene image with automatic thumbnail generation.

        Uses user-scoped path: users/{user_id}/tours/{tour_id}/scenes/{scene_id}/...

        Args:
            file: The image file to upload
            tour_id: The tour ID
            scene_id: The scene ID
            user_id: User ID for path scoping (REQUIRED)
            db: Database session for tracking

        Returns:
            Dict with image_url, thumbnail_url, web_url, and metadata
        """
        return await _upload_scene_image(
            self.supabase,
            self.bucket_name,
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
        """
        Process an existing scene image URL to generate thumbnails.

        Uses user-scoped path for generated files.

        Args:
            image_url: URL of the existing image
            tour_id: Tour ID
            scene_id: Scene ID
            user_id: User ID for path scoping

        Returns:
            Dict with thumbnail_url and metadata
        """
        return await _process_existing_scene_image(
            self.supabase,
            self.bucket_name,
            image_url,
            tour_id,
            scene_id,
            user_id,
        )

    # ============================================================
    # File Management Methods
    # ============================================================

    def delete_file(self, file_path: str, bucket_name: str | None = None) -> bool:
        """Delete file from Supabase Storage."""
        try:
            target_bucket = bucket_name or self.bucket_name
            response = self.supabase.storage.from_(target_bucket).remove([file_path])
            return not (hasattr(response, "error") and response.error)
        except Exception as e:
            logger.error("File deletion error: %s", e)
            return False

    def get_file_url(self, file_path: str, bucket_name: str | None = None) -> str:
        """Get public URL for file."""
        target_bucket = bucket_name or self.bucket_name
        return str(self.supabase.storage.from_(target_bucket).get_public_url(file_path))

    def list_files(self, folder: str, bucket_name: str | None = None) -> list[dict[str, Any]]:
        """List files in a folder."""
        try:
            target_bucket = bucket_name or self.bucket_name
            response = self.supabase.storage.from_(target_bucket).list(folder)
            if hasattr(response, "error") and response.error:
                logger.error("Storage list error: %s", response.error)
                return []
            return response or []
        except Exception as e:
            logger.error("File listing error: %s", e)
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
        """Legacy generic file upload method (non-user-scoped)."""
        try:
            # Validate file type
            if not is_valid_upload(file, allow_documents=allow_documents):
                raise InvalidFileException(detail="Invalid file type")

            # Generate unique filename
            file_extension = get_file_extension(file.filename or "", content_type=file.content_type)
            unique_filename = f"{uuid.uuid4()}{file_extension}"
            file_path = f"{folder}/{unique_filename}"

            # Read file content
            file_content = await file.read()

            # Upload to Supabase Storage
            target_bucket = bucket_name or self.bucket_name
            response = self.supabase.storage.from_(target_bucket).upload(
                path=file_path,
                file=file_content,
                file_options={
                    "content-type": file.content_type,
                    "cache-control": "3600",
                    "upsert": False,
                },
            )

            if hasattr(response, "error") and response.error:
                logger.error("Storage upload error: %s", response.error)
                raise StorageException(detail="File upload failed")

            # Get public URL
            public_url = self.supabase.storage.from_(target_bucket).get_public_url(file_path)

            return {
                "file_path": file_path,
                "public_url": public_url,
                "file_type": file_type,
                "file_size": len(file_content),
                "content_type": file.content_type,
                "original_filename": file.filename,
            }

        except BaseAPIException:
            raise
        except Exception as e:
            logger.error("File upload error: %s", e)
            raise StorageException(detail=f"File upload failed: {str(e)}") from None

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
        """Persist media metadata for uploads."""
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
            # New tracking fields
            upload_status=upload_status,
            bucket_name=self.bucket_name,
            storage_path=upload_result["file_path"],
        )
        db.add(media)
        await db.flush()
        await db.refresh(media)
        return media

    # Backward-compatible wrappers so that callers who reach the
    # private validation helpers still get the same behaviour.
    def _is_valid_upload(self, file: UploadFile, *, allow_documents: bool = False) -> bool:
        """Validate upload content types (delegates to helpers)."""
        return is_valid_upload(file, allow_documents=allow_documents)

    def _is_valid_content_type(self, content_type: str, *, allow_documents: bool = False) -> bool:
        """Validate a content-type string (delegates to helpers)."""
        return is_valid_content_type(content_type, allow_documents=allow_documents)

    def _infer_content_type_from_extension(self, ext: str) -> str | None:
        """Infer MIME type from extension (delegates to helpers)."""
        return infer_content_type_from_extension(ext)

    def _get_file_extension(self, filename: str, *, content_type: str | None = None) -> str:
        """Get file extension (delegates to helpers)."""
        return get_file_extension(filename, content_type=content_type)


# Global storage service instance
storage_service = StorageService()
