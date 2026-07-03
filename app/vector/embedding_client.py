from __future__ import annotations

import asyncio
import os
from collections.abc import Sequence
from typing import Any

from app.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_client: object | None = None


def _get_client():
    global _client
    if _client is not None:
        return _client
    api_key = settings.GOOGLE_API_KEY or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise RuntimeError("GOOGLE_API_KEY not configured for Gemini embeddings")
    try:
        from google import genai
    except ImportError as e:
        raise RuntimeError("google-genai package not installed") from e
    _client = genai.Client(api_key=api_key)
    logger.info("Gemini embedding client configured", extra={"model": settings.GEMINI_EMBED_MODEL})
    return _client


def _embed_one(client: Any, model: str, text: str, *, task_type: str = "retrieval_document") -> list[float]:
    from google.genai import types

    # gemini-embedding-2-* ignores task_type; the task is an in-prompt instruction instead.
    # Asymmetric retrieval format per https://ai.google.dev/gemini-api/docs/embeddings
    is_v2 = model.startswith("gemini-embedding-2")
    if is_v2:
        if task_type == "retrieval_query":
            content = f"task: search result | query: {text}"
        else:
            content = f"title: none | text: {text}"
        config = types.EmbedContentConfig(output_dimensionality=768)  # matches vector(768) column
    else:
        content = text
        config = types.EmbedContentConfig(task_type=task_type, output_dimensionality=768)

    retries = max(1, int(settings.VECTOR_SYNC_MAX_RETRIES))
    delay = 1.0
    last_err: Exception | None = None
    for _ in range(retries):
        try:
            resp = client.models.embed_content(
                model=model,
                contents=content,
                config=config,
            )
            if resp.embeddings:
                return list(resp.embeddings[0].values)
            raise RuntimeError("No embeddings returned from Gemini API")
        except Exception as e:
            last_err = e
            logger.warning("Gemini embed retry due to error: %s", e, exc_info=True)
            import time

            time.sleep(delay)  # intentional sync: runs inside run_in_executor thread
            delay = min(8.0, delay * 2.0)
    assert last_err is not None
    raise last_err


def embed_sync(texts: Sequence[str]) -> list[list[float]]:
    """Embed a list of texts synchronously using Gemini (per-item API call).

    Returns a list of 768-d vectors (output_dimensionality pinned to match the pgvector column).
    """
    client = _get_client()
    model = settings.GEMINI_EMBED_MODEL
    vectors: list[list[float]] = []
    for t in texts:
        emb = _embed_one(client, model, t)
        vectors.append(emb)
    return vectors


async def embed(texts: list[str]) -> list[list[float]]:
    """Async wrapper around the sync embedding call.
    Uses a thread to avoid blocking the event loop.
    """
    if not texts:
        return []
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, embed_sync, texts)


def embed_query_sync(text: str) -> list[float]:
    """Embed a single query using Gemini retrieval_query mode."""
    client = _get_client()
    model = settings.GEMINI_EMBED_MODEL
    return _embed_one(client, model, text, task_type="retrieval_query")


async def embed_query(text: str) -> list[float]:
    """Async helper to embed a single search query for semantic search."""
    if not text:
        return []
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, embed_query_sync, text)
