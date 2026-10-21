"""
Custom Domain schemas for branded tour URLs.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.enums import CustomDomainSSLStatus, CustomDomainVerificationStatus
from app.schemas.base import UtcDateTime, WriteModel

_DOMAIN_PATTERN = r"^[a-zA-Z0-9]([a-zA-Z0-9\-]*[a-zA-Z0-9])?(\.[a-zA-Z0-9]([a-zA-Z0-9\-]*[a-zA-Z0-9])?)*\.[a-zA-Z]{2,}$"


def normalize_domain(value: str) -> str:
    """Strip the scheme and trailing slash, check the format, and lower-case the result."""
    value = re.sub(r"^https?://", "", value).rstrip("/")
    if not re.fullmatch(_DOMAIN_PATTERN, value):
        raise ValueError("Invalid domain format")
    return value.lower()


class CustomDomainCreate(WriteModel):
    """Body for POST /custom-domains."""

    domain: str = Field(..., min_length=3, max_length=255)

    @field_validator("domain")
    @classmethod
    def validate_domain(cls, v: str) -> str:
        return normalize_domain(v)

    model_config = ConfigDict(json_schema_extra={"title": "CustomDomainCreate"})


class CustomDomainResponse(BaseModel):
    """Schema for custom domain responses."""

    id: str
    user_id: int
    domain: str
    verification_status: CustomDomainVerificationStatus
    ssl_status: CustomDomainSSLStatus
    verification_token: str | None = None
    created_at: UtcDateTime
    updated_at: UtcDateTime

    model_config = ConfigDict(from_attributes=True)


class CustomDomainVerification(BaseModel):
    """Schema for domain verification status."""

    domain: str
    is_verified: bool
    verification_instructions: str | None = None
    txt_record_name: str
    txt_record_value: str
