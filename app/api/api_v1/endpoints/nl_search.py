"""Natural-language property search: a sentence in, GET /properties filters out."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from app.core.exceptions import ServiceUnavailableException
from app.core.logging import get_logger
from app.middleware.ai_limits import ai_limit
from app.schemas.property import NLSearchRequest, NLSearchResponse
from app.services.ai import nl_search as nl
from app.services.ai.base import AIProviderError

logger = get_logger(__name__)

router = APIRouter()

_limit = ai_limit("properties:nl-search", per_minute=20)


@router.post(
    "/nl-search",
    response_model=NLSearchResponse,
    summary="Turn a plain-language search into property filters",
    dependencies=[Depends(_limit)],
)
async def nl_property_search(body: NLSearchRequest) -> Any:
    """Public. 20 requests per minute per IP. Answers are cached for 24 hours by normalised query.

    ``filters`` uses the query parameter names of ``GET /properties``. Send them to that endpoint
    as they are. Unknown keys and invalid values are dropped. When the model is not available the
    answer is 503 ``AI_UNAVAILABLE``: fall back to a keyword search with ``q``.
    """
    try:
        return await nl.cached_nl_search(nl.get_provider, body.q)
    except ValueError as exc:
        raise ServiceUnavailableException("Search assistant is not available", error_code="AI_UNAVAILABLE") from exc
    except (AIProviderError, TimeoutError) as exc:
        logger.error("NL search provider error: %s", exc)
        raise ServiceUnavailableException("Search assistant is not available", error_code="AI_UNAVAILABLE") from exc
