"""Unit tests for the ChatGPT visit MCP tools.

Exercises ``visits_schedule``, ``visits_list``, ``visits_get`` and
``visits_cancel`` in ``app.mcp.chatgpt.visit_tools``. The database session
(``AsyncSessionLocal``), user resolution (``_get_optional_user``), widget
resolution (``get_widget_for_tool``) and the underlying visit/property service
functions are all mocked so the tests run without a real database.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.mcp.apps_sdk import AuthRequiredError

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _SessionContext:
    """Async context manager mimicking ``AsyncSessionLocal()``."""

    def __init__(self, db):
        self.db = db

    async def __aenter__(self):
        return self.db

    async def __aexit__(self, exc_type, exc, tb):
        return False


def _make_user(user_id: int = 10):
    now = datetime.now(timezone.utc)
    return SimpleNamespace(
        id=user_id,
        role="user",
        supabase_user_id=f"user-{user_id}",
        phone="+919876543210",
        full_name="Visitor User",
        email=f"user{user_id}@example.com",
        is_active=True,
        is_verified=True,
        agent_id=None,
        created_at=now,
        updated_at=now,
    )


def _make_visit(
    visit_id: int = 1,
    property_id: int = 1,
    user_id: int = 10,
    status_value: str = "confirmed",
    scheduled_date: datetime | None = None,
    notes: str | None = None,
):
    """Build a mock visit object matching the shape ``_serialize_visit`` reads."""
    prop = SimpleNamespace(
        id=property_id,
        title="Test Property",
        locality="Karol Bagh",
        city="Delhi",
        images=[],  # empty list -> main_image_url is None
    )
    return SimpleNamespace(
        id=visit_id,
        property_id=property_id,
        user_id=user_id,
        property=prop,
        scheduled_date=scheduled_date or (datetime.now(timezone.utc) + timedelta(days=7)),
        status=SimpleNamespace(value=status_value),
        notes=notes,
        created_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
    )


def _content_text(result) -> str:
    """Extract plain text from an AppsSDKToolResult ``content`` field."""
    content = result.content
    if isinstance(content, list) and content:
        block = content[0]
        return getattr(block, "text", str(block))
    return str(content)


# Common patch context helpers ------------------------------------------------

_VISIT_TOOLS = "app.mcp.chatgpt.visit_tools"


def _patch_session(db):
    return patch(f"{_VISIT_TOOLS}.AsyncSessionLocal", return_value=_SessionContext(db))


def _patch_user(user):
    return patch(f"{_VISIT_TOOLS}._get_optional_user", new=AsyncMock(return_value=user))


def _patch_guest():
    return patch(f"{_VISIT_TOOLS}._get_optional_user", new=AsyncMock(return_value=None))


def _patch_widget():
    return patch(f"{_VISIT_TOOLS}.get_widget_for_tool", return_value="ui://widget/dummy.html")


# ===========================================================================
# visits_schedule
# ===========================================================================


class TestVisitsSchedule:
    """Tests for the visits_schedule MCP tool."""

    @pytest.mark.asyncio
    async def test_requires_auth(self):
        db = AsyncMock()

        with (
            _patch_session(db),
            _patch_guest(),
            _patch_widget(),
        ):
            from app.mcp.chatgpt.visit_tools import visits_schedule

            with pytest.raises(AuthRequiredError):
                await visits_schedule(
                    property_id=1,
                    scheduled_date="2099-07-01T10:00:00",
                )

    @pytest.mark.asyncio
    async def test_schedule_guest_user_redirected_to_auth(self):
        # Guests are challenged with an auth error carrying the original
        # request context so the host can resume after sign-in.
        db = AsyncMock()

        with (
            _patch_session(db),
            _patch_guest(),
            _patch_widget(),
        ):
            from app.mcp.chatgpt.visit_tools import visits_schedule

            with pytest.raises(AuthRequiredError) as exc_info:
                await visits_schedule(
                    property_id=42,
                    scheduled_date="2099-07-01T10:00:00",
                    notes="Call before arriving",
                )

        assert exc_info.value.structured_content["action"] == "schedule_visit"
        assert exc_info.value.structured_content["property_id"] == 42
        assert exc_info.value.structured_content["requires_auth"] is True

    @pytest.mark.asyncio
    async def test_schedule_success(self):
        db = AsyncMock()
        user = _make_user()
        visit = _make_visit(visit_id=5, property_id=1, user_id=user.id, notes="Early")

        with (
            _patch_session(db),
            _patch_user(user),
            _patch_widget(),
            patch("app.services.property.get_property", new=AsyncMock(return_value=SimpleNamespace(id=1))),
            patch("app.services.visit.create_visit", new=AsyncMock(return_value=visit)),
        ):
            from app.mcp.chatgpt.visit_tools import visits_schedule

            result = await visits_schedule(
                property_id=1,
                scheduled_date="2099-07-01T10:00:00",
                notes="Early",
            )

        assert result.structured_content["visit"]["id"] == 5
        assert result.structured_content["visit"]["property"]["title"] == "Test Property"
        db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_schedule_invalid_date_format(self):
        db = AsyncMock()
        user = _make_user()

        with (
            _patch_session(db),
            _patch_user(user),
            _patch_widget(),
        ):
            from app.mcp.chatgpt.visit_tools import visits_schedule

            result = await visits_schedule(
                property_id=1,
                scheduled_date="not-a-date",
            )

        assert result.structured_content["error"] is True
        assert result.structured_content["code"] == "INVALID_DATE"
        assert "ISO 8601" in _content_text(result)
        # The property service must never be reached on a bad date.
        db.commit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_schedule_nonexistent_property(self):
        db = AsyncMock()
        user = _make_user()

        with (
            _patch_session(db),
            _patch_user(user),
            _patch_widget(),
            patch(
                "app.services.property.get_property",
                new=AsyncMock(side_effect=Exception("not found")),
            ),
        ):
            from app.mcp.chatgpt.visit_tools import visits_schedule

            result = await visits_schedule(
                property_id=999,
                scheduled_date="2099-07-01T10:00:00",
            )

        assert result.structured_content["error"] is True
        assert result.structured_content["code"] == "NOT_FOUND"
        assert result.structured_content["property_id"] == 999
        db.commit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_schedule_past_date_returns_error(self):
        db = AsyncMock()
        user = _make_user()

        with (
            _patch_session(db),
            _patch_user(user),
            _patch_widget(),
        ):
            from app.mcp.chatgpt.visit_tools import visits_schedule

            result = await visits_schedule(
                property_id=1,
                scheduled_date="2000-01-01T10:00:00",
            )

        assert result.structured_content["error"] is True
        assert result.structured_content["code"] == "PAST_DATE"
        db.commit.assert_not_awaited()


# ===========================================================================
# visits_list
# ===========================================================================


class TestVisitsList:
    """Tests for the visits_list MCP tool."""

    @pytest.mark.asyncio
    async def test_requires_auth(self):
        db = AsyncMock()

        with (
            _patch_session(db),
            _patch_guest(),
            _patch_widget(),
        ):
            from app.mcp.chatgpt.visit_tools import visits_list

            with pytest.raises(AuthRequiredError):
                await visits_list()

    @pytest.mark.asyncio
    async def test_list_returns_visits(self):
        db = AsyncMock()
        user = _make_user()
        visits = [
            _make_visit(visit_id=1, user_id=user.id, status_value="confirmed"),
            _make_visit(visit_id=2, user_id=user.id, status_value="completed"),
        ]
        mock_get = AsyncMock(return_value=(visits, None, 2))

        with (
            _patch_session(db),
            _patch_user(user),
            _patch_widget(),
            patch(f"{_VISIT_TOOLS}.get_user_visits", new=mock_get),
        ):
            from app.mcp.chatgpt.visit_tools import visits_list

            result = await visits_list()

        assert result.structured_content["total"] == 2
        assert len(result.structured_content["visits"]) == 2
        assert result.structured_content["has_more"] is False

    @pytest.mark.asyncio
    async def test_list_empty(self):
        db = AsyncMock()
        user = _make_user()
        mock_get = AsyncMock(return_value=([], None, 0))

        with (
            _patch_session(db),
            _patch_user(user),
            _patch_widget(),
            patch(f"{_VISIT_TOOLS}.get_user_visits", new=mock_get),
        ):
            from app.mcp.chatgpt.visit_tools import visits_list

            result = await visits_list()

        assert result.structured_content["total"] == 0
        assert result.structured_content["visits"] == []
        assert "don't have any property visits" in _content_text(result)

    @pytest.mark.asyncio
    async def test_list_filter_by_status(self):
        db = AsyncMock()
        user = _make_user()
        # Service returns all rows; the wrapper filters client-side by status.
        visits = [
            _make_visit(visit_id=1, user_id=user.id, status_value="confirmed"),
            _make_visit(visit_id=2, user_id=user.id, status_value="completed"),
            _make_visit(visit_id=3, user_id=user.id, status_value="cancelled"),
        ]
        mock_get = AsyncMock(return_value=(visits, None, 3))

        with (
            _patch_session(db),
            _patch_user(user),
            _patch_widget(),
            patch(f"{_VISIT_TOOLS}.get_user_visits", new=mock_get),
        ):
            from app.mcp.chatgpt.visit_tools import visits_list

            result = await visits_list(status="completed")

        returned = result.structured_content["visits"]
        assert len(returned) == 1
        assert returned[0]["id"] == 2
        assert result.structured_content["total"] == 1


# ===========================================================================
# visits_get
# ===========================================================================


class TestVisitsGet:
    """Tests for the visits_get MCP tool."""

    @pytest.mark.asyncio
    async def test_requires_auth(self):
        db = AsyncMock()

        with (
            _patch_session(db),
            _patch_guest(),
            _patch_widget(),
        ):
            from app.mcp.chatgpt.visit_tools import visits_get

            with pytest.raises(AuthRequiredError):
                await visits_get(visit_id=1)

    @pytest.mark.asyncio
    async def test_get_existing_visit(self):
        db = AsyncMock()
        user = _make_user()
        visit = _make_visit(visit_id=7, user_id=user.id, status_value="confirmed")

        with (
            _patch_session(db),
            _patch_user(user),
            _patch_widget(),
            patch("app.services.visit.get_visit", new=AsyncMock(return_value=visit)),
        ):
            from app.mcp.chatgpt.visit_tools import visits_get

            result = await visits_get(visit_id=7)

        assert result.structured_content["visit"]["id"] == 7
        assert result.structured_content["visit"]["property"]["title"] == "Test Property"

    @pytest.mark.asyncio
    async def test_get_nonexistent_visit(self):
        db = AsyncMock()
        user = _make_user()

        with (
            _patch_session(db),
            _patch_user(user),
            _patch_widget(),
            patch("app.services.visit.get_visit", new=AsyncMock(return_value=None)),
        ):
            from app.mcp.chatgpt.visit_tools import visits_get

            result = await visits_get(visit_id=999)

        assert result.structured_content["error"] is True
        assert result.structured_content["code"] == "NOT_FOUND"
        assert result.structured_content["visit_id"] == 999

    @pytest.mark.asyncio
    async def test_get_other_users_visit_forbidden(self):
        db = AsyncMock()
        user = _make_user(user_id=10)
        # Visit belongs to a different user
        visit = _make_visit(visit_id=7, user_id=999, status_value="confirmed")

        with (
            _patch_session(db),
            _patch_user(user),
            _patch_widget(),
            patch("app.services.visit.get_visit", new=AsyncMock(return_value=visit)),
        ):
            from app.mcp.chatgpt.visit_tools import visits_get

            result = await visits_get(visit_id=7)

        assert result.structured_content["error"] is True
        assert result.structured_content["code"] == "FORBIDDEN"


# ===========================================================================
# visits_cancel
# ===========================================================================


class TestVisitsCancel:
    """Tests for the visits_cancel MCP tool."""

    @pytest.mark.asyncio
    async def test_requires_auth(self):
        db = AsyncMock()

        with (
            _patch_session(db),
            _patch_guest(),
            _patch_widget(),
        ):
            from app.mcp.chatgpt.visit_tools import visits_cancel

            with pytest.raises(AuthRequiredError):
                await visits_cancel(visit_id=1)

    @pytest.mark.asyncio
    async def test_cancel_success(self):
        db = AsyncMock()
        user = _make_user()
        visit = _make_visit(visit_id=3, user_id=user.id, status_value="confirmed")
        mock_cancel = AsyncMock(return_value=visit)

        with (
            _patch_session(db),
            _patch_user(user),
            _patch_widget(),
            patch("app.services.visit.get_visit", new=AsyncMock(return_value=visit)),
            patch("app.services.visit.cancel_visit", new=mock_cancel),
        ):
            from app.mcp.chatgpt.visit_tools import visits_cancel

            result = await visits_cancel(visit_id=3, reason="Busy")

        assert result.structured_content["success"] is True
        assert result.structured_content["visit_id"] == 3
        assert result.structured_content["status"] == "cancelled"
        mock_cancel.assert_awaited_once_with(db, 3, "Busy")
        db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_cancel_nonexistent_visit(self):
        db = AsyncMock()
        user = _make_user()

        with (
            _patch_session(db),
            _patch_user(user),
            _patch_widget(),
            patch("app.services.visit.get_visit", new=AsyncMock(return_value=None)),
            patch("app.services.visit.cancel_visit", new=AsyncMock()),
        ):
            from app.mcp.chatgpt.visit_tools import visits_cancel

            result = await visits_cancel(visit_id=999)

        assert result.structured_content["error"] is True
        assert result.structured_content["code"] == "NOT_FOUND"
        assert result.structured_content["visit_id"] == 999
        db.commit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_cancel_already_completed_visit(self):
        db = AsyncMock()
        user = _make_user()
        visit = _make_visit(visit_id=3, user_id=user.id, status_value="completed")

        with (
            _patch_session(db),
            _patch_user(user),
            _patch_widget(),
            patch("app.services.visit.get_visit", new=AsyncMock(return_value=visit)),
            patch("app.services.visit.cancel_visit", new=AsyncMock()),
        ):
            from app.mcp.chatgpt.visit_tools import visits_cancel

            result = await visits_cancel(visit_id=3)

        assert result.structured_content["error"] is True
        assert result.structured_content["code"] == "INVALID_STATUS"
        assert result.structured_content["current_status"] == "completed"
        db.commit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_cancel_other_users_visit_forbidden(self):
        db = AsyncMock()
        user = _make_user(user_id=10)
        visit = _make_visit(visit_id=3, user_id=999, status_value="confirmed")

        with (
            _patch_session(db),
            _patch_user(user),
            _patch_widget(),
            patch("app.services.visit.get_visit", new=AsyncMock(return_value=visit)),
            patch("app.services.visit.cancel_visit", new=AsyncMock()),
        ):
            from app.mcp.chatgpt.visit_tools import visits_cancel

            result = await visits_cancel(visit_id=3)

        assert result.structured_content["error"] is True
        assert result.structured_content["code"] == "FORBIDDEN"
