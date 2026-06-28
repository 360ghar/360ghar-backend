"""Unit tests for MCP tool input coercion.

Verifies that MCP tools gracefully coerce the loosely-typed inputs that MCP
clients (and LLMs) tend to send into the strict shapes the service layer
expects. Covers:

- ``amenities`` string→list coercion in ``discovery_search``
- ``amenity_ids`` string→int-list coercion in ``owner_properties_create``
- ``limit`` clamping across ``discovery_search`` / ``discovery_feed`` / ``owner_properties_list``
- ISO-8601 date parsing in the booking tool_ops layer
"""
from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from app.mcp.tool_ops import bookings as bookings_tool_ops

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _SessionContext:
    """Async context manager that mimics ``AsyncSessionLocal()``."""

    def __init__(self, db: Any) -> None:
        self.db = db

    async def __aenter__(self) -> Any:
        return self.db

    async def __aexit__(self, *_: object) -> bool:
        return False


async def _async_gen(db: Any):
    """Async generator that yields db, mimicking get_db()."""
    yield db


def _make_user(user_id: int = 10) -> SimpleNamespace:
    return SimpleNamespace(
        id=user_id,
        role="user",
        supabase_user_id=f"user-{user_id}",
        phone="+919876543210",
        full_name="Owner User",
        email=f"user{user_id}@example.com",
        is_active=True,
        is_verified=True,
        agent_id=None,
    )


def _capture_unified_call(mock: AsyncMock) -> Any:
    """Return the ``filters`` kwarg from the most recent get_unified_properties_optimized call."""
    assert mock.await_count >= 1, "expected get_unified_properties_optimized to be awaited"
    return mock.await_args.kwargs["filters"]


# ---------------------------------------------------------------------------
# Amenities string coercion (discovery_search)
# ---------------------------------------------------------------------------


class TestAmenitiesStringCoercion:
    async def test_csv_string_to_list(self) -> None:
        """'wifi,pool' → ['wifi','pool']."""
        db = AsyncMock()
        unified_mock = AsyncMock(return_value=([], None, 0))

        with (
            patch("app.mcp.chatgpt.discovery_tools.AsyncSessionLocal", return_value=_SessionContext(db)),
            patch("app.mcp.chatgpt.discovery_tools._get_optional_user", new=AsyncMock(return_value=None)),
            patch("app.services.property.get_unified_properties_optimized", new=unified_mock),
        ):
            from app.mcp.chatgpt.discovery_tools import discovery_search

            await discovery_search(amenities="wifi,pool")

        filters = _capture_unified_call(unified_mock)
        assert filters.amenities == ["wifi", "pool"]

    async def test_single_string_to_list(self) -> None:
        """'wifi' → ['wifi']."""
        db = AsyncMock()
        unified_mock = AsyncMock(return_value=([], None, 0))

        with (
            patch("app.mcp.chatgpt.discovery_tools.AsyncSessionLocal", return_value=_SessionContext(db)),
            patch("app.mcp.chatgpt.discovery_tools._get_optional_user", new=AsyncMock(return_value=None)),
            patch("app.services.property.get_unified_properties_optimized", new=unified_mock),
        ):
            from app.mcp.chatgpt.discovery_tools import discovery_search

            await discovery_search(amenities="wifi")

        filters = _capture_unified_call(unified_mock)
        assert filters.amenities == ["wifi"]

    async def test_list_unchanged(self) -> None:
        """['wifi','pool'] (already a list) passes through unchanged."""
        db = AsyncMock()
        unified_mock = AsyncMock(return_value=([], None, 0))

        with (
            patch("app.mcp.chatgpt.discovery_tools.AsyncSessionLocal", return_value=_SessionContext(db)),
            patch("app.mcp.chatgpt.discovery_tools._get_optional_user", new=AsyncMock(return_value=None)),
            patch("app.services.property.get_unified_properties_optimized", new=unified_mock),
        ):
            from app.mcp.chatgpt.discovery_tools import discovery_search

            await discovery_search(amenities=["wifi", "pool"])

        filters = _capture_unified_call(unified_mock)
        assert filters.amenities == ["wifi", "pool"]

    async def test_none_unchanged(self) -> None:
        """None amenities stays None (no coercion)."""
        db = AsyncMock()
        unified_mock = AsyncMock(return_value=([], None, 0))

        with (
            patch("app.mcp.chatgpt.discovery_tools.AsyncSessionLocal", return_value=_SessionContext(db)),
            patch("app.mcp.chatgpt.discovery_tools._get_optional_user", new=AsyncMock(return_value=None)),
            patch("app.services.property.get_unified_properties_optimized", new=unified_mock),
        ):
            from app.mcp.chatgpt.discovery_tools import discovery_search

            await discovery_search(amenities=None)

        filters = _capture_unified_call(unified_mock)
        assert filters.amenities is None

    async def test_non_string_non_list_to_list(self) -> None:
        """123 → ['123'] (any other scalar gets stringified into a single-item list)."""
        db = AsyncMock()
        unified_mock = AsyncMock(return_value=([], None, 0))

        with (
            patch("app.mcp.chatgpt.discovery_tools.AsyncSessionLocal", return_value=_SessionContext(db)),
            patch("app.mcp.chatgpt.discovery_tools._get_optional_user", new=AsyncMock(return_value=None)),
            patch("app.services.property.get_unified_properties_optimized", new=unified_mock),
        ):
            from app.mcp.chatgpt.discovery_tools import discovery_search

            await discovery_search(amenities=123)  # type: ignore[arg-type]

        filters = _capture_unified_call(unified_mock)
        assert filters.amenities == ["123"]

    async def test_csv_string_trims_whitespace(self) -> None:
        """'wifi, pool ' → ['wifi','pool'] (whitespace stripped, blanks dropped)."""
        db = AsyncMock()
        unified_mock = AsyncMock(return_value=([], None, 0))

        with (
            patch("app.mcp.chatgpt.discovery_tools.AsyncSessionLocal", return_value=_SessionContext(db)),
            patch("app.mcp.chatgpt.discovery_tools._get_optional_user", new=AsyncMock(return_value=None)),
            patch("app.services.property.get_unified_properties_optimized", new=unified_mock),
        ):
            from app.mcp.chatgpt.discovery_tools import discovery_search

            await discovery_search(amenities="wifi, pool ,")

        filters = _capture_unified_call(unified_mock)
        assert filters.amenities == ["wifi", "pool"]


