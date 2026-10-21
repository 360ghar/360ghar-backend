"""Contract fixes in the AI agent: role resolution, typed tool errors, history, search and masking."""

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic_ai import ModelRetry
from pydantic_ai.messages import ModelRequest, ModelResponse, ToolCallPart, ToolReturnPart

from app.mcp.utils import _money
from app.models.enums import PropertyPurpose, PropertyType, UserRole
from app.schemas.ai_agent import AGENT_ERROR_MESSAGE, ErrorData, ErrorFrame
from app.services.ai_agent.agent_service import (
    _build_message_history,
    _jsonable_tool,
    _role_name,
    sse_frame,
)
from app.services.ai_agent.tools import ADMIN_TOOLS, get_tools_for_role
from app.services.ai_agent.tools import discovery as discovery_tools
from app.services.ai_agent.tools import owner as owner_tools
from app.services.visibility import Viewer


def _ctx(user=None, db=None):
    return SimpleNamespace(deps=SimpleNamespace(db=db or AsyncMock(), user=user, user_role="guest"))


def test_role_enum_resolves_to_its_value_and_gets_admin_tools():
    role = _role_name(SimpleNamespace(role=UserRole.agent))

    assert role == "agent"
    names = {name for name, _func, _desc in get_tools_for_role(role)}
    assert {name for name, _f, _d in ADMIN_TOOLS} <= names


@pytest.mark.asyncio
async def test_value_error_in_a_tool_becomes_a_model_retry():
    async def tool(ctx, status: str) -> dict:
        raise ValueError("'flat' is not a valid status")

    wrapped = _jsonable_tool(tool)

    with pytest.raises(ModelRetry) as exc:
        await wrapped(object(), status="flat")
    assert "Invalid arguments for tool" in str(exc.value)


def test_widget_row_becomes_a_tool_call_and_return_pair():
    history = _build_message_history(
        [
            {
                "id": 7,
                "role": "widget",
                "tool_name": "PropertySearchWidget",
                "tool_result": {"items": []},
            },
        ]
    )

    call_part = history[0].parts[0]
    return_part = history[1].parts[0]
    assert isinstance(history[0], ModelResponse) and isinstance(call_part, ToolCallPart)
    assert isinstance(history[1], ModelRequest) and isinstance(return_part, ToolReturnPart)
    assert call_part.tool_call_id == return_part.tool_call_id == "widget_7"
    assert return_part.content == '{"items": []}'


def test_error_frame_carries_fixed_text_only():
    text = sse_frame(ErrorFrame(data=ErrorData(code="AGENT_ERROR", message=AGENT_ERROR_MESSAGE)))

    assert "event: error" in text
    assert AGENT_ERROR_MESSAGE in text
    assert "Traceback" not in text and "stream exploded" not in text


@pytest.mark.asyncio
@pytest.mark.parametrize("given", [PropertyType.house, [PropertyType.house]])
async def test_property_type_accepts_one_value_or_a_list(given):
    captured = {}

    async def fake_search(db, **kwargs):
        captured.update(kwargs)
        return [], None, 0

    with patch.object(discovery_tools, "search_properties", new=fake_search):
        result = await discovery_tools.guest_property_search(
            _ctx(),
            property_type=given,
            purpose=PropertyPurpose.rent,
        )

    assert captured["property_type"] == [PropertyType.house]
    assert captured["purpose"] == PropertyPurpose.rent
    assert result["total"] == 0 and result["limit"] == 20 and result["items"] == []


@pytest.mark.asyncio
async def test_guest_property_details_masks_owner_contact_for_anonymous_viewer():
    prop = SimpleNamespace(id=5)
    with (
        patch("app.services.property.get_property", new=AsyncMock(return_value=prop)),
        patch.object(discovery_tools, "mask_owner_contact", return_value=prop) as mask,
        patch.object(discovery_tools, "serialize_property_full", return_value={"id": 5}),
    ):
        await discovery_tools.guest_property_details(_ctx(user=None), property_id=5)

    viewer = mask.call_args.args[1]
    assert isinstance(viewer, Viewer) and viewer.id is None


