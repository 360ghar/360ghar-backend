"""
AI Image Generation Service.

Wraps Agnes AI image generation for text-to-image and image-to-image generation.
"""

from __future__ import annotations

from app.services.ai.image_gen.schemas import (
    DesignImageOut,
    ImageGenMode,
    ImageGenRequest,
    ImageGenResponse,
)


def __getattr__(name: str):
    if name == "generate_image":
        from app.services.ai.image_gen.service import generate_image

        return generate_image
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "generate_image",
    "ImageGenMode",
    "DesignImageOut",
    "ImageGenRequest",
    "ImageGenResponse",
]
