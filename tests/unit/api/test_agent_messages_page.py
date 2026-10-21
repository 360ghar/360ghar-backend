"""GET /agent/conversations/{id}/messages/page: keyset pages of assistant messages."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy.dialects import postgresql

from app.api.api_v1.endpoints.agent_chat import get_conversation_messages_page
from app.core.exceptions import BadRequestException
from app.schemas.pagination import decode_cursor
from app.services.ai_agent import conversation_store

T0 = datetime(2026, 9, 1, tzinfo=timezone.utc)


def _msg(msg_id: int, minute: int, conversation_id: int = 7):
    return SimpleNamespace(
        id=msg_id,
        conversation_id=conversation_id,
        role="user" if msg_id % 2 else "assistant",
        content=f"m{msg_id}",
        tool_name=None,
        tool_args=None,
        tool_result=None,
        created_at=T0 + timedelta(minutes=minute),
    )


# Ids 1..7; ids 4 and 5 share a timestamp so the id tie-break is exercised.
ROWS = [
    _msg(1, 0),
    _msg(2, 1),
    _msg(3, 2),
    _msg(4, 3),
    _msg(5, 3),
    _msg(6, 4),
    _msg(7, 5),
    _msg(99, 9, conversation_id=8),
]


class _KeysetDb:
    """Runs the store's SELECT against in-memory rows, using the statement's bound params."""

    def __init__(self, rows):
        self.rows = rows
        self.sql: list[str] = []

    async def execute(self, stmt):
        compiled = stmt.compile(dialect=postgresql.dialect())
        self.sql.append(str(compiled))
        params = compiled.params
        rows = [r for r in self.rows if r.conversation_id == params["conversation_id_1"]]
        if "param_3" in params:  # keyset predicate + limit
            key = (datetime.fromisoformat(params["param_1"]), params["param_2"])
            rows = [r for r in rows if (r.created_at, r.id) < key]
            limit = params["param_3"]
        else:
            limit = params["param_1"]
        rows = sorted(rows, key=lambda r: (r.created_at, r.id), reverse=True)[:limit]
        return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: rows))


async def test_store_walks_back_in_time_with_chronological_pages():
    db = _KeysetDb(ROWS)

    page1, cursor1 = await conversation_store.get_history_page(db, 7, cursor_payload={}, limit=3)
    assert [m.id for m in page1] == [5, 6, 7]  # newest three, oldest first
    assert (
        "ORDER BY ai_conversation_messages.created_at DESC, ai_conversation_messages.id DESC"
        in db.sql[0]
    )
    assert cursor1 is not None

    page2, cursor2 = await conversation_store.get_history_page(
        db, 7, cursor_payload=cursor1, limit=3
    )
    assert [m.id for m in page2] == [2, 3, 4]
    assert cursor2 is not None

    page3, cursor3 = await conversation_store.get_history_page(
        db, 7, cursor_payload=cursor2, limit=3
    )
    assert [m.id for m in page3] == [1]
    assert cursor3 is None  # end of history


async def test_store_exact_fit_has_no_next_cursor():
    page, cursor = await conversation_store.get_history_page(
        _KeysetDb(ROWS), 7, cursor_payload={}, limit=7
    )
    assert [m.id for m in page] == [1, 2, 3, 4, 5, 6, 7]
    assert cursor is None


def _owned_db(conv):
    db = AsyncMock()
    db.execute = AsyncMock(return_value=SimpleNamespace(scalar_one_or_none=lambda: conv))
    return db


async def test_endpoint_builds_cursor_page():
    rows = [_msg(6, 4), _msg(7, 5)]
    store = AsyncMock(return_value=(rows, {"v": 1, "k": ["2026-09-01T00:04:00+00:00", 6]}))
    with patch.object(conversation_store, "get_history_page", new=store):
        page = await get_conversation_messages_page(
            conversation_id=7,
            cursor=None,
            limit=2,
            current_user=SimpleNamespace(id=5),
            db=_owned_db(SimpleNamespace(id=7)),
        )

    assert [m.id for m in page["items"]] == [6, 7]
    assert page["has_more"] is True and page["limit"] == 2
    # The cursor is bound to the conversation: it decodes only with that filter.
    assert decode_cursor(page["next_cursor"], {"conversation_id": 7})["k"] == [
        "2026-09-01T00:04:00+00:00",
        6,
    ]
    assert "total" not in page
    store.assert_awaited_once()
    assert store.await_args.kwargs == {"cursor_payload": {}, "limit": 2}


async def test_endpoint_foreign_conversation_is_404_like_messages_route():
    with pytest.raises(HTTPException) as exc:
        await get_conversation_messages_page(
            conversation_id=999,
            cursor=None,
            limit=30,
            current_user=SimpleNamespace(id=5),
            db=_owned_db(None),
        )
    assert exc.value.status_code == 404
    assert exc.value.detail == "Conversation not found"


async def test_endpoint_invalid_cursor_is_invalid_cursor():
    with pytest.raises(BadRequestException) as exc:
        await get_conversation_messages_page(
            conversation_id=7,
            cursor="not-a-cursor",
            limit=30,
            current_user=SimpleNamespace(id=5),
            db=_owned_db(SimpleNamespace(id=7)),
        )
    assert exc.value.error_code == "INVALID_CURSOR"


def test_route_is_registered_with_limits_and_error_envelope():
    from app.api.api_v1.dependencies.auth import get_current_active_user
    from app.core.database import get_db
    from app.factory import create_app

    app = create_app(testing=True)
    app.dependency_overrides[get_current_active_user] = lambda: SimpleNamespace(id=5)
    app.dependency_overrides[get_db] = lambda: _owned_db(SimpleNamespace(id=7))
    client = TestClient(app, raise_server_exceptions=False)
    url = "/api/v1/agent/conversations/7/messages/page"

    store = AsyncMock(return_value=([_msg(1, 0), _msg(2, 1)], None))
    with patch.object(conversation_store, "get_history_page", new=store):
        ok = client.get(url)
    assert ok.status_code == 200
    body = ok.json()
    assert [m["id"] for m in body["items"]] == [1, 2]
    assert body["next_cursor"] is None and body["has_more"] is False and body["limit"] == 30

    assert client.get(url, params={"limit": 0}).status_code == 422
    assert client.get(url, params={"limit": 101}).status_code == 422
    bad = client.get(url, params={"cursor": "%%%"})
    assert bad.status_code == 400
    assert bad.json()["error"]["code"] == "INVALID_CURSOR"


def test_bare_messages_route_is_removed_and_the_page_route_is_a_cursor_page():
    """webui2-3: the bare list route is gone (no installed builds). Only /messages/page remains."""
    from app.api.api_v1.dependencies.auth import get_current_active_user
    from app.core.database import get_db
    from app.factory import create_app

    app = create_app(testing=True)
    app.dependency_overrides[get_current_active_user] = lambda: SimpleNamespace(id=5)
    app.dependency_overrides[get_db] = lambda: _owned_db(SimpleNamespace(id=7))
    client = TestClient(app, raise_server_exceptions=False)

    bare = client.get("/api/v1/agent/conversations/7/messages")
    assert bare.status_code == 404
    assert bare.json()["error"]["code"] == "NOT_FOUND"
    paths = app.openapi()["paths"]
    assert "/api/v1/agent/conversations/{conversation_id}/messages" not in paths
    assert "/api/v1/agent/conversations/{conversation_id}/messages/page" in paths

    with patch.object(
        conversation_store, "get_history_page", new=AsyncMock(return_value=([], None))
    ):
        paged = client.get("/api/v1/agent/conversations/7/messages/page")
    assert paged.status_code == 200
    assert set(paged.json()) >= {"items", "next_cursor", "has_more", "limit"}


async def test_page_route_maps_widget_rows_to_widget_fields():
    """Kept from the removed bare route test: a widget row exposes widget_name and widget_data."""
    widget = SimpleNamespace(
        id=1,
        role="widget",
        content=None,
        tool_name="OwnerDashboardWidget",
        tool_args=None,
        tool_result={"cards": 2},
        created_at=T0,
    )
    store = AsyncMock(return_value=([widget], None))
    with patch.object(conversation_store, "get_history_page", new=store):
        page = await get_conversation_messages_page(
            7,
            cursor=None,
            limit=30,
            current_user=SimpleNamespace(id=5),
            db=_owned_db(SimpleNamespace(id=7)),
        )
    item = page["items"][0]
    assert item.widget_name == "OwnerDashboardWidget"
    assert item.widget_data == {"cards": 2}
