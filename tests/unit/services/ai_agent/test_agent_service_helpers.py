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
    _is_error_result,
    _structured,
    sse_event,
)


def test_build_message_history_replays_widget_rows_as_tool_roundtrip():
    history = _build_message_history(
        [
            {"id": 1, "role": "user", "content": "hello"},
            {"id": 2, "role": "assistant", "content": "hi"},
            {
                "id": 3,
                "role": "widget",
                "tool_name": "owner_properties_list",
                "tool_result": {"items": [1, 2]},
            },
        ]
    )

    assert isinstance(history[0], ModelRequest)
    assert isinstance(history[0].parts[0], UserPromptPart)
    assert isinstance(history[1], ModelResponse)
    assert isinstance(history[1].parts[0], TextPart)
    assert isinstance(history[2], ModelResponse)
    assert isinstance(history[2].parts[0], ToolCallPart)
    assert history[2].parts[0].tool_call_id == "widget_3"
    assert isinstance(history[3], ModelRequest)
    assert isinstance(history[3].parts[0], ToolReturnPart)
    assert history[3].parts[0].content == '{"items": [1, 2]}'


def test_build_message_history_ignores_roles_that_are_never_stored():
    history = _build_message_history(
        [
            {"role": "user", "content": "hello"},
            {"role": "tool_call", "tool_name": "x", "tool_args": {"k": "v"}},
            {"role": "tool_result", "tool_name": "x", "tool_result": {"ok": True}},
        ]
    )

    assert len(history) == 1
    assert isinstance(history[0].parts[0], UserPromptPart)


def test_is_error_result_marks_only_error_shaped_dicts():
    assert _is_error_result({"error": True, "message": "Denied"}) is True
    assert _is_error_result({"error": "NOT_FOUND"}) is True
    assert _is_error_result({"error": None, "items": []}) is False
    assert _is_error_result({"items": []}) is False
    assert _is_error_result("error") is False


def test_structured_wraps_list_and_string_widget_results():
    assert _structured({"items": [1]}) == {"items": [1]}
    assert _structured([1, 2]) == {"raw": [1, 2]}
    assert _structured("plain text") == {"raw": "plain text"}
    assert _structured('{"items": []}') == {"items": []}


def test_sse_event_format_is_valid():
    event = sse_event("done", {"k": "v"})
    assert event.startswith("event: done\ndata: ")
    assert event.endswith("\n\n")
