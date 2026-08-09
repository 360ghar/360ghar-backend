"""Local filesystem storage fallback.

When Cloudinary credentials are not configured (placeholder values), this
module provides a drop-in replacement that stores files on local disk and
serves them via the backend's /uploads static route.

Usage is automatic — CloudinaryService.__init__ detects missing credentials
and falls back to this implementation.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any

from app.core.logging import get_logger

logger = get_logger(__name__)

# Root directory for locally-stored uploads
UPLOADS_DIR = Path(__file__).resolve().parents[3] / "uploads"
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)

# Public URL prefix served by the /uploads static route in main.py
_BASE_URL_ENV = os.environ.get("PUBLIC_BASE_URL", "http://localhost:3600")
PUBLIC_PREFIX = f"{_BASE_URL_ENV}/uploads"


class LocalStorageService:
    """Mimics CloudinaryService interface using local disk storage."""

    def __init__(self):
        self.root = "local"
        logger.warning(
            "Cloudinary credentials not configured — using local disk storage. "
            "Uploaded files will be stored in the 'uploads/' directory of the backend. "
            "Set CLOUDINARY_CLOUD_NAME, CLOUDINARY_API_KEY, CLOUDINARY_API_SECRET in "
            ".env to switch to Cloudinary."
        )

    # ------------------------------------------------------------------ #
    # Internal helpers                                                     #
    # ------------------------------------------------------------------ #

    def _save(self, data: bytes, filename: str, folder: str | None = None) -> Path:
        subfolder = UPLOADS_DIR / (folder or "misc")
        subfolder.mkdir(parents=True, exist_ok=True)
        dest = subfolder / filename
        dest.write_bytes(data)
        return dest

    def _public_url(self, folder: str | None, filename: str) -> str:
        parts = [PUBLIC_PREFIX, folder or "misc", filename]
        return "/".join(p.strip("/") for p in parts)

    def _public_id(self, folder: str | None, filename: str) -> str:
        parts = ["local", folder or "misc", filename]
        return "/".join(p.strip("/") for p in parts)

    # ------------------------------------------------------------------ #
    # CloudinaryService-compatible API                                    #
    # ------------------------------------------------------------------ #

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
        filename = Path(public_id).name
        dest = self._save(file_bytes, filename, folder)
        url = self._public_url(folder, filename)
        pid = self._public_id(folder, filename)
        logger.info("LocalStorage: saved %s -> %s", filename, dest)
        return {
            "public_id": pid,
            "secure_url": url,
            "bytes": len(file_bytes),
            "width": None,
            "height": None,
            "format": Path(filename).suffix.lstrip("."),
            "original_filename": filename,
        }

    def upload_local_file(
        self,
        local_path: str | Path,
        *,
        public_id: str,
        folder: str | None = None,
    ) -> dict[str, Any]:
        data = Path(local_path).read_bytes()
        return self.upload_file(data, public_id=public_id, folder=folder)

    def upload_from_url(
        self,
        url: str,
        *,
        public_id: str,
        folder: str | None = None,
    ) -> dict[str, Any]:
        import urllib.request
        with urllib.request.urlopen(url, timeout=15) as resp:  # noqa: S310
            data = resp.read()
        return self.upload_file(data, public_id=public_id, folder=folder)

    def delete_file(self, public_id: str) -> bool:
        try:
            # public_id format: local/<folder>/<filename>
            parts = public_id.split("/", 1)
            rel = parts[1] if len(parts) > 1 else public_id
            target = UPLOADS_DIR / rel
            if target.exists():
                target.unlink()
            return True
        except Exception as exc:
            logger.error("LocalStorage: delete failed for %s: %s", public_id, exc)
            return False

    def get_url(
        self,
        public_id: str,
        *,
        fetch_format: str | None = None,
        quality: str | None = None,
        width: int | None = None,
        height: int | None = None,
        crop: str | None = None,
    ) -> str:
        # Reconstruct URL from public_id: local/<folder>/<filename>
        parts = public_id.split("/", 1)
        rel = parts[1] if len(parts) > 1 else public_id
        return f"{PUBLIC_PREFIX}/{rel}"

    def extract_public_id_from_url(self, url: str) -> str | None:
        prefix = PUBLIC_PREFIX
        if url.startswith(prefix):
            rel = url[len(prefix):].lstrip("/")
            return f"local/{rel}"
        return None

    def get_file_info(self, public_id: str) -> dict[str, Any] | None:
        parts = public_id.split("/", 1)
        rel = parts[1] if len(parts) > 1 else public_id
        target = UPLOADS_DIR / rel
        if target.exists():
            return {
                "public_id": public_id,
                "bytes": target.stat().st_size,
                "width": None,
                "height": None,
                "format": target.suffix.lstrip("."),
                "resource_type": "image",
                "created_at": "",
            }
        return None

    def generate_signed_upload_params(
        self,
        *,
        public_id: str,
        folder: str | None = None,
        resource_type: str = "auto",
    ) -> dict[str, Any]:
        import time
        ts = int(time.time())
        pid = self._public_id(folder, Path(public_id).name)
        sig = hashlib.sha1(f"{pid}{ts}local".encode()).hexdigest()
        return {
            "upload_url": f"{_BASE_URL_ENV}/api/v1/upload",
            "api_key": "local",
            "signature": sig,
            "timestamp": ts,
            "public_id": pid,
        }
