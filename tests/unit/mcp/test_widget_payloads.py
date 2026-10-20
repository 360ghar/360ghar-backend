"""Widget payloads: one model and one producer per widget name, shared by MCP and agent."""

from app.mcp.chatgpt import WIDGETS
from app.mcp.chatgpt.response_formatter import format_chatgpt_response
from app.mcp.chatgpt.widget_payloads import WIDGET_PAYLOADS, WidgetPayload, widget_payload


def test_every_widget_name_has_exactly_one_model_and_one_producer():
    assert set(WIDGET_PAYLOADS) == set(WIDGETS)

    models = [binding.model for binding in WIDGET_PAYLOADS.values()]
    producers = [binding.produce for binding in WIDGET_PAYLOADS.values()]
    assert len(set(models)) == len(models), "two widgets share a payload model"
    assert len(set(producers)) == len(producers), "two widgets share a producer"

    for name, binding in WIDGET_PAYLOADS.items():
        assert issubclass(binding.model, WidgetPayload), name
        assert isinstance(binding.produce({}), binding.model), name


def test_declared_keys_are_validated_and_extra_keys_pass_through():
    payload = widget_payload(
        "VisitListWidget",
        {"items": [{"id": 1}], "total": 1, "counts": {"total": 1}, "custom": "kept"},
    )

    assert payload == {
        "items": [{"id": 1}],
        "total": 1,
        "counts": {"total": 1},
        "custom": "kept",
    }


def test_error_result_keeps_its_keys_and_gains_no_list_defaults():
    data = {"error": True, "message": "No active lease found."}

    assert widget_payload("MaintenanceWidget", data) == data


def test_value_the_model_cannot_hold_is_sent_unchanged():
    data = {"items": "not-a-list"}

    assert widget_payload("PropertySearchWidget", data) == data


def test_unknown_widget_name_passes_data_through():
    assert widget_payload("NoSuchWidget", {"a": 1}) == {"a": 1}


def test_formatter_sends_the_typed_payload_as_structured_content():
    result = format_chatgpt_response(
        data={"items": [{"id": 3}], "total": 3, "extra": 1},
        content_summary="Found 3.",
        widget_uri="ui://widget/propertysearchwidget.html?v=abc123",
    )

    assert result.structured_content == {"items": [{"id": 3}], "total": 3, "extra": 1}
    assert result.meta["ui"]["resourceUri"].startswith("ui://widget/propertysearchwidget")


def test_formatter_without_a_widget_leaves_data_alone():
    result = format_chatgpt_response(data={"items": []}, content_summary="None.")

    assert result.structured_content == {"items": []}


def test_rent_collection_frame_carries_one_nested_totals_object():
    """The agent rent-due result (counts renamed to totals) reaches the widget frame with real totals."""
    from app.schemas.ai_agent import make_widget_data, widget_result_dict

    result = {
        "items": [{"id": 1, "balance": 25000.0, "status": "overdue"}],
        "totals": {
            "total_due": 60000.0,
            "total_paid": 5000.0,
            "overdue_count": 2,
            "charges_count": 3,
        },
        "next_cursor": "abc",
        "has_more": True,
        "limit": 1,
    }
    frame = make_widget_data("RentCollectionWidget", result)
    stored = widget_result_dict(frame)

    assert stored is not None
    assert stored["totals"] == result["totals"]
    assert "total_due" not in stored  # no top-level copy that no producer sets
    assert frame.structured_content.totals.total_due == 60000.0
    assert frame.structured_content.totals.overdue_count == 2
