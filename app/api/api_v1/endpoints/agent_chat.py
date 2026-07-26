"""
AI Agent chat endpoints.

POST /agent/chat              — Stream a chat response via SSE
GET  /agent/conversations     — List the user's conversations
GET  /agent/conversations/{id}/messages — Get messages for a conversation
DELETE /agent/conversations/{id}       — Delete a conversation
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import Response, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.api_v1.dependencies.auth import get_current_active_user
from app.core.database import get_db
from app.core.logging import get_logger
from app.middleware.rate_limit import EndpointRateLimiter
from app.schemas.ai_agent import (
    AgentChatRequest,
    ConversationMessageOut,
    ConversationSummary,
    GuestChatRequest,
)
from app.schemas.pagination import CursorPage, CursorParams, build_cursor_page
from app.services.ai_agent import conversation_store, get_agent_service
from app.services.ai_agent.agent_service import sse_event

_public_chat_limiter = EndpointRateLimiter(calls=10, period=60)

logger = get_logger(__name__)

router = APIRouter()


async def _check_public_chat_rate_limit(request: Request) -> None:
    """FastAPI dependency: rate-limits the public chat endpoint (10 req/60s per IP)."""
    client_id = _public_chat_limiter.get_client_id(request)
    allowed = await _public_chat_limiter.check_rate_limit(
        client_id, "POST:/agent/chat-public"
    )
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded. Please try again later.",
            headers={"Retry-After": "60"},
        )


@router.post("/chat-public", summary="Send public agent chat message")
async def agent_chat_public(
    body: GuestChatRequest,
    db: AsyncSession = Depends(get_db),
    _rate_limit: None = Depends(_check_public_chat_rate_limit),
) -> StreamingResponse:
    """Stream an AI agent response for unauthenticated guests via SSE.

    Only property search tools are available. No conversation persistence.

    The main-pool DB session is released before streaming begins and a
    background-pool session is used for tool calls, matching the pattern
    in the authenticated ``/chat`` endpoint.
    """
    service = get_agent_service()

    # Release the main-pool session — streaming may take minutes and must
    # not pin a Supavisor backend while waiting on the LLM.
    await db.close()

    async def event_stream():
        from app.core.database import AsyncSessionLocalBG

        try:
            # Tools open short-lived sessions via session_factory; do not hold
            # one connection for the entire multi-minute SSE stream.
            async for event in service.stream_response(
                user_message=body.message,
                conversation_id=None,
                conversation_history=[],
                user=None,
                db=None,
                user_role="guest",
                session_factory=AsyncSessionLocalBG,
            ):
                yield event
        except Exception as exc:
            logger.error("Public SSE stream error: %s", exc, exc_info=True)
            yield sse_event(
                "error", {"code": "STREAM_ERROR", "message": str(exc)[:200]}
            )

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@router.post("/chat", summary="Send agent chat message")
async def agent_chat(
    body: AgentChatRequest,
    current_user=Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """Stream an AI agent response via Server-Sent Events.

    The main-pool DB session is released after the initial conversation
    setup. The streaming phase uses a background-pool session so the
    main pool is not held for the entire AI response duration.
    """
    service = get_agent_service()

    # Get or create conversation
    conversation = await conversation_store.get_or_create_conversation(
        db, user_id=current_user.id, conversation_id=body.conversation_id,
    )

    # Persist the user message
    await conversation_store.add_message(
        db, conversation_id=conversation.id, role="user", content=body.message,
    )
    await db.commit()

    # Load conversation history for context
    history_rows = await conversation_store.get_history(db, conversation.id, limit=50)
    history = [
        {
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

    async def event_stream():
        full_response = ""
        widget_events: list[dict] = []
        from app.core.database import AsyncSessionLocal, AsyncSessionLocalBG

        try:
            # Short sessions per tool call only — never hold a connection
            # across LLM token generation.
            #
            # Iterate the typed event stream rather than the serialized frames:
            # this used to substring-sniff '"response_text"' out of the SSE
            # string and re-parse it, which a text_chunk containing that literal
            # would clobber.
            async for event_name, event_data in service.stream_events(
                user_message=body.message,
                conversation_id=conversation_id,
                conversation_history=history[:-1],  # exclude the message we just stored
                user=current_user,
                db=None,
                session_factory=AsyncSessionLocalBG,
            ):
                if event_name == "done":
                    full_response = event_data.get("response_text", "")
                elif event_name == "widget":
                    widget_events.append(event_data)
                yield sse_event(event_name, event_data)
        except Exception as exc:
            logger.error("SSE stream error: %s", exc, exc_info=True)
            yield sse_event("error", {"code": "STREAM_ERROR", "message": str(exc)[:200]})

        # After streaming completes, open a fresh session to persist results.
        # Use AsyncSessionLocal directly instead of the get_db() generator,
        # which is a FastAPI dependency not designed for manual consumption
        # outside of request scope (causes _ConnectionRecord.pool errors).
        async with AsyncSessionLocal() as fresh_db:
            try:
                # Persist widget events
                for we in widget_events:
                    await conversation_store.add_message(
                        fresh_db, conversation_id=conversation_id,
                        role="widget",
                        tool_name=we.get("widget_name"),
                        tool_result=we.get("structured_content"),
                    )
                # Persist assistant response (even if empty when widgets were emitted)
                if full_response or widget_events:
                    await conversation_store.add_message(
                        fresh_db, conversation_id=conversation_id,
                        role="assistant", content=full_response or "",
                    )
                    await fresh_db.commit()
            except Exception as exc:
                logger.error("Failed to persist messages: %s", exc)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@router.get("/conversations", response_model=CursorPage[ConversationSummary], summary="List agent conversations")
async def list_conversations(
    page: CursorParams = Depends(),
    current_user=Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """List the authenticated user's AI conversations."""
    items, next_payload, total = await conversation_store.list_conversations(
        db,
        user_id=current_user.id,
        cursor_payload=page.decoded(),
        limit=page.limit,
        with_total=page.include_total,
    )
    return build_cursor_page(items, limit=page.limit, next_payload=next_payload, total=total)


@router.get("/conversations/{conversation_id}/messages",
            response_model=list[ConversationMessageOut],
            summary="List conversation messages",
)
async def get_conversation_messages(
    conversation_id: int,
    current_user=Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
    limit: int = 100,
):
    """Get messages for a specific conversation."""
    # Verify ownership
    from sqlalchemy import select

    from app.models.ai_conversations import AIConversation

    conv = (await db.execute(
        select(AIConversation).where(
            AIConversation.id == conversation_id,
            AIConversation.user_id == current_user.id,
        )
    )).scalar_one_or_none()
    if not conv:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="Conversation not found")

    messages = await conversation_store.get_history(db, conversation_id, limit=limit)
    return [ConversationMessageOut.model_validate(m) for m in messages]


@router.delete("/conversations/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete conversation")
async def delete_conversation(
    conversation_id: int,
    current_user=Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete a conversation and all its messages."""
    deleted = await conversation_store.delete_conversation(
        db, conversation_id=conversation_id, user_id=current_user.id,
    )
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="Conversation not found")
    await db.commit()


@router.get("/widgets/{widget_name}", summary="Get widget HTML")
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
