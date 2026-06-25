"""
BaseLoader — shared loading infrastructure for all data categories.

Provides:
- Idempotent record creation (skip if exists by unique fields)
- Batch committing every N records
- Natural-key → DB-ID mapping (resolve references across JSON files)
- Progress logging
"""

from __future__ import annotations

import hashlib
import json
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import and_, delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.core.logging import get_logger

logger = get_logger(__name__)

SEED_DATA_DIR = Path(__file__).resolve().parent.parent
HARDCODED_DIR = SEED_DATA_DIR / "hardcoded"
SEED_DIR = SEED_DATA_DIR / "seed"
MEDIA_DIR = SEED_DIR / "media"

BATCH_SIZE = 50


class IDMap:
    """Maps natural keys to database IDs resolved during loading.

    Example: id_map["user"]["saksham1991999@gmail.com"] → 1
    """

    def __init__(self) -> None:
        self._maps: dict[str, dict[str, Any]] = {}

    def put(self, entity: str, key: str, db_id: Any) -> None:
        self._maps.setdefault(entity, {})[key] = db_id

    def get(self, entity: str, key: str) -> Any | None:
        return self._maps.get(entity, {}).get(key)

    def get_all(self, entity: str) -> dict[str, Any]:
        return self._maps.get(entity, {})

    def has(self, entity: str, key: str) -> bool:
        return key in self._maps.get(entity, {})


# Shared singleton — populated as loading progresses
id_map = IDMap()


def load_json(path: Path) -> list[dict[str, Any]]:
    """Load a JSON file and return as list of dicts."""
    if not path.exists():
        logger.warning("JSON file not found: %s", path)
        return []
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict):
        return [data]
    return data


def file_hash(path: Path) -> str:
    """SHA-256 content hash of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


class BaseLoader(ABC):
    """Abstract base for all data loaders."""

    @property
    @abstractmethod
    def model_class(self) -> type:
        """SQLAlchemy model class."""

    @property
    def unique_fields(self) -> list[str]:
        """Fields that uniquely identify a record. Empty = always create."""
        return []

    def _strip_meta_keys(self, data: dict[str, Any]) -> dict[str, Any]:
        """Remove keys starting with '_' (comments, refs) before DB insert."""
        return {k: v for k, v in data.items() if not k.startswith("_")}

    async def _record_exists(self, session: AsyncSession, data: dict[str, Any]) -> bool:
        """Check if a record already exists by unique fields."""
        if not self.unique_fields:
            return False
        conditions = []
        for field in self.unique_fields:
            if field in data:
                conditions.append(getattr(self.model_class, field) == data[field])
        if not conditions:
            return False
        stmt = select(self.model_class).where(and_(*conditions))
        result = await session.execute(stmt)
        return result.scalar_one_or_none() is not None

    async def _create_record(
        self, session: AsyncSession, data: dict[str, Any]
    ) -> Any | None:
        """Create a single record if it doesn't exist. Returns the record or None."""
        clean = self._strip_meta_keys(data)
        if await self._record_exists(session, clean):
            return None
        record = self.model_class(**clean)
        session.add(record)
        await session.flush()
        return record

    async def load(
        self,
        records: list[dict[str, Any]],
        session: AsyncSession | None = None,
    ) -> dict[str, int]:
        """Load records using batch INSERT ... ON CONFLICT DO NOTHING.

        Falls back to one-by-one ORM inserts for models without unique_fields
        or when batch insert fails (e.g. missing column on remote DB).
        Returns {'created': N, 'skipped': N}.
        """
        if not records:
            return {"created": 0, "skipped": 0}

        created = 0
        skipped = 0
        own_session = session is None
        if own_session:
            session = AsyncSessionLocal()

        try:
            # Strip meta keys from all records upfront
            clean_records = [self._strip_meta_keys(r) for r in records]

            # Try batch insert path when we have unique fields for ON CONFLICT
            if self.unique_fields:
                created, skipped = await self._batch_insert(
                    session, clean_records, batch_size=BATCH_SIZE,
                )
            else:
                # No unique fields — use one-by-one ORM inserts (always create)
                for clean in clean_records:
                    try:
                        record = self.model_class(**clean)
                        session.add(record)
                        await session.flush()
                        created += 1
                    except Exception as exc:
                        logger.warning("Skipping %s record: %s", self.model_class.__name__, exc)
                        await session.rollback()
                        skipped += 1
                    if (created + skipped) % BATCH_SIZE == 0:
                        try:
                            await session.commit()
                        except Exception:
                            await session.rollback()
                try:
                    await session.commit()
                except Exception:
                    await session.rollback()
        except Exception:
            if own_session:
                await session.rollback()
            raise
        finally:
            if own_session:
                await session.close()

        logger.info(
            "%s: %d created, %d skipped",
            self.model_class.__name__,
            created,
            skipped,
        )
        return {"created": created, "skipped": skipped}

    async def _batch_insert(
        self,
        session: AsyncSession,
        clean_records: list[dict[str, Any]],
        batch_size: int = BATCH_SIZE,
    ) -> tuple[int, int]:
        """Batch INSERT ... ON CONFLICT DO NOTHING using SQLAlchemy Core."""
        created = 0
        skipped = 0
        table = self.model_class.__table__
        conflict_cols = [
            table.c[f] for f in self.unique_fields if f in table.c
        ]

        for i in range(0, len(clean_records), batch_size):
            batch = clean_records[i : i + batch_size]
            if not batch:
                continue
            try:
                stmt = pg_insert(table).values(batch)
                if conflict_cols:
                    stmt = stmt.on_conflict_do_nothing(index_elements=conflict_cols)
                result = await session.execute(stmt)
                # rowcount = number of rows actually inserted (not skipped)
                inserted = result.rowcount or 0
                created += inserted
                skipped += len(batch) - inserted
            except Exception as exc:
                logger.warning(
                    "Batch insert failed for %s, falling back to one-by-one: %s",
                    self.model_class.__name__, exc,
                )
                await session.rollback()
                # Fallback: one-by-one for this batch
                for rec in batch:
                    try:
                        if await self._record_exists(session, rec):
                            skipped += 1
                            continue
                        record = self.model_class(**rec)
                        session.add(record)
                        await session.flush()
                        created += 1
                    except Exception:
                        await session.rollback()
                        skipped += 1
            await session.commit()

        return created, skipped

    async def clear_all(self, session: AsyncSession | None = None) -> int:
        """Delete all records for this model."""
        own_session = session is None
        if own_session:
            session = AsyncSessionLocal()
        try:
            result = await session.execute(delete(self.model_class))
            await session.commit()
            count = result.rowcount or 0
            logger.info("Cleared %d %s records", count, self.model_class.__name__)
            return count
        finally:
            if own_session:
                await session.close()


