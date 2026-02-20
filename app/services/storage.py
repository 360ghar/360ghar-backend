"""
Supabase Storage Service for handling file uploads and management.
This is the ONLY service that should use Supabase for data operations (storage).

All uploads are user-scoped under users/{user_id}/... path structure.
This enables proper RLS policies for client-side direct uploads.
"""
import os
import uuid
from typing import Any, Dict, List, Optional

from fastapi import HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_supabase_service_client
from app.core.config import settings
from app.core.logging import get_logger
from app.models.tours import MediaFile
from app.services import image_processing
from app.services.storage_paths import (
    StorageFolder,
    generate_storage_path,
    sanitize_filename,
)

logger = get_logger(__name__)


class StorageService:
    """Service for managing file storage using Supabase Storage.

    All uploads use a single unified bucket with user-scoped paths:
    - users/{user_id}/... for user content
    - agents/{agent_id}/... for agent avatars (public)
    """

    def __init__(self):
        # Server-side storage operations should use the service role key.
        self.supabase = get_supabase_service_client()
        self.bucket_name = settings.SUPABASE_STORAGE_BUCKET

        self._valid_image_types = {"image/jpeg", "image/jpg", "image/png", "image/webp", "image/gif"}
        self._valid_audio_types = {
            "audio/mpeg",
            "audio/mp3",
            "audio/wav",
            "audio/ogg",
            "audio/webm",
            "audio/aac",
            "audio/mp4",
        }
        self._valid_video_types = {
            "video/mp4",
            "video/webm",
            "video/quicktime",
            "video/x-matroska",
            "video/ogg",
        }
        self._valid_document_types = {
            "application/pdf",
            "application/msword",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        }
        self._max_upload_bytes = int(getattr(settings, "MAX_UPLOAD_SIZE_MB", 50)) * 1024 * 1024

    # ============================================================
    # User-Scoped Upload Methods (NEW)
    # ============================================================

    async def upload_with_path(
        self,
        file: UploadFile,
        *,
        user_id: int,
        folder: StorageFolder,
        db: Optional[AsyncSession] = None,
        property_id: Optional[int] = None,
        tour_id: Optional[str] = None,
        scene_id: Optional[str] = None,
        visibility: str = "private",
    ) -> Dict[str, Any]:
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
            if not self._is_valid_upload(file, allow_documents=allow_documents):
                raise HTTPException(status_code=400, detail="Invalid file type")

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
                    "upsert": False
                }
            )

            if hasattr(response, 'error') and response.error:
                logger.error(f"Storage upload error: {response.error}")
                raise HTTPException(status_code=500, detail="File upload failed")

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

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"File upload error: {str(e)}")
            raise HTTPException(status_code=500, detail=f"File upload failed: {str(e)}")

    # ============================================================
    # Legacy Upload Methods (maintained for backward compatibility)
    # ============================================================

    async def upload_property_image(
        self,
        file: UploadFile,
        property_id: int,
        user_id: Optional[int] = None,
        db: Optional[AsyncSession] = None,
    ) -> Dict[str, Any]:
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
        db: Optional[AsyncSession] = None,
    ) -> Dict[str, Any]:
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
        user_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Upload agent avatar (not user-scoped, at root level)."""
        # Agent avatars use a special path at the root level
        try:
            if not self._is_valid_upload(file):
                raise HTTPException(status_code=400, detail="Invalid file type")

            file_extension = self._get_file_extension(file.filename, content_type=file.content_type)
            unique_filename = f"{uuid.uuid4()}{file_extension}"
            file_path = f"agents/{agent_id}/avatars/{unique_filename}"

            file_content = await file.read()

            response = self.supabase.storage.from_(self.bucket_name).upload(
                path=file_path,
                file=file_content,
                file_options={
                    "content-type": file.content_type,
                    "cache-control": "3600",
                    "upsert": False
                }
            )

            if hasattr(response, 'error') and response.error:
                logger.error(f"Storage upload error: {response.error}")
                raise HTTPException(status_code=500, detail="File upload failed")

            public_url = self.supabase.storage.from_(self.bucket_name).get_public_url(file_path)

            return {
                "file_path": file_path,
                "public_url": public_url,
                "file_type": "avatar",
                "file_size": len(file_content),
                "content_type": file.content_type,
                "original_filename": file.filename
            }

        except Exception as e:
            logger.error(f"Agent avatar upload error: {str(e)}")
            raise HTTPException(status_code=500, detail=f"File upload failed: {str(e)}")

    async def upload_generic(
        self,
        file: UploadFile,
        folder: str = "uploads",
        user_id: Optional[int] = None,
        db: Optional[AsyncSession] = None,
    ) -> Dict[str, Any]:
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
        db: Optional[AsyncSession],
        user_id: Optional[int],
        folder: str = "uploads",
        tour_id: Optional[str] = None,
        visibility: str = "private",
    ) -> Dict[str, Any]:
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
        files: List[UploadFile],
        *,
        db: Optional[AsyncSession],
        user_id: Optional[int],
        folder: str = "uploads",
        tour_id: Optional[str] = None,
        visibility: str = "private",
    ) -> List[Dict[str, Any]]:
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
        content_type: Optional[str],
        file_size: Optional[int],
        user_id: int,
        db: AsyncSession,
        folder: StorageFolder = StorageFolder.GENERIC_UPLOAD,
        property_id: Optional[int] = None,
        tour_id: Optional[str] = None,
        scene_id: Optional[str] = None,
        visibility: str = "private",
    ) -> Dict[str, Any]:
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
            raise HTTPException(status_code=400, detail="Filename is required")

        if file_size is not None:
            try:
                parsed_size = int(file_size)
            except (TypeError, ValueError):
                raise HTTPException(status_code=400, detail="Invalid file_size") from None
            if parsed_size < 0:
                raise HTTPException(status_code=400, detail="Invalid file_size")
            if parsed_size > self._max_upload_bytes:
                raise HTTPException(
                    status_code=413,
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
        if not self._is_valid_content_type(normalized_content_type, allow_documents=allow_documents):
            ext = os.path.splitext(filename)[1].lower()
            inferred = self._infer_content_type_from_extension(ext)
            if inferred and self._is_valid_content_type(inferred, allow_documents=allow_documents):
                normalized_content_type = inferred
            else:
                raise HTTPException(status_code=400, detail="Invalid file type")

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
            HTTPException: If upload not found, not owned by user, or file not in storage
        """
        # Find the MediaFile record
        query = select(MediaFile).where(
            MediaFile.id == upload_id,
            MediaFile.user_id == user_id,
        )
        result = await db.execute(query)
        media = result.scalar_one_or_none()

        if not media:
            raise HTTPException(status_code=404, detail="Upload not found")

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
                logger.warning(f"Upload confirmation failed: file not found at {storage_path}")
                media.upload_status = "failed"
                await db.flush()
                raise HTTPException(status_code=404, detail="File not found in storage")

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error verifying upload: {str(e)}")
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
        db: Optional[AsyncSession] = None,
    ) -> Dict[str, Any]:
        """Upload a document (PDF, etc.) with user-scoped path."""
        return await self.upload_with_path(
            file,
            user_id=user_id,
            folder=StorageFolder.DOCUMENT_GENERAL,
            db=db,
            visibility="private",
        )

    # ============================================================
    # Scene Image Methods (360 Virtual Tours)
    # ============================================================

    async def upload_scene_image(
        self,
        file: UploadFile,
        *,
        tour_id: str,
        scene_id: str,
        user_id: int,
        db: Optional[AsyncSession] = None,
    ) -> Dict[str, Any]:
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
        try:
            # Validate file type
            if file.content_type not in self._valid_image_types:
                raise HTTPException(status_code=400, detail="Invalid image type")

            # Read file content
            file_content = await file.read()

            # Validate it's a 360 panorama (2:1 aspect ratio)
            is_panorama = image_processing.validate_360_panorama(file_content)
            if not is_panorama:
                logger.warning(f"Image may not be a valid 360 panorama for scene {scene_id}")

            # Get image info and EXIF
            image_info = image_processing.get_image_info(file_content)

            # Generate unique filenames with user-scoped paths
            file_id = str(uuid.uuid4())
            base_folder = f"users/{user_id}/tours/{tour_id}/scenes/{scene_id}"

            # Upload original image
            original_path = f"{base_folder}/original/{file_id}.jpg"
            original_result = self.supabase.storage.from_(self.bucket_name).upload(
                path=original_path,
                file=file_content,
                file_options={
                    "content-type": file.content_type,
                    "cache-control": "31536000",
                    "upsert": False
                }
            )

            if hasattr(original_result, 'error') and original_result.error:
                raise HTTPException(status_code=500, detail="Failed to upload original image")

            original_url = self.supabase.storage.from_(self.bucket_name).get_public_url(original_path)

            # Generate and upload thumbnail
            thumbnail_bytes = image_processing.generate_thumbnail(file_content, max_size=512)
            thumbnail_path = f"{base_folder}/thumbnail/{file_id}.webp"

            thumbnail_result = self.supabase.storage.from_(self.bucket_name).upload(
                path=thumbnail_path,
                file=thumbnail_bytes,
                file_options={
                    "content-type": "image/webp",
                    "cache-control": "31536000",
                    "upsert": False
                }
            )

            if hasattr(thumbnail_result, 'error') and thumbnail_result.error:
                logger.warning(f"Failed to upload thumbnail for scene {scene_id}")
                thumbnail_url = None
            else:
                thumbnail_url = self.supabase.storage.from_(self.bucket_name).get_public_url(thumbnail_path)

            # Generate and upload WebP optimized version
            web_bytes = image_processing.convert_to_webp(file_content, max_dimension=4096)
            web_path = f"{base_folder}/web/{file_id}.webp"

            web_result = self.supabase.storage.from_(self.bucket_name).upload(
                path=web_path,
                file=web_bytes,
                file_options={
                    "content-type": "image/webp",
                    "cache-control": "31536000",
                    "upsert": False
                }
            )

            if hasattr(web_result, 'error') and web_result.error:
                logger.warning(f"Failed to upload WebP version for scene {scene_id}")
                web_url = original_url
            else:
                web_url = self.supabase.storage.from_(self.bucket_name).get_public_url(web_path)

            # Track in database if available
            if db:
                await self._create_media_record(
                    db=db,
                    user_id=user_id,
                    upload_result={
                        "file_path": original_path,
                        "public_url": original_url,
                        "file_type": "scene_image",
                        "file_size": len(file_content),
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
                "file_size": len(file_content),
            }

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Scene image upload error: {str(e)}")
            raise HTTPException(status_code=500, detail=f"Scene image upload failed: {str(e)}")

    async def process_existing_scene_image(
        self,
        image_url: str,
        tour_id: str,
        scene_id: str,
        user_id: int,
    ) -> Dict[str, Any]:
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

            thumbnail_result = self.supabase.storage.from_(self.bucket_name).upload(
                path=thumbnail_path,
                file=thumbnail_bytes,
                file_options={
                    "content-type": "image/webp",
                    "cache-control": "31536000",
                    "upsert": False
                }
            )

            if hasattr(thumbnail_result, 'error') and thumbnail_result.error:
                logger.warning(f"Failed to upload thumbnail for scene {scene_id}")
                return {"thumbnail_url": None, "metadata": image_info}

            thumbnail_url = self.supabase.storage.from_(self.bucket_name).get_public_url(thumbnail_path)

            return {
                "thumbnail_url": thumbnail_url,
                "width": image_info["width"],
                "height": image_info["height"],
                "is_panorama": image_info.get("is_360_panorama", False),
                "exif": image_info.get("exif"),
            }

        except Exception as e:
            logger.error(f"Failed to process existing scene image: {str(e)}")
            return {"thumbnail_url": None, "error": str(e)}

    # ============================================================
    # File Management Methods
    # ============================================================

    def delete_file(self, file_path: str, bucket_name: Optional[str] = None) -> bool:
        """Delete file from Supabase Storage."""
        try:
            target_bucket = bucket_name or self.bucket_name
            response = self.supabase.storage.from_(target_bucket).remove([file_path])
            return not (hasattr(response, 'error') and response.error)
        except Exception as e:
            logger.error(f"File deletion error: {str(e)}")
            return False

    def get_file_url(self, file_path: str, bucket_name: Optional[str] = None) -> str:
        """Get public URL for file."""
        target_bucket = bucket_name or self.bucket_name
        return self.supabase.storage.from_(target_bucket).get_public_url(file_path)

    def list_files(self, folder: str, bucket_name: Optional[str] = None) -> List[Dict[str, Any]]:
        """List files in a folder."""
        try:
            target_bucket = bucket_name or self.bucket_name
            response = self.supabase.storage.from_(target_bucket).list(folder)
            if hasattr(response, 'error') and response.error:
                logger.error(f"Storage list error: {response.error}")
                return []
            return response or []
        except Exception as e:
            logger.error(f"File listing error: {str(e)}")
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
        bucket_name: Optional[str] = None,
        allow_documents: bool = False,
    ) -> Dict[str, Any]:
        """Legacy generic file upload method (non-user-scoped)."""
        try:
            # Validate file type
            if not self._is_valid_upload(file, allow_documents=allow_documents):
                raise HTTPException(status_code=400, detail="Invalid file type")

            # Generate unique filename
            file_extension = self._get_file_extension(file.filename, content_type=file.content_type)
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
                    "upsert": False
                }
            )

            if hasattr(response, 'error') and response.error:
                logger.error(f"Storage upload error: {response.error}")
                raise HTTPException(status_code=500, detail="File upload failed")

            # Get public URL
            public_url = self.supabase.storage.from_(target_bucket).get_public_url(file_path)

            return {
                "file_path": file_path,
                "public_url": public_url,
                "file_type": file_type,
                "file_size": len(file_content),
                "content_type": file.content_type,
                "original_filename": file.filename
            }

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"File upload error: {str(e)}")
            raise HTTPException(status_code=500, detail=f"File upload failed: {str(e)}")

    async def _create_media_record(
        self,
        *,
        db: AsyncSession,
        user_id: int,
        upload_result: Dict[str, Any],
        tour_id: Optional[str] = None,
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

    def _is_valid_upload(self, file: UploadFile, *, allow_documents: bool = False) -> bool:
        """Validate upload content types."""
        valid = set(self._valid_image_types) | set(self._valid_audio_types) | set(self._valid_video_types)
        if allow_documents:
            valid |= set(self._valid_document_types)
        return file.content_type in valid

    def _is_valid_content_type(self, content_type: str, *, allow_documents: bool = False) -> bool:
        valid = set(self._valid_image_types) | set(self._valid_audio_types) | set(self._valid_video_types)
        if allow_documents:
            valid |= set(self._valid_document_types)
        return content_type in valid

    def _infer_content_type_from_extension(self, ext: str) -> Optional[str]:
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

    def _get_file_extension(self, filename: str, *, content_type: Optional[str] = None) -> str:
        """Get file extension from filename, with a safe fallback by content-type."""
        if filename:
            ext = os.path.splitext(filename)[1]
            if ext:
                return ext

        if content_type == "application/pdf":
            return ".pdf"
        if content_type in self._valid_audio_types:
            return ".mp3"
        if content_type in self._valid_video_types:
            return ".mp4"
        return ".jpg"


# Global storage service instance
storage_service = StorageService()
