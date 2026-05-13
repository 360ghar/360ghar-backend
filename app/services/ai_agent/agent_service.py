"""
Core Pydantic AI Agent service.

Creates a Pydantic AI Agent with all MCP tools registered, manages
conversation history, and streams SSE events back to the client.
"""
from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from typing import Any

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
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.logging import get_logger
from app.mcp.chatgpt import get_widget_name_for_tool
from app.services.ai_agent.system_prompt import get_system_prompt
from app.services.ai_agent.tools import AgentDeps, get_tools_for_role

logger = get_logger(__name__)


class _AgentRunError(Exception):
    """Internal error raised when an agent run fails, for fallback handling."""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


def _sse_event(event: str, data: dict[str, Any]) -> str:
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


class PydanticAIAgentService:
    """Manages a Pydantic AI Agent instance per model configuration.

    Fallback chain: GLM (primary) -> Gemini -> Groq.
    If the primary provider fails, the next provider in the chain is tried.
    """

    def __init__(self, model: str | None = None):
        self.model_name = model or settings.AI_AGENT_MODEL
        self._primary_provider = OpenAIProvider(
            base_url=settings.AI_AGENT_API_BASE,
            api_key=settings.AI_AGENT_API_KEY or settings.GLM_API_KEY,
        )

    def _create_model(self) -> OpenAIChatModel:
        """Create the primary GLM model with OpenAI-compatible provider."""
        return OpenAIChatModel(
            self.model_name,
            provider=self._primary_provider,
        )

    def _get_fallback_model(self) -> OpenAIChatModel | None:
        """Create the Gemini fallback model if configured."""
        fb_model = settings.AI_AGENT_FALLBACK_MODEL
        if not fb_model:
            return None
        fb_key = settings.AI_AGENT_FALLBACK_API_KEY or settings.GOOGLE_API_KEY
        if not fb_key:
            return None
        provider = OpenAIProvider(
            base_url=settings.AI_AGENT_FALLBACK_API_BASE,
            api_key=fb_key,
        )
        return OpenAIChatModel(fb_model, provider=provider)

    def _get_fallback2_model(self) -> OpenAIChatModel | None:
        """Create the Groq fallback model if configured."""
        fb2_model = settings.AI_AGENT_FALLBACK2_MODEL
        if not fb2_model:
            return None
        fb2_key = settings.AI_AGENT_FALLBACK2_API_KEY or settings.GROQ_API_KEY
        if not fb2_key:
            return None
        provider = OpenAIProvider(
            base_url=settings.AI_AGENT_FALLBACK2_API_BASE,
            api_key=fb2_key,
        )
        return OpenAIChatModel(fb2_model, provider=provider)

    def _build_agent(self, user_role: str, model: OpenAIChatModel) -> Agent[AgentDeps, str]:
        """Build an Agent with the given model and role-specific tools."""
        tools = get_tools_for_role(user_role)
        agent: Agent[AgentDeps, str] = Agent(
            model,
            system_prompt=get_system_prompt(user_role),
            retries=2,
        )
        for name, func, description in tools:
            agent.tool(func, name=name, description=description)  # type: ignore[call-overload]
        return agent

    async def _run_agent_stream(
        self,
        agent: Agent[AgentDeps, str],
        user_message: str,
        deps: AgentDeps,
        message_history: list[ModelMessage],
        conversation_id: int | None,
        *,
        emit_conversation_info: bool = True,
    ) -> AsyncIterator[tuple[str, dict[str, Any]]]:
        """Core agent streaming logic. Yields (event_name, data) tuples."""
        if emit_conversation_info and conversation_id is not None:
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
                pass

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
        db: AsyncSession,
        user_role: str | None = None,
    ) -> AsyncIterator[str]:
        """
        Run the agent and yield SSE events.

        Uses agent.iter() for node-by-node streaming so tool call events
        are interleaved with text chunks in real time.

        Fallback chain: GLM (primary) -> Gemini -> Groq.
        If the primary provider fails, the next in chain is tried.

        Pass user_role="guest" with user=None for unauthenticated requests.
        conversation_id=None is allowed for stateless (guest) sessions.

        Events emitted:
            conversation_info  — once, at the start (only when conversation_id is not None)
            text_chunk         — partial text from the model
            tool_call_start    — agent is invoking a tool
            tool_call_end      — tool returned a result
            fallback           — primary failed, switching to fallback provider
            done               — stream finished
            error              — all providers failed
        """
        role = str(user_role or getattr(user, "role", "user"))
        deps = AgentDeps(user=user, db=db, user_role=role)
        message_history = _build_message_history(conversation_history)

        # Build the fallback chain of (label, agent) pairs
        candidates: list[tuple[str, Agent[AgentDeps, str]]] = []
        primary_model = self._create_model()
        candidates.append((self.model_name, self._build_agent(role, primary_model)))

        fb1_model = self._get_fallback_model()
        if fb1_model:
            fb1_name = str(settings.AI_AGENT_FALLBACK_MODEL)
            candidates.append((fb1_name, self._build_agent(role, fb1_model)))

        fb2_model = self._get_fallback2_model()
        if fb2_model:
            fb2_name = str(settings.AI_AGENT_FALLBACK2_MODEL)
            candidates.append((fb2_name, self._build_agent(role, fb2_model)))

        last_error: str | None = None

        for idx, (label, agent) in enumerate(candidates):
            if idx > 0:
                logger.warning("Primary agent failed; falling back to %s", label)
                yield _sse_event("fallback", {
                    "provider": label,
                    "reason": last_error or "unknown",
                })

            try:
                async for event_name, event_data in self._run_agent_stream(
                    agent, user_message, deps, message_history, conversation_id,
                    emit_conversation_info=(idx == 0),
                ):
                    yield _sse_event(event_name, event_data)
                return  # Success — stop trying fallbacks
            except _AgentRunError as exc:
                last_error = exc.message
                logger.error("Agent run error with %s: %s", label, exc.message)
                continue

        # All providers failed
        yield _sse_event("error", {
            "code": "AGENT_ERROR",
            "message": f"All providers failed. Last error: {last_error}"[:200],
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
