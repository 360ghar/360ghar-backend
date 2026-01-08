"""
Supabase Storage Service for handling file uploads and management.
This is the ONLY service that should use Supabase for data operations (storage).
"""
import asyncio
import os
import uuid
from typing import Any, Dict, List, Optional

from fastapi import HTTPException, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_supabase_auth_client
from app.core.config import settings
from app.core.logging import get_logger
from app.models.tours import MediaFile
from app.services import image_processing

logger = get_logger(__name__)

class StorageService:
    """Service for managing file storage using Supabase Storage"""
    
    def __init__(self):
        self.supabase = get_supabase_auth_client()
        self.bucket_name = settings.SUPABASE_STORAGE_BUCKET
        self.documents_bucket_name = settings.SUPABASE_DOCUMENTS_BUCKET

        self._valid_image_types = {"image/jpeg", "image/jpg", "image/png", "image/webp", "image/gif"}
        self._valid_video_types = {
            "video/mp4",
            "video/webm",
            "video/quicktime",
            "video/x-matroska",
            "video/ogg",
        }
        self._valid_document_types = {
            "application/pdf",
            # Office formats (optional; safe defaults)
            "application/msword",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        }
    
    async def upload_property_image(self, file: UploadFile, property_id: int) -> Dict[str, Any]:
        """Upload property image to Supabase Storage"""
        return await self._upload_file(file, f"properties/{property_id}", "property_image")
    
    async def upload_user_avatar(self, file: UploadFile, user_id: int) -> Dict[str, Any]:
        """Upload user avatar to Supabase Storage"""
        return await self._upload_file(file, f"users/{user_id}", "avatar")
    
    async def upload_agent_avatar(self, file: UploadFile, agent_id: int) -> Dict[str, Any]:
        """Upload agent avatar to Supabase Storage"""
        return await self._upload_file(file, f"agents/{agent_id}", "avatar")
    
    async def upload_generic(self, file: UploadFile, folder: str = "uploads") -> Dict[str, Any]:
        """Generic upload for dashboard and misc files"""
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
        upload_result = await self._upload_file(file, folder, "generic")
        media = None
        if db and user_id:
            media = await self._create_media_record(
                db=db,
                user_id=user_id,
                upload_result=upload_result,
                tour_id=tour_id,
                visibility=visibility,
            )
        return {
            **upload_result,
            "media": media,
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

    async def create_presigned_upload(
        self,
        *,
        filename: str,
        content_type: Optional[str],
        file_size: Optional[int],
        db: Optional[AsyncSession],
        user_id: Optional[int],
        folder: str = "uploads",
        tour_id: Optional[str] = None,
        visibility: str = "private",
        bucket_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create a presigned upload URL and an optional MediaFile record."""
        if not filename:
            raise HTTPException(status_code=400, detail="Filename is required")

        file_extension = self._get_file_extension(filename, content_type=content_type)
        unique_filename = f"{uuid.uuid4()}{file_extension}"
        file_path = f"{folder}/{unique_filename}"
        target_bucket = bucket_name or self.bucket_name

        signed = self.supabase.storage.from_(target_bucket).create_signed_upload_url(file_path)
        public_url = self.supabase.storage.from_(target_bucket).get_public_url(file_path)

        media = None
        if db and user_id:
            media = await self._create_media_record(
                db=db,
                user_id=user_id,
                upload_result={
                    "file_path": file_path,
                    "public_url": public_url,
                    "file_type": "generic",
                    "file_size": file_size or 0,
                    "content_type": content_type or "application/octet-stream",
                    "original_filename": filename,
                },
                tour_id=tour_id,
                visibility=visibility,
            )

        return {
            "signed_url": signed.get("signed_url") or signed.get("signedUrl"),
            "token": signed.get("token"),
            "path": file_path,
            "public_url": public_url,
            "media": media,
        }

    async def upload_document(self, file: UploadFile, folder: str = "documents") -> Dict[str, Any]:
        """Upload a document (PDF, etc.) to the documents bucket."""
        return await self._upload_file(
            file,
            folder,
            "document",
            bucket_name=self.documents_bucket_name,
            allow_documents=True,
        )
    
    async def _upload_file(
        self,
        file: UploadFile,
        folder: str,
        file_type: str,
        *,
        bucket_name: Optional[str] = None,
        allow_documents: bool = False,
    ) -> Dict[str, Any]:
        """Generic file upload method"""
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
        )
        db.add(media)
        await db.flush()
        await db.refresh(media)
        return media
    
    def delete_file(self, file_path: str) -> bool:
        """Delete file from Supabase Storage"""
        try:
            response = self.supabase.storage.from_(self.bucket_name).remove([file_path])
            return not (hasattr(response, 'error') and response.error)
        except Exception as e:
            logger.error(f"File deletion error: {str(e)}")
            return False
    
    def get_file_url(self, file_path: str) -> str:
        """Get public URL for file"""
        return self.supabase.storage.from_(self.bucket_name).get_public_url(file_path)
    
    def list_files(self, folder: str) -> List[Dict[str, Any]]:
        """List files in a folder"""
        try:
            response = self.supabase.storage.from_(self.bucket_name).list(folder)
            if hasattr(response, 'error') and response.error:
                logger.error(f"Storage list error: {response.error}")
                return []
            return response or []
        except Exception as e:
            logger.error(f"File listing error: {str(e)}")
            return []
    
    def _is_valid_upload(self, file: UploadFile, *, allow_documents: bool = False) -> bool:
        """Validate upload content types.

        By default we accept images/videos (property media). For the property
        management document vault, we also allow PDFs (and optional office docs).
        """
        valid = set(self._valid_image_types) | set(self._valid_video_types)
        if allow_documents:
            valid |= set(self._valid_document_types)
        return file.content_type in valid
    
    def _get_file_extension(self, filename: str, *, content_type: Optional[str] = None) -> str:
        """Get file extension from filename, with a safe fallback by content-type."""
        if filename:
            ext = os.path.splitext(filename)[1]
            if ext:
                return ext

        if content_type == "application/pdf":
            return ".pdf"
        if content_type in self._valid_video_types:
            return ".mp4"
        return ".jpg"

    async def upload_scene_image(
        self,
        file: UploadFile,
        *,
        tour_id: str,
        scene_id: str,
        db: Optional[AsyncSession] = None,
        user_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Upload a 360 scene image with automatic thumbnail generation.

        Args:
            file: The image file to upload
            tour_id: The tour ID
            scene_id: The scene ID
            db: Database session for tracking
            user_id: User ID for tracking

        Returns:
            Dict with image_url, thumbnail_url, and metadata
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

            # Generate unique filenames
            file_id = str(uuid.uuid4())
            folder = f"tours/{tour_id}/scenes/{scene_id}"

            # Upload original image
            original_path = f"{folder}/original/{file_id}.jpg"
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
                thumbnail_url = None
            else:
                thumbnail_url = self.supabase.storage.from_(self.bucket_name).get_public_url(thumbnail_path)

            # Generate and upload WebP optimized version
            web_bytes = image_processing.convert_to_webp(file_content, max_dimension=4096)
            web_path = f"{folder}/web/{file_id}.webp"

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
            if db and user_id:
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
    ) -> Dict[str, Any]:
        """
        Process an existing scene image URL to generate thumbnails.

        Args:
            image_url: URL of the existing image
            tour_id: Tour ID
            scene_id: Scene ID

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

            # Generate unique filenames
            file_id = str(uuid.uuid4())
            folder = f"tours/{tour_id}/scenes/{scene_id}"

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


# Global storage service instance
storage_service = StorageService()
