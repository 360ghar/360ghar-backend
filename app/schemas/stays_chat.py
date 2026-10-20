"""Booking chat between a guest and the property host (stays app)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.base import UtcDateTime, WriteModel


class BookingMessageCreate(WriteModel):
    body: str = Field(min_length=1, max_length=2000)

    @field_validator("body")
    @classmethod
    def strip_body(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("Message body must not be blank.")
        return stripped


class BookingMessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    sender_id: int | None
    body: str | None
    created_at: UtcDateTime
