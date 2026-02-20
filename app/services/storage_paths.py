"""
Centralized storage path generation with user-scoping.

All paths are user-scoped (users/{user_id}/...) unless explicitly public.
This ensures proper organization and enables RLS policies.
"""
import re
from enum import Enum
from typing import Optional
from uuid import uuid4


class StorageFolder(Enum):
    """Predefined folder types for organized storage.

    Placeholders in values:
    - {property_id}: Property ID
    - {tour_id}: Tour ID
    - {scene_id}: Scene ID
    - {agent_id}: Agent ID (for non-user-scoped paths)
    """
    # User avatars
    AVATAR = "avatars"

    # Property media
    PROPERTY_IMAGE = "properties/{property_id}/images"
    PROPERTY_VIDEO = "properties/{property_id}/videos"
    PROPERTY_DOCUMENT = "properties/{property_id}/documents"

    # Virtual tour assets
    TOUR_THUMBNAIL = "tours/{tour_id}"
    SCENE_ORIGINAL = "tours/{tour_id}/scenes/{scene_id}/original"
    SCENE_THUMBNAIL = "tours/{tour_id}/scenes/{scene_id}/thumbnail"
    SCENE_WEB = "tours/{tour_id}/scenes/{scene_id}/web"

    # Documents
    DOCUMENT_LEASE = "documents/leases"
    DOCUMENT_MAINTENANCE = "documents/maintenance"
    DOCUMENT_GENERAL = "documents/general"

    # Generic uploads
    GENERIC_UPLOAD = "uploads"

    # Agent avatars (NOT user-scoped - at root level)
    AGENT_AVATAR = "agents/{agent_id}/avatars"


def sanitize_filename(filename: str, max_length: int = 50) -> str:
    """
    Sanitize filename for safe storage.

    - Removes path components (prevents directory traversal)
    - Replaces unsafe characters with underscores
    - Truncates to max_length
    - Preserves file extension

    Args:
        filename: Original filename
        max_length: Maximum length for the name part (excluding extension)

    Returns:
        Sanitized filename safe for storage
    """
    if not filename:
        return "file"

    # Remove path components (handle both Unix and Windows paths)
    filename = filename.split("/")[-1].split("\\")[-1]

    # Split name and extension
    if "." in filename:
        name, ext = filename.rsplit(".", 1)
        ext = f".{ext.lower()}"
    else:
        name, ext = filename, ""

    # Sanitize name: only alphanumeric, hyphens, underscores
    name = re.sub(r"[^a-zA-Z0-9_-]", "_", name)
    # Collapse multiple underscores
    name = re.sub(r"_+", "_", name)
    # Strip leading/trailing underscores
    name = name.strip("_")

    # Ensure minimum length
    if not name:
        name = "file"

    # Truncate if needed
    name = name[:max_length]

    return f"{name}{ext}"


def generate_storage_path(
    user_id: int,
    folder: StorageFolder,
    original_filename: Optional[str] = None,
    extension: Optional[str] = None,
    property_id: Optional[int] = None,
    tour_id: Optional[str] = None,
    scene_id: Optional[str] = None,
    agent_id: Optional[int] = None,
) -> str:
    """
    Generate a user-scoped storage path.

    Path format: users/{user_id}/{folder_path}/{uuid}-{sanitized_name}.{ext}

    For agent avatars (the only non-user-scoped type):
    Path format: agents/{agent_id}/avatars/{uuid}-{sanitized_name}.{ext}

    Args:
        user_id: User ID for scoping the path
        folder: StorageFolder enum defining the folder structure
        original_filename: Original filename (for sanitization and extension)
        extension: File extension (used if original_filename not provided)
        property_id: Required for PROPERTY_* folders
        tour_id: Required for TOUR_* and SCENE_* folders
        scene_id: Required for SCENE_* folders
        agent_id: Required for AGENT_AVATAR folder

    Returns:
        Complete storage path

    Raises:
        ValueError: If required IDs are missing for the folder type
    """
    file_uuid = str(uuid4())

    # Determine file name component
    if original_filename:
        safe_name = sanitize_filename(original_filename)
        file_name = f"{file_uuid}-{safe_name}"
    elif extension:
        file_name = f"{file_uuid}.{extension.lstrip('.')}"
    else:
        file_name = file_uuid

    # Build folder path with substitutions
    folder_path = folder.value

    # Handle property_id placeholder
    if "{property_id}" in folder_path:
        if property_id is None:
            raise ValueError("property_id required for this folder type")
        folder_path = folder_path.replace("{property_id}", str(property_id))

    # Handle tour_id placeholder
    if "{tour_id}" in folder_path:
        if tour_id is None:
            raise ValueError("tour_id required for this folder type")
        folder_path = folder_path.replace("{tour_id}", tour_id)

    # Handle scene_id placeholder
    if "{scene_id}" in folder_path:
        if scene_id is None:
            raise ValueError("scene_id required for this folder type")
        folder_path = folder_path.replace("{scene_id}", scene_id)

    # Handle agent_id placeholder (NOT user-scoped)
    if "{agent_id}" in folder_path:
        if agent_id is None:
            raise ValueError("agent_id required for this folder type")
        folder_path = folder_path.replace("{agent_id}", str(agent_id))
        # Agent paths are at root level, not user-scoped
        return f"{folder_path}/{file_name}"

    # All other paths are user-scoped
    return f"users/{user_id}/{folder_path}/{file_name}"


def get_folder_for_content_type(content_type: str) -> StorageFolder:
    """
    Determine the appropriate folder based on content type.

    Args:
        content_type: MIME type of the file

    Returns:
        StorageFolder enum for the content type
    """
    if content_type.startswith("image/"):
        return StorageFolder.PROPERTY_IMAGE
    elif content_type.startswith("video/"):
        return StorageFolder.PROPERTY_VIDEO
    elif content_type == "application/pdf":
        return StorageFolder.DOCUMENT_GENERAL
    elif content_type.startswith("audio/"):
        return StorageFolder.GENERIC_UPLOAD
    else:
        return StorageFolder.GENERIC_UPLOAD


def parse_user_id_from_path(path: str) -> Optional[int]:
    """
    Extract user ID from a storage path.

    Args:
        path: Storage path (e.g., "users/123/avatars/uuid.jpg")

    Returns:
        User ID if path is user-scoped, None otherwise
    """
    if path.startswith("users/"):
        parts = path.split("/")
        if len(parts) >= 2:
            try:
                return int(parts[1])
            except ValueError:
                return None
    return None
