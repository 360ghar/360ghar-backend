"""Cloudinary storage service package.

``cloudinary_service`` is a LAZY singleton: importing this package does NOT load
the heavy ``cloudinary`` SDK (~12MB). The SDK is loaded and the singleton built
only on first access to the ``cloudinary_service`` name (via module-level
``__getattr__``) or via ``get_cloudinary_service()``.

When Cloudinary credentials are absent or are still placeholder values, the
package transparently falls back to :mod:`local_fallback.LocalStorageService`
which stores files on local disk and serves them via the ``/uploads`` static
route mounted in ``app/main.py``. No code changes are needed to switch back
to Cloudinary — just fill in the three ``CLOUDINARY_*`` variables in ``.env``.
"""

from typing import TYPE_CHECKING

__all__ = [
    "CloudinaryService",
    "cloudinary_service",
    "get_cloudinary_service",
]

_PLACEHOLDER_VALUES = {"", "your_cloud_name", "your_api_key", "your_api_secret"}

_service_instance = None


def get_cloudinary_service():
    """Return the process-wide storage service singleton, built lazily.

    Returns a :class:`CloudinaryService` when Cloudinary credentials are
    configured, or a :class:`LocalStorageService` fallback otherwise.
    """
    global _service_instance  # noqa: PLW0603
    if _service_instance is None:
        from app.config import settings

        cloud_name = getattr(settings, "CLOUDINARY_CLOUD_NAME", "")
        api_key = getattr(settings, "CLOUDINARY_API_KEY", "")
        api_secret = getattr(settings, "CLOUDINARY_API_SECRET", "")

        if (
            cloud_name in _PLACEHOLDER_VALUES
            or api_key in _PLACEHOLDER_VALUES
            or api_secret in _PLACEHOLDER_VALUES
        ):
            from app.services.cloudinary.local_fallback import LocalStorageService
            _service_instance = LocalStorageService()
        else:
            from app.services.cloudinary.service import CloudinaryService
            _service_instance = CloudinaryService()

    return _service_instance


def __getattr__(name: str):
    """Resolve ``cloudinary_service`` lazily on first attribute access."""
    if name == "cloudinary_service":
        return get_cloudinary_service()
    if name == "CloudinaryService":
        from app.services.cloudinary.service import CloudinaryService
        return CloudinaryService
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


if TYPE_CHECKING:
    from app.services.cloudinary.service import CloudinaryService
    cloudinary_service: CloudinaryService