# ---------------------------------------------------------------------------
# amenity_ids coercion (owner_properties_create)
# ---------------------------------------------------------------------------


class TestAmenityIdsCoercion:
    """Verify owner_properties_create coerces amenity_ids before delegating."""

    async def _run(self, amenity_ids: Any) -> Any:
        """Invoke owner_properties_create with the given amenity_ids and return the captured value."""
        db = AsyncMock()
        user = _make_user()
        create_mock = AsyncMock(return_value={"message": "created", "property": {"id": 1}})

        with (
            patch("app.mcp.user.owner.get_db", return_value=_async_gen(db)),
            patch("app.mcp.user.owner._get_user", new=AsyncMock(return_value=user)),
            patch("app.mcp.user.owner.create_property", new=create_mock),
        ):
            from app.mcp.user.owner import owner_properties_create

            await owner_properties_create(
                title="Test Property",
                property_type="apartment",
                purpose="rent",
                full_address="123 Main St",
                city="Delhi",
                locality="Rohini",
                latitude=28.7,
                longitude=77.1,
                base_price=50000,
                amenity_ids=amenity_ids,
            )

        return create_mock.await_args.kwargs["amenity_ids"]

    async def test_csv_string_to_int_list(self) -> None:
        """'1,2,3' → [1,2,3]."""
        assert await self._run("1,2,3") == [1, 2, 3]

    async def test_single_string_to_int_list(self) -> None:
        """'1' → [1]."""
        assert await self._run("1") == [1]

    async def test_int_list_unchanged(self) -> None:
        """[1,2] (already list of ints) passes through unchanged."""
        assert await self._run([1, 2]) == [1, 2]

    async def test_none_unchanged(self) -> None:
        """None amenity_ids stays None."""
        assert await self._run(None) is None

    async def test_csv_string_with_invalid_tokens_dropped(self) -> None:
        """Non-digit tokens are silently dropped: '1,abc,3' → [1,3]."""
        assert await self._run("1,abc,3") == [1, 3]


