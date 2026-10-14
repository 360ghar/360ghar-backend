"""
AI Image Generation Schemas.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field, field_validator

ALLOWED_RATIOS = ("1:1", "3:4", "4:3", "16:9", "9:16", "2:3", "3:2", "21:9")


class ImageGenMode(str, Enum):
    TEXT_TO_IMAGE = "text-to-image"
    IMAGE_TO_IMAGE = "image-to-image"


class ImageGenRequest(BaseModel):
    mode: ImageGenMode = Field(..., description="Generation mode")
    prompt: str = Field(..., min_length=3, max_length=4000, description="Text prompt")
    # 7,000,000 base64 chars is about a 5 MB image, the same cap the web upload uses.
    image: str | None = Field(None, max_length=7_000_000, description="Base64-encoded source image (image-to-image only, max ~5 MB)")
    mimeType: str | None = Field(None, description="MIME type of source image")
    ratio: str = Field("1:1", description="Output aspect ratio: " + ", ".join(ALLOWED_RATIOS))

    @field_validator("ratio")
    @classmethod
    def _check_ratio(cls, value: str) -> str:
        if value not in ALLOWED_RATIOS:
            raise ValueError(f"ratio must be one of {', '.join(ALLOWED_RATIOS)}")
        return value


class ImageGenResponse(BaseModel):
    success: bool
    image: str | None = None
    error: str | None = None
    code: str | None = None
