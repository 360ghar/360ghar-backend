"""
Core Pydantic AI Agent service.

Creates a Pydantic AI Agent with all MCP tools registered, manages
conversation history, and streams typed SSE frames back to the client.
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
from pydantic import ValidationError
from pydantic_ai import (
    Agent,
    FunctionToolCallEvent,
    FunctionToolResultEvent,
    ModelRetry,
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
from sqlalchemy.exc import DataError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.exceptions import (
    BadRequestException,
    ForbiddenException,
    NotFoundException,
    ValidationException,
)
from app.core.logging import get_logger
from app.mcp.chatgpt import get_widget_name_for_tool
from app.mcp.chatgpt.widget_payloads import widget_payload
from app.mcp.utils import utc_iso
from app.schemas.ai_agent import (
    AGENT_ERROR_MESSAGE,
    AgentStreamFrame,
    ConversationInfoData,
    ConversationInfoFrame,
    DoneData,
    DoneFrame,
    ErrorData,
    ErrorFrame,
    TextChunkData,
    TextChunkFrame,
    ToolCallEndData,
    ToolCallEndFrame,
    ToolCallStartData,
    ToolCallStartFrame,
    WidgetData,
    WidgetFrame,
    make_widget_data,
)
from app.services.ai_agent.deps import AgentDeps, run_with_short_db_session
from app.services.ai_agent.system_prompt import get_system_prompt
from app.services.ai_agent.tools import get_tools_for_role

logger = get_logger(__name__)

# Tool errors the model can fix by changing its arguments or ids. They become a retry.
# Any other exception is logged with its traceback and ends the run with the fixed error frame.
_RETRYABLE_TOOL_ERRORS = (
    ValueError,
    DataError,
    NotFoundException,
    ForbiddenException,
    BadRequestException,
    ValidationException,
)


def _jsonable(value: Any) -> Any:
    """Coerce ORM/Pydantic types to JSON-safe primitives.

    Tool returns often carry ``datetime``/``Decimal``/``UUID`` values from ORM
    models. This guarantees every model adapter can encode them.
    """
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, datetime):
        return utc_iso(value)
    if isinstance(value, date):
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


def _retry_message(tool_name: str, exc: Exception) -> str:
    """Text the model reads when a tool rejects its arguments. Never the database text."""
    if isinstance(exc, DataError):
        return "The database rejected a value. Check the arguments and try again."
    if isinstance(exc, NotFoundException):
        return f"{tool_name}: the record was not found. Check the ids and try again."
    if isinstance(exc, ForbiddenException):
        return f"{tool_name}: the record is outside your access. Use an id you can access."
    detail = getattr(exc, "detail", None)
    text = detail if isinstance(detail, str) else str(exc)
    return f"Invalid arguments for {tool_name}: {text[:300]}. Check the values and try again."


def _jsonable_tool(func: Any) -> Any:
    """Wrap a tool so its return value is JSON-safe, preserving its signature
    so Pydantic AI's schema introspection is unaffected.

    A ``ValueError`` or ``DataError`` raised by the tool body becomes a
    ``ModelRetry``. The model then corrects its arguments instead of the whole
    run failing.

    When ``AgentDeps.session_factory`` is set, each tool call opens a short
    session so the SSE stream does not hold a Supavisor slot for the whole
    LLM turn — only while the tool runs SQL.
    """
    tool_name = getattr(func, "__name__", "tool")

    if inspect.iscoroutinefunction(func):

        @functools.wraps(func)
        async def _async_wrapped(*args: Any, **kwargs: Any) -> Any:
            ctx = args[0] if args else None
            deps = getattr(ctx, "deps", None) if ctx is not None else None

            async def _call() -> Any:
                try:
                    return _jsonable(await func(*args, **kwargs))
                except _RETRYABLE_TOOL_ERRORS as exc:
                    logger.warning("Tool %s rejected its arguments: %s", tool_name, exc)
                    raise ModelRetry(_retry_message(tool_name, exc)) from exc
                except Exception:
                    logger.exception("Tool %s failed", tool_name)
                    raise

            if isinstance(deps, AgentDeps):
                return await run_with_short_db_session(deps, _call)
            return await _call()

        return _async_wrapped

    @functools.wraps(func)
    def _sync_wrapped(*args: Any, **kwargs: Any) -> Any:
        try:
            return _jsonable(func(*args, **kwargs))
        except _RETRYABLE_TOOL_ERRORS as exc:
            logger.warning("Tool %s rejected its arguments: %s", tool_name, exc)
            raise ModelRetry(_retry_message(tool_name, exc)) from exc
        except Exception:
            logger.exception("Tool %s failed", tool_name)
            raise

    return _sync_wrapped


class _AgentRunError(Exception):
    """Internal error raised when an agent run fails. The message is logged, never sent."""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


def sse_event(event: str, data: dict[str, Any]) -> str:
    """Format a single SSE event from a raw payload dict."""
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def sse_frame(frame: AgentStreamFrame) -> str:
    """Serialize one typed agent frame to an SSE event."""
    return f"event: {frame.event}\ndata: {frame.data.model_dump_json(exclude_unset=True)}\n\n"


def _widget_frame_data(widget_name: str, result: Any) -> WidgetData | None:
    """Typed frame data for a widget result. A result the payload model rejects sends no widget."""
    try:
        return make_widget_data(widget_name, widget_payload(widget_name, result))
    except ValidationError:
        logger.error(
            "Widget %s result does not match its payload model", widget_name, exc_info=True
        )
        return None


def _role_name(user: Any, user_role: Any = None) -> str:
    """Return the role as its plain string value ("user", "agent", "admin", "guest").

    ``UserRole`` is a ``str`` Enum. ``str(member)`` gives ``"UserRole.agent"``, which
    matches no tool set, so the enum value is read instead.
    """
    raw = user_role if user_role is not None else getattr(user, "role", None)
    if raw is None:
        return "user"
    return str(getattr(raw, "value", raw))


def _build_message_history(
    messages: list[dict[str, Any]],
) -> list[ModelMessage]:
    """Convert stored conversation messages into Pydantic AI message format.

    A stored widget row is the only stored copy of a tool result, so it becomes a
    tool call and tool return pair. Text tool results are not stored; the assistant
    text is the record of them.
    """
    history: list[ModelMessage] = []

    for msg in messages:
        role = msg.get("role", "")
        content = msg.get("content", "") or ""

        if role == "user":
            history.append(ModelRequest(parts=[UserPromptPart(content=content)]))

        elif role == "assistant":
            history.append(ModelResponse(parts=[TextPart(content=content)]))

        elif role == "widget":
            tool_name = msg.get("tool_name") or "unknown"
            widget_result = msg.get("tool_result")
            call_id = f"widget_{msg.get('id', uuid.uuid4().hex[:8])}"
            history.append(
                ModelResponse(
                    parts=[
                        ToolCallPart(
                            tool_name=tool_name,
                            args={},
                            tool_call_id=call_id,
                        )
                    ]
                )
            )
            history.append(
                ModelRequest(
                    parts=[
                        ToolReturnPart(
                            tool_name=tool_name,
                            content=json.dumps(widget_result)
                            if isinstance(widget_result, dict)
                            else str(widget_result),
                            tool_call_id=call_id,
                        )
                    ]
                )
            )

    return history


@lru_cache(maxsize=1)
def _agnes_client() -> AsyncOpenAI:
    """One Agnes client per process, so its connection pool is reused.

    The OpenAI SDK retries 429, 5xx and network errors with exponential
    backoff and honours Retry-After.
    """
    if not settings.AGNES_AI_API_KEY:
        raise _AgentRunError("AGNES_AI_API_KEY not configured for the AI agent")
    return AsyncOpenAI(
        base_url=settings.AGNES_API_BASE, api_key=settings.AGNES_AI_API_KEY, max_retries=5
    )


async def close_agnes_client() -> None:
    """Close the shared Agnes client on app shutdown (no-op if never created)."""
    if _agnes_client.cache_info().currsize:
        await _agnes_client().close()
        _agnes_client.cache_clear()


def _structured(value: Any) -> dict[str, Any]:
    """Widget payloads are JSON objects. Anything else is wrapped under ``raw``."""
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return {"raw": value}
        return parsed if isinstance(parsed, dict) else {"raw": parsed}
    return {"raw": value}


class PydanticAIAgentService:
    """Manages a Pydantic AI Agent backed by Agnes AI (OpenAI-compatible API)."""

    def __init__(self, model: str | None = None):
        self.model_name = model or settings.AGNES_TEXT_MODEL

    def _create_model(self) -> Model:
        """Create the Agnes chat model on the shared client."""
        return OpenAIChatModel(
            self.model_name, provider=OpenAIProvider(openai_client=_agnes_client())
        )

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
    ) -> AsyncIterator[AgentStreamFrame]:
        """Core agent streaming logic. Yields typed SSE frames."""
        if conversation_id is not None:
            yield ConversationInfoFrame(data=ConversationInfoData(conversation_id=conversation_id))

        full_text = ""

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
                                        yield TextChunkFrame(data=TextChunkData(text=text))
                                elif isinstance(event, PartDeltaEvent):
                                    if isinstance(event.delta, TextPartDelta):
                                        text = event.delta.content_delta
                                        full_text += text
                                        yield TextChunkFrame(data=TextChunkData(text=text))

                    elif Agent.is_call_tools_node(node):
                        async with node.stream(run.ctx) as handle_stream:
                            async for event in handle_stream:  # type: ignore[assignment]
                                if isinstance(event, FunctionToolCallEvent):
                                    call_id = (
                                        event.part.tool_call_id or f"tc_{uuid.uuid4().hex[:8]}"
                                    )
                                    yield ToolCallStartFrame(
                                        data=ToolCallStartData(
                                            call_id=call_id,
                                            tool=event.part.tool_name,
                                        )
                                    )
                                elif isinstance(event, FunctionToolResultEvent):
                                    call_id = event.tool_call_id or "unknown"
                                    result_part = event.result
                                    is_retry = isinstance(result_part, RetryPromptPart)
                                    result_content = getattr(result_part, "content", "")
                                    tool_name = getattr(result_part, "tool_name", None) or "unknown"
                                    if is_retry:
                                        # The summary is cut short, so the full text goes to the log.
                                        logger.warning(
                                            "Tool %s returned a retry prompt: %s",
                                            tool_name,
                                            result_content,
                                        )
                                    failed = is_retry or _is_error_result(result_content)
                                    yield ToolCallEndFrame(
                                        data=ToolCallEndData(
                                            call_id=call_id,
                                            tool=tool_name,
                                            success=not failed,
                                        )
                                    )
                                    if not failed:
                                        widget_name = get_widget_name_for_tool(tool_name)
                                        widget = (
                                            _widget_frame_data(
                                                widget_name, _structured(result_content)
                                            )
                                            if widget_name
                                            else None
                                        )
                                        if widget is not None:
                                            yield WidgetFrame(data=widget)

            try:
                final_output = run.result.output  # type: ignore[union-attr]
                if isinstance(final_output, str) and final_output:
                    if not full_text:
                        yield TextChunkFrame(data=TextChunkData(text=final_output))
                    if len(final_output) >= len(full_text):
                        full_text = final_output
            except Exception:
                # Not fatal — the streamed text_chunks are still the answer. But an
                # empty done.response_text used to be indistinguishable from "the
                # model said nothing", so log it instead of swallowing it.
                logger.warning("Could not read final agent output", exc_info=True)

        except Exception as e:
            raise _AgentRunError(str(e)) from e

        yield DoneFrame(data=DoneData(response_text=full_text))

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

        Callers that need the typed payloads (e.g. to persist them) should
        iterate :meth:`stream_events` and serialize with :func:`sse_frame`
        instead of re-parsing these strings.
        """
        async for frame in self.stream_events(
            user_message,
            conversation_id,
            conversation_history,
            user,
            db=db,
            user_role=user_role,
            session_factory=session_factory,
        ):
            yield sse_frame(frame)

    async def stream_events(
        self,
        user_message: str,
        conversation_id: int | None,
        conversation_history: list[dict[str, Any]],
        user: Any,
        db: AsyncSession | None = None,
        user_role: str | None = None,
        session_factory: Any | None = None,
    ) -> AsyncIterator[AgentStreamFrame]:
        """
        Run the agent and yield typed SSE frames.

        Uses agent.iter() for node-by-node streaming so tool call events
        are interleaved with text chunks in real time.

        Pass user_role="guest" with user=None for unauthenticated requests.
        conversation_id=None is allowed for stateless (guest) sessions.

        Prefer ``session_factory`` over a long-lived ``db`` so tools open
        short sessions and do not pin Supavisor backends during LLM waits.

        Frames emitted (see ``app.schemas.ai_agent``):
            conversation_info  — once, at the start (only when conversation_id is not None)
            text_chunk         — partial text from the model
            tool_call_start    — agent is invoking a tool
            tool_call_end      — tool returned a result (success flag set)
            widget             — a tool result that has a linked UI widget
            done               — stream finished
            error              — agent run failed (fixed text; details are logged)
        """
        role = _role_name(user, user_role)
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
            async for frame in self._run_agent_stream(
                agent,
                user_message,
                deps,
                message_history,
                conversation_id,
            ):
                yield frame
        except _AgentRunError as exc:
            logger.error("Agent run error: %s", exc.message)
            yield ErrorFrame(data=ErrorData(code="AGENT_ERROR", message=AGENT_ERROR_MESSAGE))


def _is_error_result(content: Any) -> bool:
    """A tool that failed returns a dict whose ``error`` key is set."""
    return isinstance(content, dict) and bool(content.get("error"))
