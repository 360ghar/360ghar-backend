import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from app.api.api_v1.endpoints.agent_chat import (
    agent_chat,
    delete_conversation,
    get_widget_html,
    list_conversations,
)
from app.schemas.ai_agent import (
    AgentChatRequest,
    ConversationInfoFrame,
    DoneFrame,
    ErrorFrame,
    TextChunkFrame,
    ToolCallEndFrame,
    ToolCallStartFrame,
    WidgetFrame,
    make_widget_data,
)
from app.schemas.pagination import CursorParams, offset_payload

_FRAME_TYPES = {
    "conversation_info": ConversationInfoFrame,
    "text_chunk": TextChunkFrame,
    "tool_call_start": ToolCallStartFrame,
    "tool_call_end": ToolCallEndFrame,
    "widget": WidgetFrame,
    "done": DoneFrame,
    "error": ErrorFrame,
}


def _frame(name: str, data: dict):
    """Build the typed frame the agent service yields for ``(name, data)``."""
    if name == "widget":
        return WidgetFrame(
            data=make_widget_data(data["widget_name"], data.get("structured_content") or {})
        )
    frame_cls = _FRAME_TYPES[name]
    data_cls = frame_cls.model_fields["data"].annotation
    return frame_cls(data=data_cls(**data))


class _FakeService:
    """Yields typed frames, matching ``stream_events``."""

    def __init__(self, events):
        self._events = events

    async def stream_events(self, **_kwargs):
        for name, data in self._events:
            yield _frame(name, data)


class _ErrorService:
    async def stream_events(self, **_kwargs):
        if False:
            yield ("", {})
        raise RuntimeError("stream exploded")


def _history_row(role: str, content: str, row_id: int = 1):
    return SimpleNamespace(
        id=row_id,
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
            "app.api.api_v1.endpoints.agent_chat.conversation_store.create_conversation",
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
                    (
                        "widget",
                        {
                            "widget_name": "OwnerDashboardWidget",
                            "structured_content": {"cards": 1},
                        },
                    ),
                    ("done", {"response_text": "Here is your summary"}),
                ]
            ),
        ),
    ):
        response = await agent_chat(
            request=None,
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
            "app.api.api_v1.endpoints.agent_chat.conversation_store.create_conversation",
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
                [
                    (
                        "widget",
                        {
                            "widget_name": "RentCollectionWidget",
                            "structured_content": {"total_due": 5000},
                        },
                    )
                ]
            ),
        ),
    ):
        response = await agent_chat(
            request=None,
            body=AgentChatRequest(message="Show rent"),
            current_user=current_user,
            db=db,
        )
        await _collect_sse(response)

    roles = [c.kwargs.get("role") for c in mock_add_message.await_args_list]
    assert roles == ["user", "widget", "assistant"]
    assert mock_add_message.await_args_list[2].kwargs["content"] == ""


@pytest.mark.asyncio
async def test_agent_chat_text_chunk_cannot_clobber_persisted_response():
    """A text_chunk mentioning the ``done`` field names must not be mistaken for it.

    The endpoint used to recover ``response_text`` by substring-sniffing the
    serialized SSE frame, so streamed prose containing those literals overwrote
    the real answer. It now reads the typed event payloads.
    """
    db = AsyncMock()
    db.commit = AsyncMock()
    current_user = SimpleNamespace(id=1)

    with (
        patch(
            "app.api.api_v1.endpoints.agent_chat.conversation_store.create_conversation",
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
                    ("text_chunk", {"text": 'the key is "response_text" and '}),
                    ("text_chunk", {"text": 'also "widget_name" here'}),
                    ("done", {"response_text": "the real answer"}),
                ]
            ),
        ),
    ):
        response = await agent_chat(
            request=None,
            body=AgentChatRequest(message="explain the sse contract"),
            current_user=current_user,
            db=db,
        )
        await _collect_sse(response)

    roles = [c.kwargs.get("role") for c in mock_add_message.await_args_list]
    assert roles == ["user", "assistant"]
    assert mock_add_message.await_args_list[1].kwargs["content"] == "the real answer"


@pytest.mark.asyncio
async def test_agent_chat_stream_error_emits_error_event():
    db = AsyncMock()
    db.commit = AsyncMock()
    current_user = SimpleNamespace(id=1)

    with (
        patch(
            "app.api.api_v1.endpoints.agent_chat.conversation_store.create_conversation",
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
            request=None,
            body=AgentChatRequest(message="trigger error"),
            current_user=current_user,
            db=db,
        )
        stream_text = await _collect_sse(response)

    assert "STREAM_ERROR" in stream_text
    assert "stream exploded" not in stream_text
    assert "could not finish this reply" in stream_text
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


@pytest.mark.asyncio
async def test_agent_chat_foreign_or_unknown_conversation_is_404():
    """Another user's conversation id must not be reused (or silently replaced)."""
    db = AsyncMock()
    current_user = SimpleNamespace(id=1)

    with (
        patch(
            "app.api.api_v1.endpoints.agent_chat.conversation_store.get_owned_conversation",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "app.api.api_v1.endpoints.agent_chat.conversation_store.create_conversation",
            new=AsyncMock(),
        ) as mock_create,
    ):
        with pytest.raises(HTTPException) as exc:
            await agent_chat(
                request=None,
                body=AgentChatRequest(message="hi", conversation_id=999),
                current_user=current_user,
                db=db,
            )

    assert exc.value.status_code == 404
    mock_create.assert_not_awaited()


class _HangingService:
    """Yields a widget and some text, then waits as if the model were still streaming."""

    async def stream_events(self, **_kwargs):
        yield _frame("widget", {"widget_name": "OwnerDashboardWidget", "structured_content": {"a": 1}})
        yield _frame("text_chunk", {"text": "Partial "})
        yield _frame("text_chunk", {"text": "reply"})
        await asyncio.sleep(3600)


@pytest.mark.asyncio
async def test_agent_chat_disconnect_before_done_persists_partial_reply():
    import asyncio as _asyncio

    db = AsyncMock()
    with (
        patch(
            "app.api.api_v1.endpoints.agent_chat.conversation_store.create_conversation",
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
            return_value=_HangingService(),
        ),
    ):
        response = await agent_chat(
            request=None,
            body=AgentChatRequest(message="Show dashboard"),
            current_user=SimpleNamespace(id=1),
            db=db,
        )

        async def _read():
            async for _ in response.body_iterator:
                pass

        task = _asyncio.create_task(_read())
        await _asyncio.sleep(0.2)  # the widget and both chunks are consumed
        task.cancel()  # the client is gone
        with pytest.raises(_asyncio.CancelledError):
            await task

    rows = [(c.kwargs["role"], c.kwargs.get("content")) for c in mock_add_message.await_args_list]
    assert rows == [("user", "Show dashboard"), ("widget", None), ("assistant", "Partial reply")]
