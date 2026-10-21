"""Stream-level checks for the agent frames: tool success and widget emission."""

from __future__ import annotations

import json
from typing import Any

from pydantic_ai import Agent
from pydantic_ai.models.test import TestModel

from app.schemas.ai_agent import (
    AgentStreamEvent,
    DoneFrame,
    ToolCallEndFrame,
    WidgetFrame,
)
from app.services.ai_agent import agent_service
from app.services.ai_agent.agent_service import PydanticAIAgentService
from app.services.ai_agent.deps import AgentDeps


def _agent_with_tool(result: dict[str, Any]) -> Agent:
    def owner_properties_list() -> dict[str, Any]:
        return result

    agent: Agent = Agent(TestModel(call_tools=["owner_properties_list"]), retries=0)
    agent.tool_plain(owner_properties_list, name="owner_properties_list")
    return agent


async def _frames(agent: Agent) -> list:
    service = PydanticAIAgentService(model="test")
    deps = AgentDeps(user=None, user_role="agent")
    return [
        frame
        async for frame in service._run_agent_stream(agent, "hi", deps, [], None)  # noqa: SLF001
    ]


async def test_error_shaped_tool_result_is_a_failed_call_and_emits_no_widget(monkeypatch):
    monkeypatch.setattr(
        agent_service, "get_widget_name_for_tool", lambda _name: "PropertyListWidget"
    )
    frames = await _frames(_agent_with_tool({"error": True, "message": "Denied"}))

    ends = [f for f in frames if isinstance(f, ToolCallEndFrame)]
    assert len(ends) == 1
    assert ends[0].data.success is False
    assert not [f for f in frames if isinstance(f, WidgetFrame)]
    assert isinstance(frames[-1], DoneFrame)


async def test_successful_tool_result_emits_its_widget(monkeypatch):
    monkeypatch.setattr(
        agent_service, "get_widget_name_for_tool", lambda _name: "PropertySearchWidget"
    )
    frames = await _frames(_agent_with_tool({"items": [{"id": 1}, {"id": 2}]}))

    ends = [f for f in frames if isinstance(f, ToolCallEndFrame)]
    assert ends[0].data.success is True
    widgets = [f for f in frames if isinstance(f, WidgetFrame)]
    assert len(widgets) == 1
    assert widgets[0].data.widget_name == "PropertySearchWidget"
    assert widgets[0].data.structured_content.items == [{"id": 1}, {"id": 2}]


async def test_result_that_misses_its_payload_model_sends_no_widget(monkeypatch):
    monkeypatch.setattr(
        agent_service, "get_widget_name_for_tool", lambda _name: "PropertySearchWidget"
    )
    # items must be objects; a list of numbers does not match PropertySearchPayload.
    frames = await _frames(_agent_with_tool({"items": [1, 2]}))

    assert not [f for f in frames if isinstance(f, WidgetFrame)]
    assert isinstance(frames[-1], DoneFrame)


def test_frame_union_publishes_every_frame_name():
    schema = AgentStreamEvent.model_json_schema()
    dumped = str(schema)
    for name in (
        "ConversationInfoFrame",
        "TextChunkFrame",
        "ToolCallStartFrame",
        "ToolCallEndFrame",
        "WidgetFrame",
        "DoneFrame",
        "ErrorFrame",
    ):
        assert name in dumped


def test_widget_frame_publishes_one_payload_model_per_widget_name():
    defs = AgentStreamEvent.model_json_schema()["$defs"]
    widget_names = {
        "PropertySearchWidgetData": "PropertySearchWidget",
        "PropertyDetailsWidgetData": "PropertyDetailsWidget",
        "PropertySwipeWidgetData": "PropertySwipeWidget",
        "VisitSchedulerWidgetData": "VisitSchedulerWidget",
        "VisitListWidgetData": "VisitListWidget",
        "LeaseDetailsWidgetData": "LeaseDetailsWidget",
        "MaintenanceWidgetData": "MaintenanceWidget",
        "OwnerDashboardWidgetData": "OwnerDashboardWidget",
        "LeaseManagementWidgetData": "LeaseManagementWidget",
        "RentCollectionWidgetData": "RentCollectionWidget",
        "TenantRentWidgetData": "TenantRentWidget",
    }
    for model_name, widget_name in widget_names.items():
        assert defs[model_name]["properties"]["widget_name"]["const"] == widget_name
    # The payload model is referenced, so clients can read the per-widget shape.
    assert "PropertySearchPayload" in json.dumps(defs["PropertySearchWidgetData"])
    assert "RentCollectionPayload" in json.dumps(defs["RentCollectionWidgetData"])


def test_widget_frame_wire_shape_keeps_only_the_keys_the_payload_set():
    from app.schemas.ai_agent import WidgetFrame, make_widget_data

    frame = WidgetFrame(
        data=make_widget_data("PropertySearchWidget", {"items": [{"id": 1}], "total": 1})
    )
    payload = json.loads(agent_service.sse_frame(frame).split("data: ", 1)[1])

    assert payload == {
        "widget_name": "PropertySearchWidget",
        "structured_content": {"items": [{"id": 1}], "total": 1},
    }


def test_unknown_widget_name_is_rejected_by_the_typed_union():
    import pytest
    from pydantic import ValidationError

    from app.schemas.ai_agent import make_widget_data

    with pytest.raises(ValidationError):
        make_widget_data("NoSuchWidget", {})