class SimpleLoader(BaseLoader):
    """Generic loader that takes a model class and unique fields."""

    def __init__(self, model_cls: type, unique: list[str]) -> None:
        self._model = model_cls
        self._unique = unique

    @property
    def model_class(self) -> type:
        return self._model

    @property
    def unique_fields(self) -> list[str]:
        return self._unique


def _model_columns(model: type | None) -> set[str] | None:
    """Return the set of column names for a SQLAlchemy model, or None if model is None."""
    if model is None:
        return None
    return set(model.__table__.columns.keys())


def resolve_media_value(
    value: Any, media_urls: dict[str, str] | None, *, key: str = ""
) -> Any:
    """Resolve a ``media/...`` reference to a Cloudinary URL.

    Centralised rule so loaders never persist a broken placeholder:

    * ``media_urls is None`` → media resolution is not applicable for this data
      (e.g. generated activity); the value is left untouched.
    * otherwise a ``media/...`` ref must map to an ``http(s)://`` URL. A missing
      entry, an empty map (``--skip-media`` / failed upload), or a
      ``placeholder://`` fallback value all yield ``None`` plus an ERROR log,
      so the app shows a placeholder avatar instead of a 404 and the operator
      is alerted instead of silently storing a relative path.
    """
    if media_urls is None or not isinstance(value, str) or not value.startswith("media/"):
        return value
    resolved = media_urls.get(value)
    if isinstance(resolved, str) and (resolved.startswith("http://") or resolved.startswith("https://")):
        return resolved
    logger.error(
        "Unresolved media ref %r in field %r — setting NULL "
        "(re-run seeding without --skip-media, or verify Cloudinary credentials).",
        value, key or "<unknown>",
    )
    return None


