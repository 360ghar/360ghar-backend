from datetime import datetime, timezone

import pytest

from app.schemas.ai_agent import AgentChatRequest, ConversationMessageOut


class TestConversationMessageOut:
    def test_widget_role_populates_widget_fields(self):
        now = datetime.now(timezone.utc)
        message = ConversationMessageOut.model_validate(
            {
                "id": 1,
                "role": "widget",
                "content": None,
                "tool_name": "OwnerDashboardWidget",
                "tool_args": None,
                "tool_result": {"summary": "ok"},
                "created_at": now,
            }
        )

        assert message.widget_name == "OwnerDashboardWidget"
        assert message.widget_data == {"summary": "ok"}

    def test_non_widget_role_keeps_widget_fields_empty(self):
        now = datetime.now(timezone.utc)
        message = ConversationMessageOut.model_validate(
            {
                "id": 2,
                "role": "assistant",
                "content": "hello",
                "tool_name": "any_tool",
                "tool_result": {"x": 1},
                "created_at": now,
            }
        )

        assert message.widget_name is None
        assert message.widget_data is None

    def test_widget_role_with_missing_tool_fields_sets_widget_fields_to_none(self):
        now = datetime.now(timezone.utc)
        message = ConversationMessageOut.model_validate(
            {
                "id": 3,
                "role": "widget",
                "content": None,
                "tool_name": None,
                "tool_result": None,
                "created_at": now,
            }
        )

        assert message.widget_name is None
        assert message.widget_data is None


class TestAgentChatRequest:
    def test_message_accepts_max_length(self):
        payload = AgentChatRequest.model_validate({"message": "a" * 4000})
        assert len(payload.message) == 4000

    def test_message_rejects_blank_and_too_long(self):
        with pytest.raises(ValueError):
            AgentChatRequest.model_validate({"message": ""})

        with pytest.raises(ValueError):
            AgentChatRequest.model_validate({"message": "a" * 4001})
