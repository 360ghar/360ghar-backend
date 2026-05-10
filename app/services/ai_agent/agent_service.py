"""
Core Pydantic AI Agent service.

Creates a Pydantic AI Agent with all MCP tools registered, manages
conversation history, and streams SSE events back to the client.
"""
from __future__ import annotations

import json
import uuid
from typing import Any, AsyncIterator

from pydantic_ai import (
    Agent,
    FunctionToolCallEvent,
    FunctionToolResultEvent,
    PartDeltaEvent,
    PartStartEvent,
    TextPartDelta,
)
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider
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
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.mcp.chatgpt import get_widget_name_for_tool
from app.services.ai_agent.system_prompt import get_system_prompt
from app.services.ai_agent.tools import AgentDeps, get_tools_for_role

logger = get_logger(__name__)


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
    """Manages a Pydantic AI Agent instance per model configuration."""

    def __init__(self, model: str | None = None):
        self.model_name = model or settings.AI_AGENT_MODEL
        self._provider = OpenAIProvider(
            base_url=settings.AI_AGENT_API_BASE,
            api_key=settings.GLM_API_KEY,
        )
        self._agent_cache: dict[str, Agent[AgentDeps, str]] = {}

    def _create_model(self) -> OpenAIChatModel:
        """Create the GLM model with OpenAI-compatible provider."""
        return OpenAIChatModel(
            self.model_name,
            provider=self._provider,
        )

    def _get_agent(self, user_role: str) -> Agent[AgentDeps, str]:
        """Get or create a cached Agent for the given role.

        Agent instances are reused across requests to avoid repeated
        allocation of model objects, tool schemas, and system prompts.
        """
        if user_role not in self._agent_cache:
            tools = get_tools_for_role(user_role)
            model = self._create_model()
            agent: Agent[AgentDeps, str] = Agent(
                model,
                system_prompt=get_system_prompt(user_role),
                retries=2,
            )
            for name, func, description in tools:
                agent.tool(func, name=name, description=description)
            self._agent_cache[user_role] = agent
        return self._agent_cache[user_role]

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

        Pass user_role="guest" with user=None for unauthenticated requests.
        conversation_id=None is allowed for stateless (guest) sessions.

        Events emitted:
            conversation_info  — once, at the start (only when conversation_id is not None)
            text_chunk         — partial text from the model
            tool_call_start    — agent is invoking a tool
            tool_call_end      — tool returned a result
            done               — stream finished
            error              — something went wrong
        """
        role = user_role or getattr(user, "role", "user")
        agent = self._get_agent(role)
        deps = AgentDeps(user=user, db=db, user_role=role)

        # Build message history for context
        message_history = _build_message_history(conversation_history)

        if conversation_id is not None:
            yield _sse_event("conversation_info", {
                "conversation_id": conversation_id,
            })

        full_text = ""
        tool_calls_count = 0
        had_error = False

        try:
            async with agent.iter(
                user_message,
                deps=deps,
                message_history=message_history,
            ) as run:
                async for node in run:
                    if Agent.is_model_request_node(node):
                        # Stream text deltas from the model
                        async with node.stream(run.ctx) as request_stream:
                            async for event in request_stream:
                                if isinstance(event, PartStartEvent):
                                    if isinstance(event.part, TextPart) and event.part.content:
                                        text = event.part.content
                                        full_text += text
                                        yield _sse_event(
                                            "text_chunk", {"text": text}
                                        )
                                elif isinstance(event, PartDeltaEvent):
                                    if isinstance(event.delta, TextPartDelta):
                                        text = event.delta.content_delta
                                        full_text += text
                                        yield _sse_event(
                                            "text_chunk", {"text": text}
                                        )

                    elif Agent.is_call_tools_node(node):
                        # Stream tool call/result events
                        async with node.stream(run.ctx) as handle_stream:
                            async for event in handle_stream:
                                if isinstance(event, FunctionToolCallEvent):
                                    call_id = (
                                        event.part.tool_call_id
                                        or f"tc_{uuid.uuid4().hex[:8]}"
                                    )
                                    tool_calls_count += 1
                                    yield _sse_event("tool_call_start", {
                                        "call_id": call_id,
                                        "tool": event.part.tool_name,
                                    })
                                elif isinstance(event, FunctionToolResultEvent):
                                    call_id = event.tool_call_id or "unknown"
                                    result_part = event.result
                                    is_retry = isinstance(result_part, RetryPromptPart)
                                    tool_name = getattr(result_part, "tool_name", None) or "unknown"
                                    yield _sse_event("tool_call_end", {
                                        "call_id": call_id,
                                        "tool": tool_name,
                                        "success": not is_retry,
                                        "summary": _summarize_result(
                                            getattr(result_part, "content", "")
                                        ),
                                    })
                                    # Emit widget event if tool has an associated widget
                                    if not is_retry:
                                        widget_name = get_widget_name_for_tool(tool_name)
                                        if widget_name:
                                            result_data = result_part.content
                                            if isinstance(result_data, str):
                                                try:
                                                    result_data = json.loads(result_data)
                                                except (json.JSONDecodeError, TypeError):
                                                    result_data = {"raw": result_data}
                                            yield _sse_event("widget", {
                                                "widget_name": widget_name,
                                                "structured_content": result_data,
                                            })

            # Use run.result.output as the authoritative final text
            try:
                final_output = run.result.output
                if isinstance(final_output, str) and final_output:
                    if not full_text:
                        yield _sse_event("text_chunk", {"text": final_output})
                    if len(final_output) >= len(full_text):
                        full_text = final_output
            except Exception:
                pass

        except Exception as e:
            logger.error("Agent stream error: %s", e, exc_info=True)
            had_error = True
            yield _sse_event("error", {
                "code": "AGENT_ERROR",
                "message": str(e)[:200],
                "recoverable": True,
            })

        if not had_error:
            done_data: dict[str, Any] = {
                "tool_calls_count": tool_calls_count,
                "response_text": full_text,
            }
            if conversation_id is not None:
                done_data["conversation_id"] = conversation_id
            yield _sse_event("done", done_data)


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
