"""Cloudinary storage service package.

``cloudinary_service`` is a LAZY singleton: importing this package does NOT load
the heavy ``cloudinary`` SDK (~12MB). The SDK is loaded and the singleton built
only on first access to the ``cloudinary_service`` name (via module-level
``__getattr__``) or via ``get_cloudinary_service()``.
"""

from typing import TYPE_CHECKING

from app.services.cloudinary.service import (
    CloudinaryService,
    get_cloudinary_service,
)

__all__ = [
    "CloudinaryService",
    "cloudinary_service",
    "get_cloudinary_service",
]


def __getattr__(name: str):
    """Resolve ``cloudinary_service`` lazily on first attribute access.

    Importing ``from app.services.cloudinary import cloudinary_service`` returns
    this module object's attribute, which triggers this function only at access
    time — so the ``cloudinary`` package is not imported at module import time.
    """
    if name == "cloudinary_service":
        return get_cloudinary_service()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


if TYPE_CHECKING:
    # For static analysis / type checkers only — never executed at runtime.
    cloudinary_service: CloudinaryService
