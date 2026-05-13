from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger

logger = get_logger(__name__)


def compute_text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


async def get_existing_hash(db: AsyncSession, property_id: int) -> str | None:
    q = text(
        "SELECT emb_text_hash FROM public.property_embeddings WHERE property_id = :pid"
    )
    res = await db.execute(q, {"pid": property_id})
    row = res.first()
    return row[0] if row else None


def _vector_literal(vec: list[float]) -> str:
    # pgvector expects a literal like: [0.1, 0.2, ...]
    return "[" + ",".join(f"{x:.8f}" for x in vec) + "]"


def _zero_vector_literal(dim: int = 768) -> str:
    return "[" + ",".join(["0" for _ in range(dim)]) + "]"


async def upsert_embedding(
    db: AsyncSession,
    property_id: int,
    embedding: list[float] | None,
    metadata: dict[str, Any],
    emb_text_hash: str,
) -> None:
    """Upsert embedding and metadata.

    If embedding is None, only update metadata/hash/updated_at.
    """
    if embedding is not None:
        # Use explicit vector literal via pgvector parameterization. psycopg+pgvector handles list binding.
        embedding_str = _vector_literal(embedding)
        q = text(
            """
            INSERT INTO public.property_embeddings (property_id, embedding, metadata, emb_text_hash, created_at, updated_at)
            VALUES (:pid, CAST(:emb AS vector), CAST(:md_json AS JSONB), :hash, NOW(), NOW())
            ON CONFLICT (property_id)
            DO UPDATE SET embedding = EXCLUDED.embedding,
                          metadata = EXCLUDED.metadata,
                          emb_text_hash = EXCLUDED.emb_text_hash,
                          updated_at = NOW();
            """
        )
        import json as _json
        await db.execute(q, {"pid": property_id, "emb": embedding_str, "md_json": _json.dumps(metadata), "hash": emb_text_hash})
    else:
        zero_vec = _zero_vector_literal(768)
        q = text(
            """
            INSERT INTO public.property_embeddings (property_id, embedding, metadata, emb_text_hash, created_at, updated_at)
            VALUES (:pid, COALESCE((SELECT embedding FROM public.property_embeddings WHERE property_id = :pid), CAST(:zero_vec AS vector)), CAST(:md_json AS JSONB), :hash, NOW(), NOW())
            ON CONFLICT (property_id)
            DO UPDATE SET metadata = EXCLUDED.metadata,
                          emb_text_hash = EXCLUDED.emb_text_hash,
                          updated_at = NOW();
            """
        )
        import json as _json
        await db.execute(q, {"pid": property_id, "md_json": _json.dumps(metadata), "hash": emb_text_hash, "zero_vec": zero_vec})


async def read_watermark(db: AsyncSession) -> datetime | None:
    q = text("SELECT last_watermark FROM public.vector_sync_state WHERE key = 'properties'")
    res = await db.execute(q)
    row = res.first()
    return row[0] if row and row[0] else None


async def write_watermark(db: AsyncSession, watermark: datetime) -> None:
    q = text(
        "UPDATE public.vector_sync_state SET last_watermark = :wm WHERE key = 'properties'"
    )
    await db.execute(q, {"wm": watermark})


async def acquire_advisory_lock(db: AsyncSession) -> bool:
    q = text("SELECT pg_try_advisory_lock( hashtext('property_vector_sync') )")
    res = await db.execute(q)
    got = bool(res.scalar_one())
    if not got:
        logger.info("vector sync skipped; another worker holds the lock")
    return got


async def release_advisory_lock(db: AsyncSession) -> None:
    q = text("SELECT pg_advisory_unlock( hashtext('property_vector_sync') )")
    await db.execute(q)
