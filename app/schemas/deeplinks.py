"""Pydantic schemas for the deep link generation API."""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.services.deeplinks.service import MAX_IDENTIFIER_LENGTH


class EntityInfo(BaseModel):
    entity: str = Field(..., description="URL segment for the entity, e.g. 'property'")
    description: str = Field("", description="Human-readable description")
    public: bool = Field(False, description="Whether links resolve without auth")


class AppInfo(BaseModel):
    key: str = Field(..., description="Stable app key: ghar/estate/flatmates/stays")
    name: str = Field(..., description="Human-readable app name")
    path_prefix: str = Field("", description="HTTPS path namespace ('' for the flagship app)")
    custom_scheme: str = Field(..., description="Custom URL scheme used as launch fallback")
    android_packages: list[str] = Field(default_factory=list)
    ios_bundle_id: str = Field(...)
    entities: list[EntityInfo] = Field(default_factory=list)


class GeneratedLinkResponse(BaseModel):
    app: str = Field(..., description="App key")
    entity: str = Field(..., description="Entity type")
    identifier: str = Field(..., description="Entity identifier")
    url: str = Field(..., description="Canonical HTTPS App/Universal Link to share")
    scheme_url: str = Field(..., description="Custom-scheme URL for direct app launch")
    web_fallback_url: str = Field(..., description="Web URL shown if the app is not installed")


class GenerateLinkRequest(BaseModel):
    app: str = Field(
        ...,
        min_length=1,
        max_length=32,
        description="App key: ghar/estate/flatmates/stays",
    )
    entity: str = Field(
        ...,
        min_length=1,
        max_length=32,
        description="Entity type, e.g. 'property'",
    )
    identifier: str = Field(
        ...,
        min_length=1,
        # Reference the service-layer constant so the POST body and the
        # GET path stay in sync without a second source of truth.
        max_length=MAX_IDENTIFIER_LENGTH,
        description="Entity identifier (id or slug)",
    )
