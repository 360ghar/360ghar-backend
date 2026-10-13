"""
Core Pydantic AI Agent service.

Creates a Pydantic AI Agent with all MCP tools registered, manages
conversation history, and streams SSE events back to the client.
"""
from __future__ import annotations

import functools
import inspect
import json
import uuid
from collections.abc import AsyncIterator
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from functools import lru_cache
from typing import Any
from uuid import UUID

from openai import AsyncOpenAI
from pydantic_ai import (
    Agent,
    FunctionToolCallEvent,
    FunctionToolResultEvent,
    PartDeltaEvent,
    PartStartEvent,
    TextPartDelta,
)
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    RetryPromptPart,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.models import Model
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.logging import get_logger
from app.mcp.chatgpt import get_widget_name_for_tool
from app.services.ai_agent.deps import AgentDeps, run_with_short_db_session
from app.services.ai_agent.system_prompt import get_system_prompt
from app.services.ai_agent.tools import get_tools_for_role

logger = get_logger(__name__)


def _jsonable(value: Any) -> Any:
    """Coerce ORM/Pydantic types to JSON-safe primitives.

    Tool returns often carry ``datetime``/``Decimal``/``UUID`` values from ORM
    models. This guarantees every model adapter can encode them.
    """
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(v) for v in value]
    if hasattr(value, "model_dump"):
        return _jsonable(value.model_dump(mode="json"))
    return str(value)


def _jsonable_tool(func: Any) -> Any:
    """Wrap a tool so its return value is JSON-safe, preserving its signature
    so Pydantic AI's schema introspection is unaffected.

    When ``AgentDeps.session_factory`` is set, each tool call opens a short
    session so the SSE stream does not hold a Supavisor slot for the whole
    LLM turn — only while the tool runs SQL.
    """

    if inspect.iscoroutinefunction(func):
        @functools.wraps(func)
        async def _async_wrapped(*args: Any, **kwargs: Any) -> Any:
            ctx = args[0] if args else None
            deps = getattr(ctx, "deps", None) if ctx is not None else None
            if isinstance(deps, AgentDeps):
                async def _run() -> Any:
                    return _jsonable(await func(*args, **kwargs))

                return await run_with_short_db_session(deps, _run)
            return _jsonable(await func(*args, **kwargs))

        return _async_wrapped

    @functools.wraps(func)
    def _sync_wrapped(*args: Any, **kwargs: Any) -> Any:
        return _jsonable(func(*args, **kwargs))

    return _sync_wrapped


class _AgentRunError(Exception):
    """Internal error raised when an agent run fails."""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


def sse_event(event: str, data: dict[str, Any]) -> str:
    """Format a single SSE event."""
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def _build_message_history(
    messages: list[dict[str, Any]],
) -> list[ModelMessage]:
    """Convert stored conversation messages into Pydantic AI message format.

    Includes tool_call and tool_result pairs so the LLM retains full context
    from earlier turns.
    """
    history: list[ModelMessage] = []
    pending_tool_calls: list[ToolCallPart] = []

    for msg in messages:
        role = msg.get("role", "")
        content = msg.get("content", "") or ""

        if role == "user":
            history.append(ModelRequest(parts=[UserPromptPart(content=content)]))

        elif role == "assistant":
            history.append(ModelResponse(parts=[TextPart(content=content)]))

        elif role == "tool_call":
            # Accumulate tool call parts for the model response
            tool_name = msg.get("tool_name", "unknown")
            tool_args = msg.get("tool_args", {})
            call_id = msg.get("tool_call_id", f"tc_{uuid.uuid4().hex[:8]}")
            pending_tool_calls.append(
                ToolCallPart(
                    tool_name=tool_name,
                    args=tool_args if isinstance(tool_args, dict) else {},
                    tool_call_id=call_id,
                )
            )

        elif role == "tool_result":
            # Emit the model response with tool calls, then the request with returns
            tool_name = msg.get("tool_name", "unknown")
            tool_result = msg.get("tool_result", {})
            call_id = msg.get("tool_call_id", "unknown")
            result_content = (
                json.dumps(tool_result)
                if isinstance(tool_result, dict)
                else str(tool_result)
            )

            if pending_tool_calls:
                history.append(ModelResponse(parts=list(pending_tool_calls)))
                pending_tool_calls.clear()

            history.append(
                ModelRequest(
                    parts=[
                        ToolReturnPart(
                            tool_name=tool_name,
                            content=result_content,
                            tool_call_id=call_id,
                        )
                    ]
                )
            )

    # Flush any remaining tool calls
    if pending_tool_calls:
        history.append(ModelResponse(parts=list(pending_tool_calls)))

    return history


