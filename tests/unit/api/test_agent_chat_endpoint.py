from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from app.api.api_v1.endpoints.agent_chat import (
    agent_chat,
    delete_conversation,
    get_conversation_messages,
    get_widget_html,
    list_conversations,
)
from app.schemas.ai_agent import AgentChatRequest
from app.schemas.pagination import CursorParams, offset_payload


class _FakeService:
    def __init__(self, events):
        self._events = events

    async def stream_response(self, **_kwargs):
        for event in self._events:
            yield event


class _ErrorService:
    async def stream_response(self, **_kwargs):
        if False:
            yield ""
        raise RuntimeError("stream exploded")


def _history_row(role: str, content: str):
    return SimpleNamespace(
        role=role,
        content=content,
        tool_name=None,
        tool_args=None,
        tool_result=None,
    )


async def _collect_sse(response) -> str:
    chunks = []
    async for chunk in response.body_iterator:
        if isinstance(chunk, bytes):
            chunks.append(chunk.decode("utf-8"))
        else:
            chunks.append(chunk)
    return "".join(chunks)


@pytest.mark.asyncio
async def test_agent_chat_persists_widget_and_assistant_messages():
    db = AsyncMock()
    db.commit = AsyncMock()
    current_user = SimpleNamespace(id=1)

    with (
        patch(
            "app.api.api_v1.endpoints.agent_chat.conversation_store.get_or_create_conversation",
            new=AsyncMock(return_value=SimpleNamespace(id=10)),
        ),
        patch(
            "app.api.api_v1.endpoints.agent_chat.conversation_store.get_history",
            new=AsyncMock(return_value=[_history_row("user", "hello")]),
        ),
        patch(
            "app.api.api_v1.endpoints.agent_chat.conversation_store.add_message",
            new_callable=AsyncMock,
        ) as mock_add_message,
        patch(
            "app.api.api_v1.endpoints.agent_chat.get_agent_service",
            return_value=_FakeService(
                [
                    'event: widget\ndata: {"widget_name":"OwnerDashboardWidget","structured_content":{"cards":1}}\n\n',
                    'event: done\ndata: {"response_text":"Here is your summary"}\n\n',
                ]
            ),
        ),
    ):
        response = await agent_chat(
            body=AgentChatRequest(message="Show dashboard"),
            current_user=current_user,
            db=db,
        )
        stream_text = await _collect_sse(response)

    assert "Here is your summary" in stream_text
    roles = [c.kwargs.get("role") for c in mock_add_message.await_args_list]
    assert roles == ["user", "widget", "assistant"]
    assert mock_add_message.await_args_list[1].kwargs["tool_name"] == "OwnerDashboardWidget"
    assert mock_add_message.await_args_list[1].kwargs["tool_result"] == {"cards": 1}
    assert mock_add_message.await_args_list[2].kwargs["content"] == "Here is your summary"


@pytest.mark.asyncio
async def test_agent_chat_persists_empty_assistant_when_only_widget_event():
    db = AsyncMock()
    db.commit = AsyncMock()
    current_user = SimpleNamespace(id=1)

    with (
        patch(
            "app.api.api_v1.endpoints.agent_chat.conversation_store.get_or_create_conversation",
            new=AsyncMock(return_value=SimpleNamespace(id=11)),
        ),
        patch(
            "app.api.api_v1.endpoints.agent_chat.conversation_store.get_history",
            new=AsyncMock(return_value=[_history_row("user", "hello")]),
        ),
        patch(
            "app.api.api_v1.endpoints.agent_chat.conversation_store.add_message",
            new_callable=AsyncMock,
        ) as mock_add_message,
        patch(
            "app.api.api_v1.endpoints.agent_chat.get_agent_service",
            return_value=_FakeService(
                ['event: widget\ndata: {"widget_name":"RentCollectionWidget","structured_content":{"total_due":5000}}\n\n']
            ),
        ),
    ):
        response = await agent_chat(
            body=AgentChatRequest(message="Show rent"),
            current_user=current_user,
            db=db,
        )
        await _collect_sse(response)

    roles = [c.kwargs.get("role") for c in mock_add_message.await_args_list]
    assert roles == ["user", "widget", "assistant"]
    assert mock_add_message.await_args_list[2].kwargs["content"] == ""


@pytest.mark.asyncio
async def test_agent_chat_ignores_malformed_widget_event():
    db = AsyncMock()
    db.commit = AsyncMock()
    current_user = SimpleNamespace(id=1)

    with (
        patch(
            "app.api.api_v1.endpoints.agent_chat.conversation_store.get_or_create_conversation",
            new=AsyncMock(return_value=SimpleNamespace(id=12)),
        ),
        patch(
            "app.api.api_v1.endpoints.agent_chat.conversation_store.get_history",
            new=AsyncMock(return_value=[_history_row("user", "hello")]),
        ),
        patch(
            "app.api.api_v1.endpoints.agent_chat.conversation_store.add_message",
            new_callable=AsyncMock,
        ) as mock_add_message,
        patch(
            "app.api.api_v1.endpoints.agent_chat.get_agent_service",
            return_value=_FakeService(
                [
                    'event: widget\ndata: {"widget_name":\n\n',
                    'event: done\ndata: {"response_text":"fallback"}\n\n',
                ]
            ),
        ),
    ):
        response = await agent_chat(
            body=AgentChatRequest(message="test malformed"),
            current_user=current_user,
            db=db,
        )
        await _collect_sse(response)

    roles = [c.kwargs.get("role") for c in mock_add_message.await_args_list]
    assert roles == ["user", "assistant"]
    assert mock_add_message.await_args_list[1].kwargs["content"] == "fallback"


