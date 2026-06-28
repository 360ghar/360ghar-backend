"""
Cloudinary Storage Service package.

Re-exports all public symbols from the sub-modules so that existing imports
like ``from app.services.storage import StorageService`` continue to work
without any changes.
"""

from .helpers import (  # noqa: F401 – public re-exports
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
from .paths import (  # noqa: F401 – public re-exports
    StorageFolder,
    generate_storage_path,
    get_folder_for_content_type,
    parse_user_id_from_path,
    sanitize_filename,
)
from .processing import (  # noqa: F401 – public re-exports
    process_existing_scene_image,
    upload_scene_image,
)
from .service import StorageService, storage_service  # noqa: F401 – primary exports

__all__ = [
    # Class & singleton
    "StorageService",
    "storage_service",
    # Helpers
    "VALID_AUDIO_TYPES",
    "VALID_DOCUMENT_TYPES",
    "VALID_IMAGE_TYPES",
    "VALID_VIDEO_TYPES",
    "expected_type_from_content_type",
    "get_file_extension",
    "get_max_upload_bytes",
    "infer_content_type_from_extension",
    "is_valid_content_type",
    "is_valid_upload",
    "validate_magic_bytes",
    # Paths
    "StorageFolder",
    "generate_storage_path",
    "get_folder_for_content_type",
    "parse_user_id_from_path",
    "sanitize_filename",
    # Processing
    "process_existing_scene_image",
    "upload_scene_image",
]
