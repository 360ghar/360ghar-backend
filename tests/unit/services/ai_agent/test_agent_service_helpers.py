from pydantic_ai.messages import (
    ModelRequest,
    ModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)

from app.services.ai_agent.agent_service import (
    _build_message_history,
    sse_event,
    _summarize_result,
)


def test_build_message_history_handles_user_assistant_and_tool_roundtrip():
    history = _build_message_history(
        [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi"},
            {
                "role": "tool_call",
                "tool_name": "owner_properties_list",
                "tool_args": {"page": 1},
                "tool_call_id": "tc_1",
            },
            {
                "role": "tool_result",
                "tool_name": "owner_properties_list",
                "tool_result": {"items": [1, 2]},
                "tool_call_id": "tc_1",
            },
        ]
    )

    assert isinstance(history[0], ModelRequest)
    assert isinstance(history[0].parts[0], UserPromptPart)
    assert isinstance(history[1], ModelResponse)
    assert isinstance(history[1].parts[0], TextPart)
    assert isinstance(history[2], ModelResponse)
    assert isinstance(history[2].parts[0], ToolCallPart)
    assert isinstance(history[3], ModelRequest)
    assert isinstance(history[3].parts[0], ToolReturnPart)
    assert history[3].parts[0].content == '{"items": [1, 2]}'


def test_build_message_history_uses_safe_defaults_for_invalid_tool_args_and_unflushed_calls():
    history = _build_message_history(
        [
            {"role": "tool_call", "tool_name": "bad_args", "tool_args": "not-a-dict"},
            {"role": "tool_result", "tool_name": "bad_args", "tool_result": "done"},
            {"role": "tool_call", "tool_name": "pending", "tool_args": {"k": "v"}},
        ]
    )

    first_tool_call = history[0].parts[0]
    assert isinstance(first_tool_call, ToolCallPart)
    assert first_tool_call.args == {}

    tool_return = history[1].parts[0]
    assert isinstance(tool_return, ToolReturnPart)
    assert tool_return.content == "done"
    assert tool_return.tool_call_id == "unknown"

    pending_tool_call = history[2].parts[0]
    assert isinstance(pending_tool_call, ToolCallPart)
    assert pending_tool_call.tool_name == "pending"


def test_summarize_result_covers_all_branches():
    assert _summarize_result({"message": "ok"}) == "ok"
    assert _summarize_result({"items": [1, 2, 3]}) == "Found 3 items"
    assert _summarize_result({"error": "bad", "message": "Denied"}) == "Denied"
    assert _summarize_result("x" * 200, max_len=10) == "x" * 10
    assert _summarize_result(12345, max_len=3) == "123"


def test_sse_event_format_is_valid():
    event = sse_event("done", {"k": "v"})
    assert event.startswith("event: done\ndata: ")
    assert event.endswith("\n\n")