@pytest.mark.asyncio
async def test_agent_chat_stream_error_emits_error_event():
    db = AsyncMock()
    db.commit = AsyncMock()
    current_user = SimpleNamespace(id=1)

    with (
        patch(
            "app.api.api_v1.endpoints.agent_chat.conversation_store.get_or_create_conversation",
            new=AsyncMock(return_value=SimpleNamespace(id=13)),
        ),
        patch(
            "app.api.api_v1.endpoints.agent_chat.conversation_store.get_history",
            new=AsyncMock(return_value=[_history_row("user", "hello")]),
        ),
        patch(
            "app.api.api_v1.endpoints.agent_chat.conversation_store.add_message",
            new_callable=AsyncMock,
        ) as mock_add_message,
        patch(
            "app.api.api_v1.endpoints.agent_chat.get_agent_service",
            return_value=_ErrorService(),
        ),
    ):
        response = await agent_chat(
            body=AgentChatRequest(message="trigger error"),
            current_user=current_user,
            db=db,
        )
        stream_text = await _collect_sse(response)

    assert "STREAM_ERROR" in stream_text
    assert "stream exploded" in stream_text
    assert len(mock_add_message.await_args_list) == 1
    assert mock_add_message.await_args_list[0].kwargs["role"] == "user"


@pytest.mark.asyncio
async def test_list_conversations_delegates_to_store_and_respects_pagination():
    db = AsyncMock()
    current_user = SimpleNamespace(id=9)
    expected_items = [{"id": 1, "title": "T1"}]
    next_payload = offset_payload(35)

    page = CursorParams(cursor=None, limit=25, include_total=True)

    with patch(
        "app.api.api_v1.endpoints.agent_chat.conversation_store.list_conversations",
        new=AsyncMock(return_value=(expected_items, next_payload, 1)),
    ) as mock_list:
        result = await list_conversations(
            page=page,
            current_user=current_user,
            db=db,
        )

    assert result["items"] == expected_items
    assert result["has_more"] is True
    assert result["next_cursor"] is not None
    assert result["limit"] == 25
    assert result["total"] == 1
    mock_list.assert_awaited_once_with(
        db,
        user_id=9,
        cursor_payload={},
        limit=25,
        with_total=True,
    )


@pytest.mark.asyncio
async def test_get_conversation_messages_success_maps_widget_fields():
    db = AsyncMock()
    current_user = SimpleNamespace(id=5)
    conv = SimpleNamespace(id=33, user_id=5)
    now = datetime.now(timezone.utc)
    message_row = SimpleNamespace(
        id=1,
        role="widget",
        content=None,
        tool_name="OwnerDashboardWidget",
        tool_args=None,
        tool_result={"cards": 2},
        created_at=now,
    )
    query_result = SimpleNamespace(scalar_one_or_none=lambda: conv)
    db.execute = AsyncMock(return_value=query_result)

    with patch(
        "app.api.api_v1.endpoints.agent_chat.conversation_store.get_history",
        new=AsyncMock(return_value=[message_row]),
    ):
        result = await get_conversation_messages(
            conversation_id=33,
            current_user=current_user,
            db=db,
            limit=100,
        )

    assert len(result) == 1
    assert result[0].widget_name == "OwnerDashboardWidget"
    assert result[0].widget_data == {"cards": 2}


@pytest.mark.asyncio
async def test_get_conversation_messages_raises_404_when_not_owned():
    db = AsyncMock()
    current_user = SimpleNamespace(id=5)
    query_result = SimpleNamespace(scalar_one_or_none=lambda: None)
    db.execute = AsyncMock(return_value=query_result)

    with pytest.raises(HTTPException) as exc:
        await get_conversation_messages(
            conversation_id=999,
            current_user=current_user,
            db=db,
            limit=100,
        )

    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_delete_conversation_success_commits():
    db = AsyncMock()
    db.commit = AsyncMock()
    current_user = SimpleNamespace(id=2)

    with patch(
        "app.api.api_v1.endpoints.agent_chat.conversation_store.delete_conversation",
        new=AsyncMock(return_value=True),
    ) as mock_delete:
        result = await delete_conversation(
            conversation_id=8,
            current_user=current_user,
            db=db,
        )

    assert result is None
    mock_delete.assert_awaited_once_with(db, conversation_id=8, user_id=2)
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_delete_conversation_raises_404_when_missing():
    db = AsyncMock()
    db.commit = AsyncMock()
    current_user = SimpleNamespace(id=2)

    with patch(
        "app.api.api_v1.endpoints.agent_chat.conversation_store.delete_conversation",
        new=AsyncMock(return_value=False),
    ):
        with pytest.raises(HTTPException) as exc:
            await delete_conversation(
                conversation_id=8,
                current_user=current_user,
                db=db,
            )

    assert exc.value.status_code == 404
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_get_widget_html_success():
    with patch(
        "app.mcp.chatgpt.load_widget_html",
        return_value="<html>ok</html>",
    ):
        response = await get_widget_html("OwnerDashboardWidget")

    assert response.status_code == 200
    assert response.body.decode("utf-8") == "<html>ok</html>"
    assert response.headers["cache-control"] == "public, max-age=3600"


@pytest.mark.asyncio
async def test_get_widget_html_not_found_raises_404():
    with patch(
        "app.mcp.chatgpt.load_widget_html",
        return_value=None,
    ):
        with pytest.raises(HTTPException) as exc:
            await get_widget_html("MissingWidget")

    assert exc.value.status_code == 404
