from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.database import AsyncSessionLocalBG
from app.core.logging import get_logger
from app.models.properties import Amenity, Property, PropertyAmenity

from .compose import build_embedding_text, build_metadata
from .embedding_client import embed
from .store import (
    acquire_advisory_lock,
    compute_text_hash,
    get_existing_hash,
    read_watermark,
    release_advisory_lock,
    upsert_embedding,
    write_watermark,
)

logger = get_logger(__name__)


async def _fetch_changed_properties(db: AsyncSession, since: datetime | None, limit: int) -> list[dict[str, Any]]:
    # Only the columns consumed by build_embedding_text()/build_metadata() in
    # compose.py — anything else (calendar_data, features, owner_*, view/like
    # counters, deposit/rate breakdowns, floor/age details, etc.) ships bytes
    # through the Supabase pooler for nothing. The change-detection hash is
    # computed solely from the embedding text, so dropping unused columns does
    # not affect embedding or watermark behaviour.
    embedding_columns: tuple[Any, ...] = (
        Property.id, Property.title, Property.description, Property.property_type,
        Property.purpose, Property.status, Property.is_available,
        Property.latitude, Property.longitude, Property.city, Property.state,
        Property.country, Property.pincode, Property.locality, Property.landmark,
        Property.base_price, Property.monthly_rent, Property.area_sqft,
        Property.bedrooms, Property.bathrooms, Property.parking_spaces,
        Property.tags, Property.search_keywords, Property.main_image_url,
        Property.created_at, Property.updated_at,
    )

    stmt = select(*embedding_columns).select_from(Property)

    if since is not None:
        stmt = stmt.where(
            or_(
                and_(
                    Property.updated_at.is_not(None),
                    Property.updated_at > since,
                ),
                and_(
                    Property.updated_at.is_(None),
                    Property.created_at > since,
                ),
            )
        )

    stmt = stmt.order_by(Property.updated_at.asc().nullslast()).limit(limit)
    res = await db.execute(stmt)
    rows = res.mappings().all()
    return [dict(r) for r in rows]


async def _fetch_amenities_and_tags(db: AsyncSession, property_ids: list[int]) -> tuple[dict[int, list[str]], dict[int, list[str]]]:
    if not property_ids:
        return {}, {}
    # Amenities titles by property
    stmt = (
        select(PropertyAmenity.property_id, Amenity.title)
        .join(Amenity, PropertyAmenity.amenity_id == Amenity.id)
        .where(PropertyAmenity.property_id.in_(property_ids))
    )
    res = await db.execute(stmt)
    amap: dict[int, list[str]] = {}
    for pid, title in res.all():
        amap.setdefault(pid, []).append(title)

    # Tags are stored in properties.tags JSON; fetch in outer query maps
    tmap: dict[int, list[str]] = {}
    # We'll rely on the 'tags' column already fetched per property; this function only fills amenities
    return amap, tmap


async def _prepare_batch(db: AsyncSession, props: list[dict[str, Any]]) -> tuple[list[str], list[dict[str, Any]], list[str], list[bool]]:
    """Fetch amenities, build texts/metadata/hashes, check existing hashes.

    Returns (texts, metas, hashes, need_embed_flags) — no embedding yet.
    """
    if not props:
        return [], [], [], []
    pids = [int(p["id"]) for p in props]
    amenity_map, _ = await _fetch_amenities_and_tags(db, pids)

    texts: list[str] = []
    metas: list[dict[str, Any]] = []
    hashes: list[str] = []
    need_embed_flags: list[bool] = []

    for p in props:
        pid = int(p["id"])
        amenities = amenity_map.get(pid, [])
        tags = p.get("tags") or []
        if isinstance(tags, list):
            tag_list = [str(t) for t in tags]
        else:
            tag_list = []
        text = build_embedding_text(p, amenities, tag_list)
        meta = build_metadata(p, amenities, tag_list)
        h = compute_text_hash(text)
        existing = await get_existing_hash(db, pid)
        need_embed = (existing != h)
        texts.append(text)
        metas.append(meta)
        hashes.append(h)
        need_embed_flags.append(need_embed)

    return texts, metas, hashes, need_embed_flags


