from __future__ import annotations

import re
from enum import Enum
from uuid import uuid4

from app.core.exceptions import BadRequestException


class StorageFolder(Enum):
    AVATAR = "avatars/{user_id}"
    PROPERTY_IMAGE = "properties/{property_id}"
    PROPERTY_VIDEO = "properties/{property_id}/videos"
    PROPERTY_DOCUMENT = "properties/{property_id}/documents"
    TOUR_THUMBNAIL = "tours/{tour_id}/thumbnail"
    SCENE_ORIGINAL = "tours/{tour_id}/scenes/{scene_id}/original"
    SCENE_THUMBNAIL = "tours/{tour_id}/scenes/{scene_id}/thumbnail"
    SCENE_WEB = "tours/{tour_id}/scenes/{scene_id}/web"
    DOCUMENT_LEASE = "documents/leases"
    DOCUMENT_MAINTENANCE = "documents/maintenance"
    DOCUMENT_GENERAL = "documents/general"
    GENERIC_UPLOAD = "uploads/{user_id}"
    AGENT_AVATAR = "agents/{agent_id}/avatars"
    BLOG_COVER = "blog-covers"


def sanitize_filename(filename: str, max_length: int = 50) -> str:
    if not filename:
        return "file"
    filename = filename.split("/")[-1].split("\\")[-1]
    if "." in filename:
        name, ext = filename.rsplit(".", 1)
        ext = f".{ext.lower()}"
    else:
        name, ext = filename, ""
    name = re.sub(r"[^a-zA-Z0-9_-]", "_", name)
    name = re.sub(r"_+", "_", name)
    name = name.strip("_")
    if not name:
        name = "file"
    name = name[:max_length]
    return f"{name}{ext}"


def generate_cloudinary_public_id(
    folder: StorageFolder,
    original_filename: str | None = None,
    extension: str | None = None,
    user_id: int | None = None,
    property_id: int | None = None,
    tour_id: str | None = None,
    scene_id: str | None = None,
    agent_id: int | None = None,
) -> str:
    file_uuid = str(uuid4())[:12]
    if original_filename:
        safe_name = sanitize_filename(original_filename)
        file_name = f"{file_uuid}-{safe_name}"
    elif extension:
        file_name = f"{file_uuid}.{extension.lstrip('.')}"
    else:
        file_name = file_uuid

    folder_path = folder.value

    if "{user_id}" in folder_path:
        if user_id is None:
            raise BadRequestException(detail="user_id required for this folder type")
        folder_path = folder_path.replace("{user_id}", str(user_id))

    if "{property_id}" in folder_path:
        if property_id is None:
            raise BadRequestException(detail="property_id required for this folder type")
        folder_path = folder_path.replace("{property_id}", str(property_id))

    if "{tour_id}" in folder_path:
        if tour_id is None:
            raise BadRequestException(detail="tour_id required for this folder type")
        folder_path = folder_path.replace("{tour_id}", tour_id)

    if "{scene_id}" in folder_path:
        if scene_id is None:
            raise BadRequestException(detail="scene_id required for this folder type")
        folder_path = folder_path.replace("{scene_id}", scene_id)

    if "{agent_id}" in folder_path:
        if agent_id is None:
            raise BadRequestException(detail="agent_id required for this folder type")
        folder_path = folder_path.replace("{agent_id}", str(agent_id))

    return f"{folder_path}/{file_name}"


def generate_storage_path(
    user_id: int,
    folder: StorageFolder,
    original_filename: str | None = None,
    extension: str | None = None,
    property_id: int | None = None,
    tour_id: str | None = None,
    scene_id: str | None = None,
    agent_id: int | None = None,
) -> str:
    return generate_cloudinary_public_id(
        folder=folder,
        original_filename=original_filename,
        extension=extension,
        user_id=user_id,
        property_id=property_id,
        tour_id=tour_id,
        scene_id=scene_id,
        agent_id=agent_id,
    )


def get_folder_for_content_type(content_type: str) -> StorageFolder:
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


def parse_user_id_from_path(path: str) -> int | None:
    if path.startswith("avatars/"):
        parts = path.split("/")
        if len(parts) >= 2:
            try:
                return int(parts[1])
            except ValueError:
                return None
    if path.startswith("uploads/"):
        parts = path.split("/")
        if len(parts) >= 2:
            try:
                return int(parts[1])
            except ValueError:
                return None
    return None
