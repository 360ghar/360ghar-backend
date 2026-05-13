import asyncio
import os

from app.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_client_inited = False

def _ensure_client():
    global _client_inited
    if _client_inited:
        return
    api_key = settings.GOOGLE_API_KEY or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise RuntimeError("GOOGLE_API_KEY not configured for Gemini embeddings")
    try:
        import google.generativeai as genai
    except ImportError as e:
        raise RuntimeError("google-generativeai package not installed") from e
    genai.configure(api_key=api_key)
    _client_inited = True
    logger.info("Gemini embedding client configured", extra={"model": settings.GEMINI_EMBED_MODEL})


def _embed_one(genai, model: str, text: str, *, task_type: str = "retrieval_document") -> list[float]:
    retries = max(1, int(settings.VECTOR_SYNC_MAX_RETRIES))
    delay = 1.0
    last_err: Exception | None = None
    for _ in range(retries):
        try:
            resp = genai.embed_content(
                model=model,
                content=text,
                task_type=task_type,
            )
            if isinstance(resp, dict) and "embedding" in resp:
                emb = resp["embedding"]["values"] if isinstance(resp["embedding"], dict) else resp["embedding"]
                return list(emb)
            # Fallback attribute style
            return list(resp.embedding.values)
        except Exception as e:  # noqa: BLE001
            last_err = e
            logger.warning("Gemini embed retry due to error: %s", e, exc_info=True)
            import time
            time.sleep(delay)
            delay = min(8.0, delay * 2.0)
    assert last_err is not None
    raise last_err


def embed_sync(texts: list[str]) -> list[list[float]]:
    """Embed a list of texts synchronously using Gemini (per-item API call).

    Returns a list of vectors (lists of floats). Length should be 768 for text-embedding-004.
    """
    _ensure_client()
    import google.generativeai as genai

    model = settings.GEMINI_EMBED_MODEL
    vectors: list[list[float]] = []
    for t in texts:
        emb = _embed_one(genai, model, t)
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
    _ensure_client()
    import google.generativeai as genai

    model = settings.GEMINI_EMBED_MODEL
    return _embed_one(genai, model, text, task_type="retrieval_query")


async def embed_query(text: str) -> list[float]:
    """Async helper to embed a single search query for semantic search."""
    if not text:
        return []
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, embed_query_sync, text)
