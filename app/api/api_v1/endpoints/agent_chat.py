"""
AI Agent chat endpoints.

POST   /agent/chat                              — Stream a chat response via SSE (typed frames)
POST   /agent/chat-public                       — Guest stream, property discovery tools only
GET    /agent/conversations                     — List the user's conversations (CursorPage)
GET    /agent/conversations/{id}/messages/page  — Messages as a CursorPage, newest page first
DELETE /agent/conversations/{id}                — Delete a conversation
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse, Response, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.api_v1.dependencies.auth import get_current_active_user
from app.core.database import get_db
from app.core.exceptions import NotFoundException
from app.core.logging import get_logger
from app.middleware.rate_limit import EndpointRateLimiter
from app.schemas.ai_agent import (
    AGENT_ERROR_MESSAGE,
    AgentChatRequest,
    AgentErrorCode,
    AgentStreamEvent,
    AIConversationSummary,
    ConversationMessageOut,
    DoneFrame,
    ErrorData,
    ErrorFrame,
    GuestChatRequest,
    TextChunkFrame,
    WidgetData,
    WidgetFrame,
    widget_result_dict,
)
from app.schemas.pagination import CursorPage, CursorParams, build_cursor_page, decode_cursor
from app.services.ai_agent import conversation_store, get_agent_service
from app.services.ai_agent.agent_service import sse_frame

_public_chat_limiter = EndpointRateLimiter(calls=10, period=60)

logger = get_logger(__name__)

router = APIRouter()

# Rows of earlier turns sent to the model with each new message.
HISTORY_LIMIT = 50

_SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "X-Accel-Buffering": "no",
    "Connection": "keep-alive",
}


class _EventStreamResponse(StreamingResponse):
    """A stream response documented as text/event-stream, not as JSON."""

    media_type = "text/event-stream"


# OpenAPI description of the stream. The frame schemas are the union in app/schemas/ai_agent.py.
AGENT_STREAM_RESPONSES: dict[int | str, dict[str, Any]] = {
    200: {
        "model": AgentStreamEvent,
        "description": (
            "Server-Sent Events. Each event is a typed frame: conversation_info, text_chunk, "
            "tool_call_start, tool_call_end, widget, done or error. Read to the end of the "
            "stream; the reply is saved before done is sent."
        ),
    },
}


async def _check_public_chat_rate_limit(request: Request) -> None:
    """FastAPI dependency: rate-limits the public chat endpoint (10 req/60s per IP)."""
    client_id = _public_chat_limiter.get_client_id(request)
    allowed = await _public_chat_limiter.check_rate_limit(client_id, "POST:/agent/chat-public")
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "code": "RATE_LIMIT_EXCEEDED",
                "message": "Rate limit exceeded. Please try again later.",
            },
            headers={"Retry-After": "60"},
        )


def _error_frame(code: AgentErrorCode = "STREAM_ERROR") -> str:
    """A fixed error frame. The exception text stays in the server log."""
    return sse_frame(ErrorFrame(data=ErrorData(code=code, message=AGENT_ERROR_MESSAGE)))


@router.post(
    "/chat-public",
    summary="Send public agent chat message",
    responses=AGENT_STREAM_RESPONSES,
    response_class=_EventStreamResponse,
)
async def agent_chat_public(
    body: GuestChatRequest,
    db: AsyncSession = Depends(get_db),
    _rate_limit: None = Depends(_check_public_chat_rate_limit),
) -> StreamingResponse:
    """Stream an AI agent response for unauthenticated guests via SSE.

    Only property discovery tools are available. No conversation persistence.

    The main-pool DB session is released before streaming begins and a
    background-pool session is used for tool calls, matching the pattern
    in the authenticated ``/chat`` endpoint.
    """
    service = get_agent_service()

    # Release the main-pool session — streaming may take minutes and must
    # not pin a Supavisor backend while waiting on the LLM.
    await db.close()

    async def event_stream() -> AsyncIterator[str]:
        from app.core.database import AsyncSessionLocalBG

        try:
            # Tools open short-lived sessions via session_factory; do not hold
            # one connection for the entire multi-minute SSE stream.
            async for frame in service.stream_events(
                user_message=body.message,
                conversation_id=None,
                conversation_history=[],
                user=None,
                db=None,
                user_role="guest",
                session_factory=AsyncSessionLocalBG,
            ):
                yield sse_frame(frame)
        except Exception as exc:
            logger.error("Public SSE stream error: %s", exc, exc_info=True)
            yield _error_frame()

    return StreamingResponse(event_stream(), media_type="text/event-stream", headers=_SSE_HEADERS)


async def _persist_turn(
    conversation_id: int,
    *,
    widgets: list[WidgetData],
    text: str,
) -> None:
    """Save the widget rows and the assistant row of one reply in one transaction.

    Called before the terminal frame is sent, so a client that stops reading at
    ``done`` still finds the reply in history.
    """
    if not text and not widgets:
        return
    from app.core.database import AsyncSessionLocal

    # A fresh session: the request session was released before streaming began.
    async with AsyncSessionLocal() as fresh_db:
        try:
            for widget in widgets:
                await conversation_store.add_message(
                    fresh_db,
                    conversation_id=conversation_id,
                    role="widget",
                    tool_name=widget.widget_name,
                    tool_result=widget_result_dict(widget),
                )
            await conversation_store.add_message(
                fresh_db,
                conversation_id=conversation_id,
                role="assistant",
                content=text,
            )
            await fresh_db.commit()
        except Exception as exc:
            await fresh_db.rollback()
            logger.error("Failed to persist agent reply: %s", exc, exc_info=True)


@router.post(
    "/chat",
    summary="Send agent chat message",
    responses=AGENT_STREAM_RESPONSES,
    response_class=_EventStreamResponse,
)
async def agent_chat(
    body: AgentChatRequest,
    current_user=Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """Stream an AI agent response via Server-Sent Events.

    An unknown or foreign ``conversation_id`` returns 404 ``NOT_FOUND``.
    The main-pool DB session is released after the initial conversation
    setup. The streaming phase uses a background-pool session so the
    main pool is not held for the entire AI response duration.
    """
    service = get_agent_service()

    if body.conversation_id is not None:
        conversation = await conversation_store.get_owned_conversation(
            db,
            user_id=current_user.id,
            conversation_id=body.conversation_id,
        )
        if conversation is None:
            raise NotFoundException("Conversation not found", error_code="NOT_FOUND")
    else:
        conversation = await conversation_store.create_conversation(db, user_id=current_user.id)

    # Persist the user message
    await conversation_store.add_message(
        db,
        conversation_id=conversation.id,
        role="user",
        content=body.message,
    )
    await db.commit()

    # Load conversation history for context. The last row is the message just stored.
    history_rows = await conversation_store.get_history(db, conversation.id, limit=HISTORY_LIMIT)
    history = [
        {
            "id": m.id,
            "role": m.role,
            "content": m.content,
            "tool_name": m.tool_name,
            "tool_args": m.tool_args,
            "tool_result": m.tool_result,
        }
        for m in history_rows
    ]

    # Snapshot IDs needed after the session is released
    conversation_id = conversation.id

    # Release the main-pool session — streaming may take minutes.
    await db.close()

    async def event_stream() -> AsyncIterator[str]:
        from app.core.database import AsyncSessionLocalBG

        widgets: list[WidgetData] = []
        chunks: list[str] = []
        persisted = False

        async def persist_once(text: str) -> None:
            nonlocal persisted
            if not persisted:
                persisted = True
                await _persist_turn(conversation_id, widgets=widgets, text=text)

        try:
            # Short sessions per tool call only — never hold a connection
            # across LLM token generation.
            async for frame in service.stream_events(
                user_message=body.message,
                conversation_id=conversation_id,
                conversation_history=history[:-1],  # exclude the message we just stored
                user=current_user,
                db=None,
                session_factory=AsyncSessionLocalBG,
            ):
                if isinstance(frame, WidgetFrame):
                    widgets.append(frame.data)
                elif isinstance(frame, TextChunkFrame):
                    chunks.append(frame.data.text)
                elif isinstance(frame, DoneFrame):
                    await persist_once(frame.data.response_text)
                elif isinstance(frame, ErrorFrame):
                    await persist_once("")
                yield sse_frame(frame)
            await persist_once("")
        except (asyncio.CancelledError, GeneratorExit):
            # Client left before done. Save the partial reply in a shielded task so the
            # cancellation cannot abort the write. The messages table has no interrupted
            # flag, so the partial text is stored as is.
            # ponytail: no "interrupted" marker; add a nullable column if the UI needs one.
            try:
                await asyncio.shield(persist_once("".join(chunks)))
            except asyncio.CancelledError:
                pass
            raise
        except Exception as exc:
            logger.error("SSE stream error: %s", exc, exc_info=True)
            await persist_once("")
            yield _error_frame()

    return StreamingResponse(event_stream(), media_type="text/event-stream", headers=_SSE_HEADERS)


@router.get(
    "/conversations",
    response_model=CursorPage[AIConversationSummary],
    summary="List agent conversations",
)
async def list_conversations(
    page: CursorParams = Depends(),
    current_user=Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """List the authenticated user's AI conversations."""
    filters: dict[str, Any] = {}
    items, next_payload, total = await conversation_store.list_conversations(
        db,
        user_id=current_user.id,
        cursor_payload=page.decoded(filters),
        limit=page.limit,
        with_total=page.include_total,
    )
    return build_cursor_page(
        items,
        limit=page.limit,
        next_payload=next_payload,
        total=total,
        filters=filters,
    )