@lru_cache(maxsize=1)
def _agnes_client() -> AsyncOpenAI:
    """One Agnes client per process, so its connection pool is reused.

    The OpenAI SDK retries 429, 5xx and network errors with exponential
    backoff and honours Retry-After.
    """
    if not settings.AGNES_AI_API_KEY:
        raise _AgentRunError("AGNES_AI_API_KEY not configured for the AI agent")
    return AsyncOpenAI(base_url=settings.AGNES_API_BASE, api_key=settings.AGNES_AI_API_KEY, max_retries=5)


async def close_agnes_client() -> None:
    """Close the shared Agnes client on app shutdown (no-op if never created)."""
    if _agnes_client.cache_info().currsize:
        await _agnes_client().close()
        _agnes_client.cache_clear()


class PydanticAIAgentService:
    """Manages a Pydantic AI Agent backed by Agnes AI (OpenAI-compatible API)."""

    def __init__(self, model: str | None = None):
        self.model_name = model or settings.AGNES_TEXT_MODEL

    def _create_model(self) -> Model:
        """Create the Agnes chat model on the shared client."""
        return OpenAIChatModel(self.model_name, provider=OpenAIProvider(openai_client=_agnes_client()))

    def _build_agent(self, user_role: str, model: Model) -> Agent[AgentDeps, str]:
        """Build an Agent with the given model and role-specific tools."""
        tools = get_tools_for_role(user_role)
        agent: Agent[AgentDeps, str] = Agent(
            model,
            system_prompt=get_system_prompt(user_role),
            retries=2,
        )
        for name, func, description in tools:
            agent.tool(_jsonable_tool(func), name=name, description=description)  # type: ignore[call-overload]
        return agent

    async def _run_agent_stream(
        self,
        agent: Agent[AgentDeps, str],
        user_message: str,
        deps: AgentDeps,
        message_history: list[ModelMessage],
        conversation_id: int | None,
    ) -> AsyncIterator[tuple[str, dict[str, Any]]]:
        """Core agent streaming logic. Yields (event_name, data) tuples."""
        if conversation_id is not None:
            yield ("conversation_info", {"conversation_id": conversation_id})

        full_text = ""
        tool_calls_count = 0

        try:
            async with agent.iter(
                user_message,
                deps=deps,
                message_history=message_history,
            ) as run:
                async for node in run:
                    if Agent.is_model_request_node(node):
                        async with node.stream(run.ctx) as request_stream:
                            async for event in request_stream:
                                if isinstance(event, PartStartEvent):
                                    if isinstance(event.part, TextPart) and event.part.content:
                                        text = event.part.content
                                        full_text += text
                                        yield ("text_chunk", {"text": text})
                                elif isinstance(event, PartDeltaEvent):
                                    if isinstance(event.delta, TextPartDelta):
                                        text = event.delta.content_delta
                                        full_text += text
                                        yield ("text_chunk", {"text": text})

                    elif Agent.is_call_tools_node(node):
                        async with node.stream(run.ctx) as handle_stream:
                            async for event in handle_stream:  # type: ignore[assignment]
                                if isinstance(event, FunctionToolCallEvent):
                                    call_id = (
                                        event.part.tool_call_id
                                        or f"tc_{uuid.uuid4().hex[:8]}"
                                    )
                                    tool_calls_count += 1
                                    yield ("tool_call_start", {
                                        "call_id": call_id,
                                        "tool": event.part.tool_name,
                                    })
                                elif isinstance(event, FunctionToolResultEvent):
                                    call_id = event.tool_call_id or "unknown"
                                    result_part = event.result
                                    is_retry = isinstance(result_part, RetryPromptPart)
                                    tool_name = getattr(result_part, "tool_name", None) or "unknown"
                                    yield ("tool_call_end", {
                                        "call_id": call_id,
                                        "tool": tool_name,
                                        "success": not is_retry,
                                        "summary": _summarize_result(
                                            getattr(result_part, "content", "")
                                        ),
                                    })
                                    if not is_retry:
                                        widget_name = get_widget_name_for_tool(tool_name)
                                        if widget_name:
                                            result_data = result_part.content
                                            if isinstance(result_data, str):
                                                try:
                                                    result_data = json.loads(result_data)
                                                except (json.JSONDecodeError, TypeError):
                                                    result_data = {"raw": result_data}
                                            yield ("widget", {
                                                "widget_name": widget_name,
                                                "structured_content": result_data,
                                            })

            try:
                final_output = run.result.output  # type: ignore[union-attr]
                if isinstance(final_output, str) and final_output:
                    if not full_text:
                        yield ("text_chunk", {"text": final_output})
                    if len(final_output) >= len(full_text):
                        full_text = final_output
            except Exception:
                # Not fatal — the streamed text_chunks are still the answer. But an
                # empty done.response_text used to be indistinguishable from "the
                # model said nothing", so log it instead of swallowing it.
                logger.warning("Could not read final agent output", exc_info=True)

        except Exception as e:
            raise _AgentRunError(str(e)) from e

        done_data: dict[str, Any] = {
            "tool_calls_count": tool_calls_count,
            "response_text": full_text,
        }
        if conversation_id is not None:
            done_data["conversation_id"] = conversation_id
        yield ("done", done_data)

    async def stream_response(
        self,
        user_message: str,
        conversation_id: int | None,
        conversation_history: list[dict[str, Any]],
        user: Any,
        db: AsyncSession | None = None,
        user_role: str | None = None,
        session_factory: Any | None = None,
    ) -> AsyncIterator[str]:
        """Serialize :meth:`stream_events` into SSE frames.

        Callers that need the event payloads (e.g. to persist them) should
        iterate :meth:`stream_events` and serialize with :func:`sse_event`
        instead of re-parsing these strings.
        """
        async for event_name, event_data in self.stream_events(
            user_message,
            conversation_id,
            conversation_history,
            user,
            db=db,
            user_role=user_role,
            session_factory=session_factory,
        ):
            yield sse_event(event_name, event_data)

    async def stream_events(
        self,
        user_message: str,
        conversation_id: int | None,
        conversation_history: list[dict[str, Any]],
        user: Any,
        db: AsyncSession | None = None,
        user_role: str | None = None,
        session_factory: Any | None = None,
    ) -> AsyncIterator[tuple[str, dict[str, Any]]]:
        """
        Run the agent and yield ``(event_name, data)`` pairs.

        Uses agent.iter() for node-by-node streaming so tool call events
        are interleaved with text chunks in real time.

        Pass user_role="guest" with user=None for unauthenticated requests.
        conversation_id=None is allowed for stateless (guest) sessions.

        Prefer ``session_factory`` over a long-lived ``db`` so tools open
        short sessions and do not pin Supavisor backends during LLM waits.

        Events emitted:
            conversation_info  — once, at the start (only when conversation_id is not None)
            text_chunk         — partial text from the model
            tool_call_start    — agent is invoking a tool
            tool_call_end      — tool returned a result
            widget             — a tool result that has a linked UI widget
            done               — stream finished
            error              — agent run failed
        """
        role = str(user_role or getattr(user, "role", "user"))
        if session_factory is None and db is None:
            from app.core.database import AsyncSessionLocalBG

            session_factory = AsyncSessionLocalBG
        deps = AgentDeps(
            user=user,
            db=db,
            user_role=role,
            session_factory=session_factory,
        )
        message_history = _build_message_history(conversation_history)

        try:
            agent = self._build_agent(role, self._create_model())
            async for event_name, event_data in self._run_agent_stream(
                agent, user_message, deps, message_history, conversation_id,
            ):
                yield (event_name, event_data)
        except _AgentRunError as exc:
            logger.error("Agent run error: %s", exc.message)
            yield ("error", {
                "code": "AGENT_ERROR",
                "message": f"Agent run failed: {exc.message}"[:200],
                "recoverable": False,
            })


def _summarize_result(content: Any, max_len: int = 100) -> str:
    """Create a short human-readable summary of a tool result."""
    if isinstance(content, str):
        text = content
    elif isinstance(content, dict):
        if "message" in content:
            text = str(content["message"])
        elif "items" in content:
            text = f"Found {len(content['items'])} items"
        elif "error" in content:
            text = f"Error: {content.get('message', content['error'])}"
        else:
            text = json.dumps(content)[:max_len]
    else:
        text = str(content)[:max_len]
    return text[:max_len]