def resolve_refs(
    data: dict[str, Any],
    id_map: IDMap,
    media_urls: dict[str, str] | None = None,
    *,
    model: type | None = None,
) -> dict[str, Any]:
    """Replace *_ref keys with actual DB IDs, strip meta keys, and resolve media/ URLs.

    Centralised reference resolution used by all loaders. Set media_urls=None
    when media URL resolution is not needed (e.g. activity data).

    When ``model`` is provided, auto-injected fields (updated_at, location)
    are only added if the model's table actually has those columns.
    """
    out = {k: v for k, v in data.items() if not k.startswith("_")}
    cols = _model_columns(model)

    # Resolve user references by email
    for key in (
        "owner_id", "user_id", "tenant_user_id", "created_by_user_id",
        "conducted_by_user_id", "assigned_agent_id", "author_id",
        "sender_id", "viewer_user_id", "blocker_user_id", "blocked_user_id",
        "reporter_user_id", "reported_user_id", "viewed_user_id",
        "target_user_id", "counterparty_user_id",
        "user_one_id", "user_two_id",
    ):
        ref_key = f"{key}_ref"
        if ref_key in out:
            ref_val = out.pop(ref_key)
            db_id = id_map.get("user", ref_val)
            if db_id:
                out[key] = db_id
            else:
                logger.debug("Could not resolve user ref %s → %s", ref_key, ref_val)

    # Resolve agent references by name
    for key in ("agent_id", "assigned_agent_id"):
        ref_key = f"{key}_ref"
        if ref_key in out:
            ref_val = out.pop(ref_key)
            db_id = id_map.get("agent", ref_val)
            if db_id:
                out[key] = db_id

    # Resolve property references by title
    for key in ("property_id", "listing_id", "context_property_id"):
        ref_key = f"{key}_ref"
        if ref_key in out:
            ref_val = out.pop(ref_key)
            db_id = id_map.get("property", ref_val)
            if db_id:
                out[key] = db_id

    # Resolve tour references by title
    for key in ("tour_id",):
        ref_key = f"{key}_ref"
        if ref_key in out:
            ref_val = out.pop(ref_key)
            db_id = id_map.get("tour", ref_val)
            if db_id:
                out[key] = db_id

    # Resolve lease references
    for key in ("lease_id",):
        ref_key = f"{key}_ref"
        if ref_key in out:
            ref_val = out.pop(ref_key)
            db_id = id_map.get("lease", ref_val)
            if db_id:
                out[key] = db_id

    # Resolve rental form references by slug
    for key in ("form_id",):
        ref_key = f"{key}_ref"
        if ref_key in out:
            ref_val = out.pop(ref_key)
            db_id = id_map.get("rental_form", ref_val)
            if db_id:
                out[key] = db_id

    # Resolve rent charge references
    for key in ("charge_id",):
        ref_key = f"{key}_ref"
        if ref_key in out:
            ref_val = out.pop(ref_key)
            db_id = id_map.get("rent_charge", ref_val)
            if db_id:
                out[key] = db_id

    # Resolve conversation references
    for key in ("conversation_id",):
        ref_key = f"{key}_ref"
        if ref_key in out:
            ref_val = out.pop(ref_key)
            db_id = id_map.get("conversation", ref_val)
            if db_id:
                out[key] = db_id

    # Resolve match references
    for key in ("match_id",):
        ref_key = f"{key}_ref"
        if ref_key in out:
            ref_val = out.pop(ref_key)
            db_id = id_map.get("match", ref_val)
            if db_id:
                out[key] = db_id

    # Resolve media/ URL references. Unresolved refs become NULL (never a
    # relative path) — see resolve_media_value for the rule.
    if media_urls is not None:
        for key, value in list(out.items()):
            out[key] = resolve_media_value(value, media_urls, key=key)

    # Default updated_at to now() if not present (remote DB has NOT NULL constraint)
    # Only inject when the model actually has an updated_at column
    if (cols is None or "updated_at" in cols) and "updated_at" not in out:
        out["updated_at"] = datetime.now(timezone.utc)

    # Populate PostGIS location from latitude/longitude if present
    # Only inject when the model actually has a location column
    lat = out.get("latitude")
    lng = out.get("longitude")
    if lat is not None and lng is not None and (cols is None or "location" in cols) and "location" not in out:
        out["location"] = f"SRID=4326;POINT({lng} {lat})"

    return out
