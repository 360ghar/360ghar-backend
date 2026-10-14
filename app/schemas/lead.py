from __future__ import annotations

import re

from pydantic import BaseModel, Field, field_validator

_MOBILE = re.compile(r"^[6-9]\d{9}$")


def normalize_mobile(value: str) -> str:
    """Return the 10-digit Indian mobile number, or raise ValueError.

    Accepts spaces, dashes, a leading 0, +91 or 91.
    """
    digits = re.sub(r"\D", "", value or "")
    if len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]
    elif len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]
    if not _MOBILE.match(digits):
        raise ValueError("Enter a 10-digit mobile number that starts with 6, 7, 8 or 9.")
    return digits


class LeadCreate(BaseModel):
    property_id: int | None = None
    name: str | None = Field(None, max_length=100)
    phone: str
    note: str | None = Field(None, max_length=500)
    # Honeypot: real visitors never fill this. A bot that does gets a normal
    # response and nothing is stored.
    website: str | None = Field(None, max_length=200)

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, v: str) -> str:
        return normalize_mobile(v)

    @field_validator("name", "note")
    @classmethod
    def strip_text(cls, v: str | None) -> str | None:
        v = (v or "").strip()
        return v or None


class LeadCreated(BaseModel):
    received: bool = True