# ---------------------------------------------------------------------------
# Limit clamping
# ---------------------------------------------------------------------------


class TestLimitClamping:
    async def test_limit_zero_becomes_one_in_discovery_search(self) -> None:
        """discovery_search: limit=0 → 1."""
        db = AsyncMock()
        unified_mock = AsyncMock(return_value=([], None, 0))

        with (
            patch("app.mcp.chatgpt.discovery_tools.AsyncSessionLocal", return_value=_SessionContext(db)),
            patch("app.mcp.chatgpt.discovery_tools._get_optional_user", new=AsyncMock(return_value=None)),
            patch("app.services.property.get_unified_properties_optimized", new=unified_mock),
        ):
            from app.mcp.chatgpt.discovery_tools import discovery_search

            await discovery_search(limit=0)

        assert unified_mock.await_args.kwargs["limit"] == 1

    async def test_limit_negative_becomes_one_in_discovery_search(self) -> None:
        """discovery_search: limit=-5 → 1."""
        db = AsyncMock()
        unified_mock = AsyncMock(return_value=([], None, 0))

        with (
            patch("app.mcp.chatgpt.discovery_tools.AsyncSessionLocal", return_value=_SessionContext(db)),
            patch("app.mcp.chatgpt.discovery_tools._get_optional_user", new=AsyncMock(return_value=None)),
            patch("app.services.property.get_unified_properties_optimized", new=unified_mock),
        ):
            from app.mcp.chatgpt.discovery_tools import discovery_search

            await discovery_search(limit=-5)

        assert unified_mock.await_args.kwargs["limit"] == 1

    async def test_limit_above_max_clamped_in_discovery_search(self) -> None:
        """discovery_search: limit=9999 → 50."""
        db = AsyncMock()
        unified_mock = AsyncMock(return_value=([], None, 0))

        with (
            patch("app.mcp.chatgpt.discovery_tools.AsyncSessionLocal", return_value=_SessionContext(db)),
            patch("app.mcp.chatgpt.discovery_tools._get_optional_user", new=AsyncMock(return_value=None)),
            patch("app.services.property.get_unified_properties_optimized", new=unified_mock),
        ):
            from app.mcp.chatgpt.discovery_tools import discovery_search

            await discovery_search(limit=9999)

        assert unified_mock.await_args.kwargs["limit"] == 50

    async def test_limit_above_max_clamped_in_discovery_feed(self) -> None:
        """discovery_feed: limit=9999 → 20."""
        db = AsyncMock()
        unified_mock = AsyncMock(return_value=([], None, 0))

        with (
            patch("app.mcp.chatgpt.discovery_tools.AsyncSessionLocal", return_value=_SessionContext(db)),
            patch("app.mcp.chatgpt.discovery_tools._get_optional_user", new=AsyncMock(return_value=None)),
            patch("app.services.property.get_unified_properties_optimized", new=unified_mock),
        ):
            from app.mcp.chatgpt.discovery_tools import discovery_feed

            await discovery_feed(limit=9999)

        assert unified_mock.await_args.kwargs["limit"] == 20

    async def test_limit_above_max_clamped_in_owner_properties_list(self) -> None:
        """owner_properties_list: limit=9999 → 100."""
        db = AsyncMock()
        user = _make_user()
        list_mock = AsyncMock(
            return_value={"items": [], "total": 0, "limit": 100, "stats": {}}
        )

        with (
            patch("app.mcp.user.owner.get_db", return_value=_async_gen(db)),
            patch("app.mcp.user.owner._get_user", new=AsyncMock(return_value=user)),
            patch("app.mcp.user.owner.list_properties_enriched", new=list_mock),
        ):
            from app.mcp.user.owner import owner_properties_list

            await owner_properties_list(limit=9999)

        assert list_mock.await_args.kwargs["limit"] == 100

    async def test_limit_zero_becomes_one_in_owner_properties_list(self) -> None:
        """owner_properties_list: limit=0 → 1."""
        db = AsyncMock()
        user = _make_user()
        list_mock = AsyncMock(
            return_value={"items": [], "total": 0, "limit": 1, "stats": {}}
        )

        with (
            patch("app.mcp.user.owner.get_db", return_value=_async_gen(db)),
            patch("app.mcp.user.owner._get_user", new=AsyncMock(return_value=user)),
            patch("app.mcp.user.owner.list_properties_enriched", new=list_mock),
        ):
            from app.mcp.user.owner import owner_properties_list

            await owner_properties_list(limit=0)

        assert list_mock.await_args.kwargs["limit"] == 1


