from __future__ import annotations

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.base import UtcDateTime, WriteModel

EntityType = Literal["locality", "property"]
Locale = Literal["en", "hi"]
ALL_LOCALES: tuple[Locale, ...] = ("en", "hi")


class ContentBlockOut(BaseModel):
    """Public content for one entity and locale. Only served (auto or approved) rows appear."""

    model_config = ConfigDict(from_attributes=True)

    entity_type: EntityType
    slug: str
    locale: Locale
    body: dict[str, Any]
    sources: list[dict[str, Any]]
    data_as_of: date | None
    indexable: bool
    generated_at: UtcDateTime
    updated_at: UtcDateTime


class ContentManifestItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    entity_type: EntityType
    slug: str
    locale: Locale
    indexable: bool
    updated_at: UtcDateTime


class ContentManifest(BaseModel):
    items: list[ContentManifestItem]


class ContentReviewItem(ContentBlockOut):
    id: int
    review_status: str
    dup_score: float | None
    fact_count: int
    key_fact: bool
    prompt_version: str
    model: str | None
    errors: list[Any]


class ContentStatusUpdate(WriteModel):
    review_status: Literal["approved", "rejected", "needs_review"]


class ContentRunRequest(WriteModel):
    entity_type: EntityType = "locality"
    locales: list[Locale] = Field(default_factory=lambda: list(ALL_LOCALES), min_length=1, max_length=2)
    max_entities: int = Field(10, ge=1, le=50)
    max_seconds: int = Field(240, ge=10, le=280)
    after: str | None = Field(None, max_length=200, description="Cursor from the previous run")
    slugs: list[str] | None = Field(None, max_length=50)
    city: str | None = Field(None, max_length=100)
    force: bool = False
    retry_failed: bool = False


class ContentRunItem(BaseModel):
    slug: str
    locale: str
    status: str
    indexable: bool
    dup_score: float
    calls: int


class ContentRunResult(BaseModel):
    generated: int
    skipped: int
    failed: int
    needs_review: int
    rejected: int
    calls: int
    provider_errors: int
    done: bool
    next_after: str | None
    stopped_reason: str | None
    items: list[ContentRunItem]
