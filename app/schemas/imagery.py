from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.schemas.base import WriteModel

Kind = Literal["city", "locality", "property", "blog"]
ALL_KINDS: tuple[Kind, ...] = ("city", "locality", "property", "blog")


class ImageryRunRequest(WriteModel):
    kinds: list[Kind] = Field(default_factory=lambda: list(ALL_KINDS), min_length=1, max_length=4)
    max_items: int = Field(8, ge=1, le=20)
    max_seconds: int = Field(240, ge=10, le=280)
    variant: Literal["og", "hero"] = Field("og", description="og is 16:9 at 1K, hero is 16:9 at 2K")

    @field_validator("kinds")
    @classmethod
    def _unique_kinds(cls, value: list[Kind]) -> list[Kind]:
        if len(set(value)) != len(value):
            raise ValueError("kinds must not repeat")
        return value


class ImageryRunItem(BaseModel):
    kind: str
    slug: str
    status: Literal["ready", "skipped", "failed", "rate_limited"]


class ImageryRunResult(BaseModel):
    generated: int
    skipped: int
    failed: int
    rate_limited: int
    done: bool
    retry_after: int | None = Field(None, description="Seconds to wait before the next call after a provider 429")
    stopped_reason: str | None
    items: list[ImageryRunItem]