async def _messages_page(
    conversation_id: int,
    *,
    cursor: str | None,
    limit: int,
    current_user: Any,
    db: AsyncSession,
) -> dict[str, Any]:
    """Newest ``limit`` messages first; ``next_cursor`` walks back in time.

    Each page's ``items`` are in chronological order (oldest first), so the client can
    prepend older pages. The cursor is bound to the conversation: a cursor from another
    conversation fails with 422 INVALID_CURSOR.
    """
    conversation = await conversation_store.get_owned_conversation(
        db,
        user_id=current_user.id,
        conversation_id=conversation_id,
    )
    if conversation is None:
        raise NotFoundException("Conversation not found", error_code="NOT_FOUND")

    filters = {"conversation_id": conversation_id}
    cursor_payload = decode_cursor(cursor, filters) if cursor else {}
    messages, next_payload = await conversation_store.get_history_page(
        db,
        conversation_id,
        cursor_payload=cursor_payload,
        limit=limit,
    )
    return build_cursor_page(
        [ConversationMessageOut.model_validate(m) for m in messages],
        limit=limit,
        next_payload=next_payload,
        filters=filters,
    )


@router.get(
    "/conversations/{conversation_id}/messages/page",
    response_model=CursorPage[ConversationMessageOut],
    summary="List conversation messages (cursor-paginated)",
)
async def get_conversation_messages_page(
    conversation_id: int,
    cursor: str | None = Query(
        None, description="Opaque cursor from a prior page's next_cursor; fetches older messages."
    ),
    limit: int = Query(30, ge=1, le=100, description="Max messages to return (1-100)."),
    current_user=Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Newest ``limit`` messages first; ``next_cursor`` walks back in time."""
    return await _messages_page(
        conversation_id, cursor=cursor, limit=limit, current_user=current_user, db=db
    )


@router.delete(
    "/conversations/{conversation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete conversation",
)
async def delete_conversation(
    conversation_id: int,
    current_user=Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete a conversation and all its messages."""
    deleted = await conversation_store.delete_conversation(
        db,
        conversation_id=conversation_id,
        user_id=current_user.id,
    )
    if not deleted:
        raise NotFoundException("Conversation not found", error_code="NOT_FOUND")
    await db.commit()


@router.get(
    "/widgets/{widget_name}",
    summary="Get widget HTML",
    response_class=HTMLResponse,
    responses={200: {"content": {"text/html": {"schema": {"type": "string"}}}}},
)
async def get_widget_html(widget_name: str) -> Response:
    """Serve a pre-built HTML widget bundle by name.

    No auth required — widget HTML is static and data is injected
    client-side via postMessage after loading.
    """
    from app.mcp.chatgpt import WIDGETS, load_widget_html

    # Allowlist rather than trusting the path param: the filename is joined onto
    # WIDGET_DIR, and the clients already validate the name twice.
    if widget_name not in WIDGETS:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Widget not found",
        )

    html = load_widget_html(widget_name)
    if not html:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Widget not found",
        )
    return Response(
        content=html,
        media_type="text/html",
        headers={"Cache-Control": "public, max-age=3600"},
    )
