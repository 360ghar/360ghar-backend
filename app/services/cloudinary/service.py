from __future__ import annotations

import io
from pathlib import Path
from typing import Any

from app.config import settings
from app.core.exceptions import StorageException
from app.core.logging import get_logger

logger = get_logger(__name__)

CLOUDINARY_ROOT = "360ghar"


def _configure():
    """Configure the cloudinary SDK.

    Imported lazily so the heavy ``cloudinary`` package is only loaded the first
    time a CloudinaryService is instantiated (i.e. on first use), not at import
    time of this module.
    """
    import cloudinary
    import cloudinary.http_client  # noqa: F401

    cloudinary.config(
        cloud_name=settings.CLOUDINARY_CLOUD_NAME,
        api_key=settings.CLOUDINARY_API_KEY,
        api_secret=settings.CLOUDINARY_API_SECRET,
        secure=True,
    )


class CloudinaryService:
    """Wrapper over the Cloudinary SDK for upload / delete / URL / transform ops.

    The SDK is imported lazily on first instantiation; the instance attributes
    ``_cloudinary``, ``_api``, ``_uploader`` and ``_url`` bind the SDK handles so
    method bodies resolve them without re-importing.
    """

    def __init__(self):
        # Imported here (not at module top) so that ``cloudinary`` (~12MB) is
        # only loaded when a service is actually instantiated at runtime.
        import cloudinary
        import cloudinary.http_client  # noqa: F401
        from cloudinary import api as cloudinary_api
        from cloudinary import uploader
        from cloudinary.utils import cloudinary_url

        # Bind to instance so method bodies resolve them without re-importing.
        self._cloudinary = cloudinary
        self._api = cloudinary_api
        self._uploader = uploader
        self._url = cloudinary_url

        # Increase Cloudinary's urllib3 connection pool (best-effort).
        try:
            import urllib3

            cloudinary.http_client._session = urllib3.PoolManager(maxsize=20)
        except Exception:
            pass

        _configure()
        self.root = CLOUDINARY_ROOT

    def _public_id(self, *parts: str) -> str:
        cleaned = [p.strip("/") for p in parts if p]
        return "/".join(cleaned)

    def _upload_options(self, is_image: bool = False, is_document: bool = False) -> dict[str, Any]:
        options: dict[str, Any] = {}
        if is_image:
            options["fetch_format"] = "auto"
            options["quality"] = "auto"
        if is_document:
            options["resource_type"] = "auto"
        return options

    def upload_file(
        self,
        file_bytes: bytes,
        *,
        public_id: str,
        content_type: str | None = None,
        is_image: bool = False,
        folder: str | None = None,
        **extra_options: Any,
    ) -> dict[str, Any]:
        try:
            full_public_id = self._public_id(self.root, folder or "", public_id)

            options: dict[str, Any] = {
                "public_id": full_public_id,
                "overwrite": False,
                "resource_type": "auto",
            }
            if content_type:
                options["resource_type"] = self._resource_type(content_type)
            options.update(self._upload_options(is_image=is_image, is_document=options.get("resource_type") == "raw"))
            options.update(extra_options)

            if isinstance(file_bytes, bytes):
                result = self._uploader.upload(io.BytesIO(file_bytes), **options)
            else:
                result = self._uploader.upload(file_bytes, **options)

            secure_url: str = result.get("secure_url", "")
            return {
                "public_id": result.get("public_id", full_public_id),
                "secure_url": secure_url,
                "bytes": result.get("bytes", len(file_bytes) if isinstance(file_bytes, bytes) else 0),
                "width": result.get("width"),
                "height": result.get("height"),
                "format": result.get("format"),
                "original_filename": result.get("original_filename", ""),
            }
        except Exception as e:
            logger.error("Cloudinary upload error: %s", e)
            raise StorageException(detail=f"Cloudinary upload failed: {e}") from e

    def upload_local_file(
        self,
        local_path: str | Path,
        *,
        public_id: str,
        folder: str | None = None,
    ) -> dict[str, Any]:
        try:
            full_public_id = self._public_id(self.root, folder or "", public_id)
            options: dict[str, Any] = {
                "public_id": full_public_id,
                "overwrite": True,
                "resource_type": "auto",
            }
            ext = Path(str(local_path)).suffix.lower()
            if ext in (".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tiff"):
                options.update(self._upload_options(is_image=True))
            else:
                options["resource_type"] = "raw"

            result = self._uploader.upload(str(local_path), **options)
            return {
                "public_id": result.get("public_id", full_public_id),
                "secure_url": result.get("secure_url", ""),
                "bytes": result.get("bytes", 0),
                "width": result.get("width"),
                "height": result.get("height"),
                "format": result.get("format"),
            }
        except Exception as e:
            logger.error("Cloudinary local file upload error: %s", e)
            raise StorageException(detail=f"Cloudinary upload failed: {e}") from e

    def upload_from_url(
        self,
        url: str,
        *,
        public_id: str,
        folder: str | None = None,
    ) -> dict[str, Any]:
        try:
            full_public_id = self._public_id(self.root, folder or "", public_id)
            result = self._uploader.upload(
                url,
                public_id=full_public_id,
                overwrite=True,
                resource_type="auto",
                fetch_format="auto",
                quality="auto",
            )
            return {
                "public_id": result.get("public_id", full_public_id),
                "secure_url": result.get("secure_url", ""),
                "bytes": result.get("bytes", 0),
                "width": result.get("width"),
                "height": result.get("height"),
                "format": result.get("format"),
            }
        except Exception as e:
            logger.error("Cloudinary URL upload error: %s", e)
            raise StorageException(detail=f"Cloudinary upload from URL failed: {e}") from e

    def delete_file(self, public_id: str) -> bool:
        try:
            result = self._api.delete_resources([public_id], resource_type="auto")
            deleted = result.get("deleted", {})
            return bool(deleted.get(public_id) == "deleted")
        except Exception as e:
            logger.error("Cloudinary delete error: %s", e)
            return False

    def get_url(
        self,
        public_id: str,
        *,
        fetch_format: str | None = "auto",
        quality: str | None = "auto",
        width: int | None = None,
        height: int | None = None,
        crop: str | None = None,
    ) -> str:
        transformations: list[dict[str, Any]] = []
        if fetch_format:
            transformations.append({"fetch_format": fetch_format})
        if quality:
            transformations.append({"quality": quality})
        if width or height:
            t: dict[str, Any] = {}
            if width:
                t["width"] = width
            if height:
                t["height"] = height
            t["crop"] = crop or "fit"
            transformations.append(t)
        url, _ = self._url(
            public_id,
            transformation=transformations,
            secure=True,
        )
        return str(url)

    def extract_public_id_from_url(self, url: str) -> str | None:
        try:
            parts = url.split("/")
            for i, part in enumerate(parts):
                if part == self.root and i + 1 < len(parts):
                    return "/".join(parts[i:]).split("?")[0].split("#")[0]
            return None
        except Exception:
            return None

    def get_file_info(self, public_id: str) -> dict[str, Any] | None:
        try:
            result = self._api.resource(public_id, resource_type="auto")
            return {
                "public_id": result.get("public_id", ""),
                "bytes": result.get("bytes", 0),
                "width": result.get("width"),
                "height": result.get("height"),
                "format": result.get("format"),
                "resource_type": result.get("resource_type", ""),
                "created_at": result.get("created_at", ""),
            }
        except Exception as e:
            logger.error("Cloudinary file info error: %s", e)
            return None

    def generate_signed_upload_params(
        self,
        *,
        public_id: str,
        folder: str | None = None,
        resource_type: str = "auto",
    ) -> dict[str, Any]:
        """Generate signed upload parameters for client-side direct uploads.

        Returns a dict with ``upload_url``, ``api_key``, ``signature``,
        ``timestamp``, and other params the client needs to POST directly
        to Cloudinary's upload endpoint.
        """
        import hashlib
        import time

        from app.config import settings

        full_public_id = self._public_id(self.root, folder or "", public_id)
        timestamp = int(time.time())

        # Build the parameters to sign (sorted alphabetically per Cloudinary docs).
        params_to_sign = {
            "public_id": full_public_id,
            "timestamp": timestamp,
        }
        # Cloudinary signs: param=value&param=value (sorted) + api_secret
        sorted_params = "&".join(
            f"{k}={v}" for k, v in sorted(params_to_sign.items())
        )
        to_sign = f"{sorted_params}{settings.CLOUDINARY_API_SECRET}"
        signature = hashlib.sha1(to_sign.encode("utf-8")).hexdigest()

        upload_url = f"https://api.cloudinary.com/v1_1/{settings.CLOUDINARY_CLOUD_NAME}/{resource_type}/upload"

        return {
            "upload_url": upload_url,
            "api_key": settings.CLOUDINARY_API_KEY,
            "signature": signature,
            "timestamp": timestamp,
            "public_id": full_public_id,
        }

    @staticmethod
    def _resource_type(content_type: str) -> str:
        if content_type.startswith("image/"):
            return "image"
        if content_type.startswith("video/"):
            return "video"
        return "raw"


# Lazy singleton. The ``cloudinary_service`` name is resolved lazily via the
# package-level ``__getattr__`` in ``app/services/cloudinary/__init__.py`` so
# that merely importing this module (or the package) does NOT load the heavy
# ``cloudinary`` package. The singleton is built on first attribute access.
_cloudinary_service_instance: CloudinaryService | None = None


def get_cloudinary_service() -> CloudinaryService:
    """Return the process-wide CloudinaryService singleton, building it lazily."""
    global _cloudinary_service_instance  # noqa: PLW0603
    if _cloudinary_service_instance is None:
        _cloudinary_service_instance = CloudinaryService()
    return _cloudinary_service_instance
