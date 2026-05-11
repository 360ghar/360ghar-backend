"""
Tests for app.models.social module — UserMatch, UserConversation, UserMessage, etc.
"""

import logging

import pytest
from sqlalchemy import CheckConstraint

from app.models.enums import (
    ConversationSource,
    ConversationStatus,
    MessageType,
    UserMatchStatus,
    UserReportReason,
    UserReportStatus,
)
from app.models.social import (
    AppCatalog,
    EnumStringType,
    MatchQnAAnswer,
    UserBlock,
    UserConversation,
    UserMatch,
    UserMessage,
    UserReport,
)


def _constraint_names(model) -> set[str]:
    return {
        constraint.name
        for constraint in model.__table__.constraints
        if isinstance(constraint, CheckConstraint)
    }


class TestEnumStringType:
    """Tests for social enum column validation."""

    @pytest.mark.parametrize(
        ("enum_type", "valid_enum", "valid_string", "invalid_string"),
        [
            (UserMatch.__table__.c.status.type, UserMatchStatus.active, "active", "deleted"),
            (
                UserConversation.__table__.c.source.type,
                ConversationSource.listing_interest,
                "listing_interest",
                "manual",
            ),
            (
                UserConversation.__table__.c.status.type,
                ConversationStatus.active,
                "active",
                "deleted",
            ),
            (UserMessage.__table__.c.message_type.type, MessageType.text, "text", "audio"),
            (UserReport.__table__.c.reason.type, UserReportReason.spam, "spam", "fraud"),
            (UserReport.__table__.c.status.type, UserReportStatus.open, "open", "closed"),
        ],
    )
    def test_social_enum_columns_validate_bound_values(
        self,
        enum_type: EnumStringType,
        valid_enum,
        valid_string: str,
        invalid_string: str,
    ):
        assert enum_type.process_bind_param(valid_enum, None) == valid_string
        assert enum_type.process_bind_param(valid_string, None) == valid_string

        with pytest.raises(ValueError):
            enum_type.process_bind_param(invalid_string, None)

    def test_process_result_value_valid_enum(self):
        """Valid database values are converted back to enum members."""
        enum_type = UserMatch.__table__.c.status.type
        result = enum_type.process_result_value("active", None)
        assert result == UserMatchStatus.active
        assert isinstance(result, UserMatchStatus)

    @pytest.mark.parametrize(
        ("enum_type", "valid_string", "expected_enum"),
        [
            (UserMatch.__table__.c.status.type, "active", UserMatchStatus.active),
            (
                UserConversation.__table__.c.status.type,
                "active",
                ConversationStatus.active,
            ),
            (UserMessage.__table__.c.message_type.type, "text", MessageType.text),
            (UserReport.__table__.c.status.type, "open", UserReportStatus.open),
        ],
    )
    def test_process_result_value_parametrized(self, enum_type, valid_string, expected_enum):
        """Multiple enum types round-trip correctly through process_result_value."""
        result = enum_type.process_result_value(valid_string, None)
        assert result == expected_enum
        assert isinstance(result, type(expected_enum))

    def test_process_result_value_none(self):
        """None input returns None."""
        enum_type = UserMatch.__table__.c.status.type
        assert enum_type.process_result_value(None, None) is None

    def test_process_result_value_unknown_returns_raw_string(self, caplog):
        """Unknown database values return the raw string with a warning log."""
        enum_type = UserMatch.__table__.c.status.type
        with caplog.at_level(logging.WARNING, logger="app.models.social"):
            result = enum_type.process_result_value("unknown_value", None)
        assert result == "unknown_value"
        assert not isinstance(result, UserMatchStatus)
        assert "Unknown UserMatchStatus value" in caplog.text

    def test_social_tables_have_enum_check_constraints(self):
        assert "ck_user_matches_status" in _constraint_names(UserMatch)
        assert {
            "ck_user_conversations_source",
            "ck_user_conversations_status",
        }.issubset(_constraint_names(UserConversation))
        assert "ck_user_messages_message_type" in _constraint_names(UserMessage)
        assert {
            "ck_user_reports_reason",
            "ck_user_reports_status",
        }.issubset(_constraint_names(UserReport))


class TestUserMatchModel:
    """Tests for UserMatch model."""

    def test_tablename(self):
        assert UserMatch.__tablename__ == "user_matches"

    def test_default_status(self):
        assert UserMatch.status.default.arg == "active"

    def test_has_required_columns(self):
        columns = {c.name for c in UserMatch.__table__.columns}
        assert {"user_one_id", "user_two_id", "status"}.issubset(columns)


class TestUserConversationModel:
    """Tests for UserConversation model."""

    def test_tablename(self):
        assert UserConversation.__tablename__ == "user_conversations"

    def test_default_source(self):
        assert UserConversation.source.default.arg == "listing_interest"

    def test_default_status(self):
        assert UserConversation.status.default.arg == "active"

    def test_has_required_columns(self):
        columns = {c.name for c in UserConversation.__table__.columns}
        assert {"user_one_id", "user_two_id", "created_by_user_id", "source", "status"}.issubset(columns)


class TestUserMessageModel:
    """Tests for UserMessage model."""

    def test_tablename(self):
        assert UserMessage.__tablename__ == "user_messages"

    def test_default_message_type(self):
        assert UserMessage.message_type.default.arg == "text"

    def test_has_required_columns(self):
        columns = {c.name for c in UserMessage.__table__.columns}
        assert {"conversation_id", "sender_id", "body", "message_type"}.issubset(columns)


class TestUserBlockModel:
    """Tests for UserBlock model."""

    def test_tablename(self):
        assert UserBlock.__tablename__ == "user_blocks"

    def test_has_required_columns(self):
        columns = {c.name for c in UserBlock.__table__.columns}
        assert {"blocker_user_id", "blocked_user_id"}.issubset(columns)


class TestUserReportModel:
    """Tests for UserReport model."""

    def test_tablename(self):
        assert UserReport.__tablename__ == "user_reports"

    def test_default_reason(self):
        assert UserReport.reason.default.arg == "other"

    def test_default_status(self):
        assert UserReport.status.default.arg == "open"

    def test_has_required_columns(self):
        columns = {c.name for c in UserReport.__table__.columns}
        assert {"reporter_user_id", "reported_user_id", "reason", "status"}.issubset(columns)


class TestAppCatalogModel:
    """Tests for AppCatalog model."""

    def test_tablename(self):
        assert AppCatalog.__tablename__ == "app_catalogs"

    def test_default_version(self):
        assert AppCatalog.version.default.arg == 1

    def test_default_is_active(self):
        assert AppCatalog.is_active.default.arg is True


class TestMatchQnAAnswerModel:
    """Tests for MatchQnAAnswer model."""

    def test_tablename(self):
        assert MatchQnAAnswer.__tablename__ == "match_qna_answers"

    def test_has_required_columns(self):
        columns = {c.name for c in MatchQnAAnswer.__table__.columns}
        assert {"match_id", "user_id", "q1", "q2", "q3"}.issubset(columns)