@pytest.mark.asyncio
async def test_rent_due_reuses_the_mcp_computation():
    due = {
        "items": [{"lease_id": 1}],
        "total_due": 10.0,
        "overdue_count": 1,
        "has_more": False,
        "next_cursor": None,
        "limit": 20,
    }
    with patch.object(
        owner_tools, "compute_rent_due_items", new=AsyncMock(return_value=due)
    ) as compute:
        result = await owner_tools.agent_rent_list_due(
            _ctx(user=SimpleNamespace(id=2, role="user", agent_id=None)), overdue_only=True
        )

    assert compute.await_args.kwargs["overdue_only"] is True
    assert result["items"] == [{"lease_id": 1}]
    assert "total" not in result


def test_money_is_a_rounded_json_number():
    assert _money(Decimal("1234.5")) == 1234.5
    assert isinstance(_money(Decimal("10")), float)
    assert _money(None) is None


@pytest.mark.asyncio
async def test_history_orders_rows_of_one_reply_by_id_as_tie_break():
    from sqlalchemy.dialects import postgresql

    from app.services.ai_agent import conversation_store

    db = AsyncMock()
    db.execute = AsyncMock(
        return_value=SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: []))
    )

    await conversation_store.get_history(db, 3, limit=5)

    sql = str(db.execute.await_args.args[0].compile(dialect=postgresql.dialect()))
    assert "created_at DESC, ai_conversation_messages.id DESC" in sql


@pytest.mark.asyncio
async def test_agent_property_list_reports_the_real_total_not_the_page_length():
    prop = SimpleNamespace(id=1)
    with (
        patch(
            "app.services.pm_properties.list_managed_properties",
            new=AsyncMock(return_value=([prop], None, 45)),
        ),
        patch.object(owner_tools, "_user_schema", return_value=None),
        patch.object(
            owner_tools,
            "enrich_properties_with_lease_info",
            new=AsyncMock(return_value=([{"id": 1}], {})),
        ),
        patch.object(owner_tools, "owner_scope", new=AsyncMock(return_value=None)),
        patch.object(owner_tools, "compute_portfolio_stats", new=AsyncMock(return_value={})),
    ):
        result = await owner_tools.agent_properties_list(
            _ctx(user=SimpleNamespace(id=2)), limit=1, include_total=True
        )

    assert result["total"] == 45
    assert len(result["items"]) == 1
    assert result["limit"] == 1


def test_tour_form_uses_the_request_field_names():
    import inspect

    from app.api.api_v1.endpoints.ai import generate_tour

    params = set(inspect.signature(generate_tour).parameters)
    assert {
        "generate_titles",
        "generate_descriptions",
        "suggest_hotspots",
        "spatial",
        "apply_to_scenes",
        "language",
    } <= params
    assert not {"auto_detect_rooms", "auto_place_hotspots", "auto_generate_descriptions"} & params


async def test_maintenance_status_outside_the_transition_set_is_rejected():
    from app.mcp.tool_ops import update_maintenance_status

    with pytest.raises(ValueError):
        await update_maintenance_status(
            AsyncMock(), actor=MagicMock(), request_id=1, status="flat"
        )


SHARED_SEARCH_ARGS = {
    "query",
    "city",
    "locality",
    "latitude",
    "longitude",
    "radius_km",
    "property_type",
    "purpose",
    "price_min",
    "price_max",
    "bedrooms_min",
    "bedrooms_max",
    "amenities",
    "cursor",
    "limit",
    "include_total",
}


@pytest.mark.asyncio
async def test_agent_and_mcp_discovery_search_share_arguments_and_envelope():
    """be-ai-20: one search contract for the agent tool and the MCP tool (same name, same shape)."""
    import inspect

    from app.mcp.chatgpt import discovery_tools as mcp_discovery

    agent_args = set(inspect.signature(discovery_tools.guest_property_search).parameters)
    mcp_args = set(inspect.signature(mcp_discovery.discovery_search).parameters)
    assert SHARED_SEARCH_ARGS <= agent_args
    assert SHARED_SEARCH_ARGS <= mcp_args

    with patch.object(
        discovery_tools, "search_properties", new=AsyncMock(return_value=([], None, 0))
    ):
        agent_out = await discovery_tools.guest_property_search(_ctx(), include_total=True)
    # The MCP tool returns these keys too (see tests/unit/mcp/test_discovery_tools.py).
    assert {"items", "total", "next_cursor", "has_more", "limit"} <= set(agent_out)
