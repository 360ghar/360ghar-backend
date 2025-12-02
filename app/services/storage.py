"""
Supabase Storage Service for handling file uploads and management.
This is the ONLY service that should use Supabase for data operations (storage).
"""
import os
import uuid
from typing import Optional, Dict, Any, List
from fastapi import UploadFile, HTTPException
from app.core.auth import get_supabase_auth_client
from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

class StorageService:
    """Service for managing file storage using Supabase Storage"""
    
    def __init__(self):
        self.supabase = get_supabase_auth_client()
        self.bucket_name = settings.SUPABASE_STORAGE_BUCKET
    
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
    
    async def _upload_file(self, file: UploadFile, folder: str, file_type: str) -> Dict[str, Any]:
        """Generic file upload method"""
        try:
            # Validate file type
            if not self._is_valid_media(file):
                raise HTTPException(status_code=400, detail="Invalid image or video file type")
            
            # Generate unique filename
            file_extension = self._get_file_extension(file.filename)
            unique_filename = f"{uuid.uuid4()}{file_extension}"
            file_path = f"{folder}/{unique_filename}"
            
            # Read file content
            file_content = await file.read()
            
            # Upload to Supabase Storage
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
    
    def _is_valid_media(self, file: UploadFile) -> bool:
        """Validate if file is a supported image or video"""
        valid_image_types = ["image/jpeg", "image/jpg", "image/png", "image/webp", "image/gif"]
        valid_video_types = ["video/mp4", "video/webm", "video/quicktime", "video/x-matroska", "video/ogg"]
        return file.content_type in (valid_image_types + valid_video_types)
    
    def _get_file_extension(self, filename: str) -> str:
        """Get file extension from filename"""
        if not filename:
            return ".jpg"
        return os.path.splitext(filename)[1] or ".jpg"

# Global storage service instance
storage_service = StorageService()
