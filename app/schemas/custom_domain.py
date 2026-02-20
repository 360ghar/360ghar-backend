"""
Custom Domain schemas for branded tour URLs.
"""
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict, field_validator
import re


class CustomDomainBase(BaseModel):
    """Base schema for custom domains."""
    domain: str

    @field_validator("domain")
    @classmethod
    def validate_domain(cls, v: str) -> str:
        """Validate domain format."""
        # Remove protocol if present
        v = re.sub(r"^https?://", "", v)
        # Remove trailing slash
        v = v.rstrip("/")
        # Basic domain validation
        domain_pattern = r"^[a-zA-Z0-9]([a-zA-Z0-9\-]*[a-zA-Z0-9])?(\.[a-zA-Z0-9]([a-zA-Z0-9\-]*[a-zA-Z0-9])?)*\.[a-zA-Z]{2,}$"
        if not re.match(domain_pattern, v):
            raise ValueError("Invalid domain format")
        return v.lower()


class CustomDomainCreate(CustomDomainBase):
    """Schema for creating a custom domain."""
    pass


class CustomDomainResponse(CustomDomainBase):
    """Schema for custom domain responses."""
    id: str
    user_id: int
    verification_status: str  # pending, verified, failed
    ssl_status: str  # pending, provisioning, active, failed
    verification_token: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class CustomDomainVerification(BaseModel):
    """Schema for domain verification status."""
    domain: str
    is_verified: bool
    verification_instructions: Optional[str] = None
    txt_record_name: str
    txt_record_value: str


class CustomDomainList(BaseModel):
    """Schema for listing custom domains."""
    items: list[CustomDomainResponse]
    total: int