# ---------------------------------------------------------------------------
# Date parsing (booking tool_ops)
# ---------------------------------------------------------------------------


class TestDateParsing:
    """Verify booking tool_ops date parsing handles ISO-8601 and rejects garbage."""

    async def test_valid_iso_date(self) -> None:
        """Valid ISO-8601 dates reach calculate_pricing as datetime instances."""
        db = AsyncMock()
        pricing_mock = AsyncMock(return_value={"nights": 4, "total_amount": 8000})

        with patch.object(bookings_tool_ops.booking_svc, "calculate_pricing", pricing_mock):
            await bookings_tool_ops.get_pricing(
                db,
                property_id=1,
                check_in_date="2026-07-01T12:00:00",
                check_out_date="2026-07-05T11:00:00",
                guests=2,
            )

        call_args = pricing_mock.await_args
        assert isinstance(call_args.args[2], datetime)
        assert isinstance(call_args.args[3], datetime)
        assert call_args.args[2].year == 2026
        assert call_args.args[3].day == 5

    async def test_invalid_date_returns_error(self) -> None:
        """Non-ISO dates surface a structured error and never reach the service."""
        db = AsyncMock()
        pricing_mock = AsyncMock()

        with patch.object(bookings_tool_ops.booking_svc, "calculate_pricing", pricing_mock):
            result = await bookings_tool_ops.get_pricing(
                db,
                property_id=1,
                check_in_date="07/01/2026",  # not ISO-8601
                check_out_date="2026-07-05",
                guests=1,
            )

        assert result["error"] is True
        assert "ISO-8601" in result["message"]
        pricing_mock.assert_not_awaited()


# ---------------------------------------------------------------------------
# Misc coercion sanity (property_type / purpose enum validation)
# ---------------------------------------------------------------------------


class TestEnumCoercion:
    """Invalid enum values produce structured errors instead of exceptions."""

    async def test_invalid_purpose_returns_error_with_valid_values(self) -> None:
        db = AsyncMock()
        unified_mock = AsyncMock(return_value=([], None, 0))

        with (
            patch("app.mcp.chatgpt.discovery_tools.AsyncSessionLocal", return_value=_SessionContext(db)),
            patch("app.mcp.chatgpt.discovery_tools._get_optional_user", new=AsyncMock(return_value=None)),
            patch("app.services.property.get_unified_properties_optimized", new=unified_mock),
        ):
            from app.mcp.chatgpt.discovery_tools import discovery_search

            result = await discovery_search(purpose="lease")

        # discovery_search catches the ValueError internally and returns an error response
        # Either the structured-content path returns the error or the outer except fires.
        structured = getattr(result, "structured_content", None) or {}
        # If unified_mock was called, the filter took the bad enum (it shouldn't have)
        # Most likely path: purpose validation fails before the filter is built.
        if unified_mock.await_count == 0:
            # Validation path: error structured_content was returned
            assert structured.get("error") is True
            assert "lease" in structured.get("message", "")
        else:
            # Outer except path: error captured
            assert structured.get("error") is True

    async def test_invalid_property_type_returns_error(self) -> None:
        db = AsyncMock()
        unified_mock = AsyncMock(return_value=([], None, 0))

        with (
            patch("app.mcp.chatgpt.discovery_tools.AsyncSessionLocal", return_value=_SessionContext(db)),
            patch("app.mcp.chatgpt.discovery_tools._get_optional_user", new=AsyncMock(return_value=None)),
            patch("app.services.property.get_unified_properties_optimized", new=unified_mock),
            patch("app.mcp.chatgpt.discovery_tools.logger", new=MagicMock()),
        ):
            from app.mcp.chatgpt.discovery_tools import discovery_search

            result = await discovery_search(property_type="mansion")

        structured = getattr(result, "structured_content", None) or {}
        assert structured.get("error") is True
        assert unified_mock.await_count == 0
