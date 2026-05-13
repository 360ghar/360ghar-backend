"""
AI Image Generation Schemas.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class ImageGenMode(str, Enum):
    TEXT_TO_IMAGE = "text-to-image"
    IMAGE_TO_IMAGE = "image-to-image"


class ImageGenRequest(BaseModel):
    mode: ImageGenMode = Field(..., description="Generation mode")
    prompt: str = Field(..., min_length=3, max_length=4000, description="Text prompt")
    image: str | None = Field(None, description="Base64-encoded source image (image-to-image only)")
    mimeType: str | None = Field(None, description="MIME type of source image")


class ImageGenResponse(BaseModel):
    success: bool
    image: str | None = None
    error: str | None = None
    code: str | None = None
