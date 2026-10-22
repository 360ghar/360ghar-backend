"""Rent agreement and legal notice drafts (tenants and landlords)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from app.core.logging import get_logger
from app.middleware.ai_limits import ai_limit
from app.schemas.ai_tools import LegalDraftRequest, LegalDraftResponse
from app.services.ai import legal_draft as ld

logger = get_logger(__name__)

router = APIRouter()

_limit = ai_limit("ai:legal-draft", per_hour=5)


@router.post(
    "/legal-draft",
    response_model=LegalDraftResponse,
    summary="Draft a rent agreement or a legal notice",
    dependencies=[Depends(_limit)],
)
async def legal_draft(body: LegalDraftRequest) -> Any:
    """Public. Limited to 5 per hour per IP.

    The clauses are fixed text filled from ``fields``. The model only rewords the free text
    (``additional_terms`` or ``facts``); ``narrative_source`` says whether it did. Every response
    carries the fixed ``disclaimer`` and ends with a Disclaimer section: show both. The fields
    are never written to the logs.
    """
    fields = body.fields
    has_text = bool(getattr(fields, "additional_terms", None) or getattr(fields, "facts", None))
    provider = ld.make_provider() if has_text else None
    try:
        result = await ld.draft(body.kind, fields, provider)
    finally:
        if provider is not None:
            await provider.close()
    logger.info("Legal draft built: kind=%s source=%s", body.kind, result.narrative_source)
    return result
