from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.schemas.pagination import read_keyset
from app.services.ai_agent import conversation_store


def _make_db():
    db = AsyncMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    return db


@pytest.mark.asyncio
async def test_get_owned_conversation_returns_owned_row():
    db = _make_db()
    existing = SimpleNamespace(id=7, user_id=4, title="Existing")
    db.execute = AsyncMock(return_value=SimpleNamespace(scalar_one_or_none=lambda: existing))

    conv = await conversation_store.get_owned_conversation(db, user_id=4, conversation_id=7)

    assert conv is existing
    db.add.assert_not_called()


@pytest.mark.asyncio
async def test_get_owned_conversation_returns_none_for_other_user():
    # The query filters by user_id, so a foreign conversation yields no row (404 at the route).
    db = _make_db()
    db.execute = AsyncMock(return_value=SimpleNamespace(scalar_one_or_none=lambda: None))

    conv = await conversation_store.get_owned_conversation(db, user_id=10, conversation_id=999)

    assert conv is None


@pytest.mark.asyncio
async def test_create_conversation_adds_row_for_user():
    db = _make_db()

    conv = await conversation_store.create_conversation(db, user_id=10)

    assert conv.user_id == 10
    db.add.assert_called_once_with(conv)
    db.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_add_message_sets_conversation_title_from_first_user_message():
    db = _make_db()
    conv = SimpleNamespace(id=12, title=None)
    db.execute = AsyncMock(return_value=SimpleNamespace(scalar_one_or_none=lambda: conv))

    msg = await conversation_store.add_message(
        db,
        conversation_id=12,
        role="user",
        content="  First user message for title generation  ",
    )

    assert msg.role == "user"
    assert conv.title == "First user message for title generation"
    assert db.flush.await_count == 2


@pytest.mark.asyncio
async def test_add_message_does_not_override_existing_title_or_non_user_role():
    db = _make_db()
    conv = SimpleNamespace(id=13, title="Keep title")
    db.execute = AsyncMock(return_value=SimpleNamespace(scalar_one_or_none=lambda: conv))

    await conversation_store.add_message(
        db,
        conversation_id=13,
        role="assistant",
        content="Assistant reply",
    )
    await conversation_store.add_message(
        db,
        conversation_id=13,
        role="user",
        content="User follow-up",
    )

    assert conv.title == "Keep title"
    assert db.flush.await_count == 2


@pytest.mark.asyncio
async def test_get_history_reverses_descending_query_order_and_applies_limit():
    db = _make_db()
    m1 = SimpleNamespace(id=1)
    m2 = SimpleNamespace(id=2)
    m3 = SimpleNamespace(id=3)
    db.execute = AsyncMock(
        return_value=SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: [m3, m2, m1]))
    )

    history = await conversation_store.get_history(db, conversation_id=30, limit=3)

    assert history == [m1, m2, m3]
    stmt = db.execute.await_args.args[0]
    assert stmt._limit_clause.value == 3


@pytest.mark.asyncio
async def test_list_conversations_handles_none_message_count():
    now = datetime.now(timezone.utc)
    conv_a = SimpleNamespace(id=1, title=None, created_at=now, updated_at=now)
    conv_b = SimpleNamespace(id=2, title="B", created_at=now, updated_at=now)
    db = _make_db()
    db.execute = AsyncMock(return_value=SimpleNamespace(all=lambda: [(conv_a, None), (conv_b, 4)]))

    rows, next_payload, total = await conversation_store.list_conversations(
        db, user_id=77, cursor_payload={}, limit=20
    )

    assert rows[0]["message_count"] == 0
    assert rows[1]["message_count"] == 4
    assert rows[0]["created_at"] == now
    assert next_payload is None
    assert total is None


@pytest.mark.asyncio
async def test_list_conversations_pages_by_keyset_not_offset():
    newer = datetime(2026, 10, 14, 9, 0, tzinfo=timezone.utc)
    older = datetime(2026, 10, 14, 8, 0, tzinfo=timezone.utc)
    page_one = [
        (SimpleNamespace(id=5, title="New", created_at=newer, updated_at=newer), 1),
        (SimpleNamespace(id=4, title="Old", created_at=older, updated_at=older), 2),
    ]
    db = _make_db()
    db.execute = AsyncMock(return_value=SimpleNamespace(all=lambda: page_one))

    rows, next_payload, total = await conversation_store.list_conversations(
        db, user_id=77, cursor_payload={}, limit=1
    )

    # The lookahead row shows another page. The cursor holds the last row's (updated_at, id).
    assert [r["id"] for r in rows] == [5]
    assert total is None
    assert read_keyset(next_payload)[1] == 5
    first_stmt = db.execute.await_args.args[0]
    assert first_stmt._limit_clause.value == 2
    assert first_stmt._offset_clause is None

    # The next page filters by the keyset and carries no offset.
    db.execute = AsyncMock(return_value=SimpleNamespace(all=lambda: []))
    await conversation_store.list_conversations(
        db, user_id=77, cursor_payload=next_payload, limit=1
    )
    next_stmt = db.execute.await_args.args[0]
    assert next_stmt._offset_clause is None
    assert next_stmt._where_criteria


@pytest.mark.asyncio
async def test_delete_conversation_returns_boolean_based_on_rowcount():
    db = _make_db()
    db.execute = AsyncMock(return_value=SimpleNamespace(rowcount=1))

    deleted = await conversation_store.delete_conversation(
        db,
        conversation_id=5,
        user_id=8,
    )
    assert deleted is True
    db.flush.assert_awaited_once()

    db.flush.reset_mock()
    db.execute = AsyncMock(return_value=SimpleNamespace(rowcount=0))
    deleted = await conversation_store.delete_conversation(
        db,
        conversation_id=5,
        user_id=8,
    )
    assert deleted is False