async def _embed_texts(texts_to_embed: list[str]) -> list[list[float]]:
    """Call the embedding API — no DB session held during this I/O."""
    if not texts_to_embed:
        return []
    try:
        vectors = await embed(texts_to_embed)
    except Exception as e:  # noqa: BLE001
        logger.error("Embedding API failed for batch of %s: %s", len(texts_to_embed), e, exc_info=True)
        raise
    if not vectors or len(vectors) != len(texts_to_embed):
        logger.error(
            "Embedding API returned %d vectors for %d inputs; aborting batch",
            len(vectors),
            len(texts_to_embed),
        )
        raise RuntimeError("Embedding API returned inconsistent vector count")
    return vectors


async def _upsert_batch(db: AsyncSession, props: list[dict[str, Any]], metas: list[dict[str, Any]], hashes: list[str], need_embed_flags: list[bool], vectors: list[list[float]]) -> None:
    """Upsert embeddings into DB — session held only for writes."""
    vec_iter = iter(vectors)
    for p, meta, h, need_embed in zip(props, metas, hashes, need_embed_flags, strict=True):
        pid = int(p["id"])
        emb = next(vec_iter) if need_embed and vectors else None
        await upsert_embedding(db, pid, emb, meta, h)


async def run_property_vector_sync() -> dict[str, int | bool]:
    """Entry point to run one incremental sync pass.

    The session is released during the embedding API call so that the
    DB connection is not held during network I/O. Uses the background
    pool to avoid starving HTTP/MCP request traffic.

    Returns stats for logging/metrics.
    """
    stats = {"scanned": 0, "embedded": 0, "updated": 0}
    force = os.getenv("VECTOR_SYNC_FORCE", "").lower() in ("1", "true", "yes")

    # Phase 1: Acquire lock, fetch data, compute hashes (session held briefly)
    async with AsyncSessionLocalBG() as db:
        got_lock = True
        if not force:
            got_lock = await acquire_advisory_lock(db)
            if not got_lock:
                return {"skipped": True}
        try:
            watermark = await read_watermark(db)
            batch_size = int(settings.VECTOR_SYNC_BATCH_SIZE)

            changed = await _fetch_changed_properties(db, watermark, batch_size)
            if not changed:
                if not force:
                    await release_advisory_lock(db)
                return {"scanned": 0, "embedded": 0, "updated": 0}

            stats["scanned"] = len(changed)
            texts, metas, hashes, need_embed_flags = await _prepare_batch(db, changed)
        except Exception:
            logger.error("Vector sync phase 1 failed", exc_info=True)
            if not force:
                await db.rollback()
                try:
                    await release_advisory_lock(db)
                except Exception:
                    logger.debug("Failed to release advisory lock", exc_info=True)
            raise
        finally:
            # Release session — embedding call happens without a DB connection
            if not force:
                await release_advisory_lock(db)

    # Phase 2: Embedding API call — NO session held
    texts_to_embed = [t for t, f in zip(texts, need_embed_flags, strict=True) if f]
    vectors = await _embed_texts(texts_to_embed)

    # Rebuild full vectors list aligned with props ordering
    vec_iter = iter(vectors)
    full_vectors: list[list[float]] = []
    for need in need_embed_flags:
        full_vectors.append(next(vec_iter) if need and vectors else [])

    # Phase 3: Upsert + watermark advance (new session, brief)
    async with AsyncSessionLocalBG() as db:
        try:
            await _upsert_batch(db, changed, metas, hashes, need_embed_flags, full_vectors)
            await db.commit()

            stats["updated"] = len(changed)

            timestamps = [t for p in changed if (t := p.get("updated_at") or p.get("created_at")) is not None]
            new_wm = max(timestamps)
            if isinstance(new_wm, datetime):
                await write_watermark(db, new_wm)
                await db.commit()
            else:
                await write_watermark(db, datetime.now(timezone.utc))
                await db.commit()
        except Exception:
            logger.error("Vector sync phase 3 (upsert/watermark) failed", exc_info=True)
            await db.rollback()
            raise

    return stats
