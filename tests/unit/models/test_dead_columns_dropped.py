"""BE-tours residual pass: two dead columns are removed (lead decision: drop non-user-data dead columns).

- media_files.processing_metadata (r2-json-blobs-6): no reader; the only write is NULL.
- conversations.context_data: written with a match_id by flatmates, never read.

Both the ORM and the migration must agree. Without the DROP statements, the migration
test keeps the columns and fails.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError
from sqlalchemy import text

from app.models.conversations import Conversation
from app.models.tours import MediaFile
from app.schemas.storage import MediaFileResponse, MediaUpdateRequest

MIGRATION = (
    Path(__file__).resolve().parents[3]
    / "supabase"
    / "migrations"
    / "20261014006005_drop_dead_columns.sql"
)


def test_orm_has_no_dead_columns():
    assert "processing_metadata" not in MediaFile.__table__.c
    assert "context_data" not in Conversation.__table__.c


def test_media_schemas_no_longer_carry_processing_metadata():
    assert "processing_metadata" not in MediaFileResponse.model_fields
    with pytest.raises(ValidationError):
        MediaUpdateRequest.model_validate({"processing_metadata": {"width": 1}})


@pytest.mark.asyncio
async def test_migration_drops_both_dead_columns(db_session):
    await db_session.execute(
        text("ALTER TABLE media_files ADD COLUMN IF NOT EXISTS processing_metadata JSONB")
    )
    await db_session.execute(
        text("ALTER TABLE conversations ADD COLUMN IF NOT EXISTS context_data JSONB")
    )

    await db_session.execute(text(MIGRATION.read_text(encoding="utf-8")))

    result = await db_session.execute(
        text(
            "SELECT table_name, column_name FROM information_schema.columns "
            "WHERE table_schema = 'public' AND ("
            "(table_name = 'media_files' AND column_name = 'processing_metadata') OR "
            "(table_name = 'conversations' AND column_name = 'context_data'))"
        )
    )
    assert result.all() == []
