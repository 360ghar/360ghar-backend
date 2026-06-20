"""Tests for MCP discovery tools (search, property details, feed, amenities, swipe, shortlist, recommendations)."""
from __future__ import annotations

import contextlib
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.mcp.apps_sdk import AppsSDKToolResult, AuthRequiredError
from app.mcp.chatgpt.discovery_tools import (
    discovery_amenities,
    discovery_feed,
    discovery_property_get,
    discovery_recommendations,
    discovery_search,
    discovery_shortlist,
    discovery_swipe,
)
from app.models.enums import PropertyPurpose, PropertyType

# ---------------------------------------------------------------------------
# Local helpers (mirror tests/unit/mcp/conftest.py factories)
# ---------------------------------------------------------------------------


class _SessionContext:
    """Context manager matching ``AsyncSessionLocal()`` usage."""

    def __init__(self, db):
        self.db = db

    async def __aenter__(self):
        return self.db

    async def __aexit__(self, exc_type, exc, tb):
        return False


def _make_user(user_id: int = 10, role: str = "user"):
    now = datetime.now(timezone.utc)
    return SimpleNamespace(
        id=user_id,
        role=role,
        supabase_user_id=f"user-{user_id}",
        phone="+919876543210",
        full_name="Seeker User",
        email=f"user{user_id}@example.com",
        is_active=True,
        is_verified=True,
        agent_id=None,
        created_at=now,
        updated_at=now,
    )


def _make_property(
    property_id: int = 1,
    title: str = "Test Property",
    city: str = "Delhi",
    locality: str = "Karol Bagh",
    purpose: PropertyPurpose = PropertyPurpose.buy,
    property_type: PropertyType = PropertyType.apartment,
    base_price: float = 5_000_000,
    monthly_rent: float | None = None,
    bedrooms: int = 3,
    bathrooms: int = 2,
    area_sqft: float = 1200,
    is_available: bool = True,
    owner_id: int = 10,
):
    """Build a mock property with enum-typed purpose/property_type.

    ``serialize_property_basic`` accesses ``.value`` on ``purpose`` and
    ``property_type``, so these must be enum members (not plain strings).
    """
    now = datetime.now(timezone.utc)
    return SimpleNamespace(
        id=property_id,
        title=title,
        description="A beautiful property",
        city=city,
        locality=locality,
        full_address=f"{locality}, {city}",
        purpose=purpose,
        property_type=property_type,
        base_price=base_price,
        monthly_rent=monthly_rent,
        daily_rate=None,
        security_deposit=None,
        maintenance_charges=None,
        bedrooms=bedrooms,
        bathrooms=bathrooms,
        balconies=1,
        area_sqft=area_sqft,
        parking_spaces=1,
        floor_number=2,
        total_floors=10,
        max_occupancy=5,
        is_available=is_available,
        owner_id=owner_id,
        owner_name="Owner User",
        owner_contact="+919876543210",
        images=[],
        property_amenities=[],
        amenities=[],
        latitude=None,
        longitude=None,
        pincode="110005",
        state="Delhi",
        main_image_url=None,
        like_count=5,
        view_count=100,
        created_at=now,
        updated_at=now,
    )


def _content_text(result) -> str:
    """Extract narrative text from an AppsSDKToolResult."""
    content = result.content
    if isinstance(content, list) and content:
        block = content[0]
        return getattr(block, "text", str(block))
    return str(content)


@contextlib.contextmanager
def _patch_env(db, user=None):
    """Patch module-level dependencies shared by all discovery tools."""
    with (
        patch(
            "app.mcp.chatgpt.discovery_tools.AsyncSessionLocal",
            return_value=_SessionContext(db),
        ),
        patch(
            "app.mcp.chatgpt.discovery_tools._get_optional_user",
            new=AsyncMock(return_value=user),
        ),
        patch(
            "app.mcp.chatgpt.discovery_tools.get_widget_for_tool",
            return_value="ui://widget/test.html",
        ),
    ):
        yield


# ===========================================================================
# Discovery Search
# ===========================================================================


class TestDiscoverySearch:
    """Tests for the discovery_search MCP tool."""

    async def test_guest_search_returns_results(self):
        db = AsyncMock()
        prop = _make_property()
        mock_search = AsyncMock(return_value=([prop], None, 1))

        with _patch_env(db, user=None), patch(
            "app.services.property.get_unified_properties_optimized", new=mock_search
        ):
            result = await discovery_search(city="Delhi", limit=10)

        assert isinstance(result, AppsSDKToolResult)
        assert result.structured_content["total"] == 1
        assert len(result.structured_content["properties"]) == 1
        assert result.structured_content["properties"][0]["id"] == prop.id

    async def test_guest_search_with_nlp_query(self):
        db = AsyncMock()
        mock_search = AsyncMock(return_value=([], None, 0))

        with _patch_env(db, user=None), patch(
            "app.services.property.get_unified_properties_optimized", new=mock_search
        ):
            await discovery_search(query="3BHK Gurugram buy under 2 crore")

        filters = mock_search.call_args.kwargs["filters"]
        assert filters.bedrooms_min == 3
        assert filters.bedrooms_max == 3
        assert filters.price_max == 20_000_000
        assert filters.purpose == PropertyPurpose.buy
        assert filters.city == "Gurugram"

    async def test_guest_search_empty_results_shows_suggestions(self):
        db = AsyncMock()
        mock_search = AsyncMock(return_value=([], None, 0))

        with _patch_env(db, user=None), patch(
            "app.services.property.get_unified_properties_optimized", new=mock_search
        ):
            result = await discovery_search(city="Agra")

        assert result.structured_content["total"] == 0
        assert result.structured_content["properties"] == []
        assert "No properties found" in _content_text(result)

    async def test_guest_search_amenities_as_string(self):
        db = AsyncMock()
        mock_search = AsyncMock(return_value=([], None, 0))

        with _patch_env(db, user=None), patch(
            "app.services.property.get_unified_properties_optimized", new=mock_search
        ):
            await discovery_search(amenities="wifi,pool")

        assert mock_search.call_args.kwargs["filters"].amenities == ["wifi", "pool"]

    async def test_guest_search_amenities_as_list(self):
        db = AsyncMock()
        mock_search = AsyncMock(return_value=([], None, 0))

        with _patch_env(db, user=None), patch(
            "app.services.property.get_unified_properties_optimized", new=mock_search
        ):
            await discovery_search(amenities=["wifi", "pool"])

        assert mock_search.call_args.kwargs["filters"].amenities == ["wifi", "pool"]

    async def test_guest_search_amenities_none(self):
        db = AsyncMock()
        mock_search = AsyncMock(return_value=([], None, 0))

        with _patch_env(db, user=None), patch(
            "app.services.property.get_unified_properties_optimized", new=mock_search
        ):
            await discovery_search()

        assert mock_search.call_args.kwargs["filters"].amenities is None

    async def test_guest_search_invalid_purpose(self):
        db = AsyncMock()
        mock_search = AsyncMock(return_value=([], None, 0))

        with _patch_env(db, user=None), patch(
            "app.services.property.get_unified_properties_optimized", new=mock_search
        ):
            result = await discovery_search(purpose="vacation")

        assert result.structured_content["error"] is True
        assert "Invalid purpose" in result.structured_content["message"]
        assert "buy" in result.structured_content["message"]
        mock_search.assert_not_awaited()

    async def test_guest_search_invalid_property_type(self):
        db = AsyncMock()
        mock_search = AsyncMock(return_value=([], None, 0))

        with _patch_env(db, user=None), patch(
            "app.services.property.get_unified_properties_optimized", new=mock_search
        ):
            result = await discovery_search(property_type="spaceship")

        assert result.structured_content["error"] is True
        assert "Invalid property_type" in result.structured_content["message"]
        mock_search.assert_not_awaited()

    async def test_guest_search_city_normalization(self):
        db = AsyncMock()
        mock_search = AsyncMock(return_value=([], None, 0))

        with _patch_env(db, user=None), patch(
            "app.services.property.get_unified_properties_optimized", new=mock_search
        ):
            await discovery_search(city="bangalore")

        assert mock_search.call_args.kwargs["filters"].city == "Bengaluru"

    async def test_guest_search_limit_clamping(self):
        db = AsyncMock()
        mock_search = AsyncMock(return_value=([], None, 0))

        with _patch_env(db, user=None), patch(
            "app.services.property.get_unified_properties_optimized", new=mock_search
        ):
            await discovery_search(limit=0)
        assert mock_search.call_args.kwargs["limit"] == 1

        with _patch_env(db, user=None), patch(
            "app.services.property.get_unified_properties_optimized", new=mock_search
        ):
            await discovery_search(limit=100)
        assert mock_search.call_args.kwargs["limit"] == 50

    async def test_guest_search_response_is_apps_sdk_result(self):
        db = AsyncMock()
        prop = _make_property()
        mock_search = AsyncMock(return_value=([prop], {"offset": 1}, 5))

        with _patch_env(db, user=None), patch(
            "app.services.property.get_unified_properties_optimized", new=mock_search
        ):
            result = await discovery_search(city="Delhi")

        assert isinstance(result, AppsSDKToolResult)
        sc = result.structured_content
        for key in ("properties", "total", "next_cursor", "has_more", "limit", "filters_applied"):
            assert key in sc
        assert sc["total"] == 5
        assert sc["has_more"] is True
        assert sc["next_cursor"] is not None
        assert sc["limit"] == 20


# ===========================================================================
# Discovery Property Get
# ===========================================================================


class TestDiscoveryPropertyGet:
    """Tests for the discovery_property_get MCP tool."""

    async def test_get_existing_property(self):
        db = AsyncMock()
        prop = _make_property(property_id=42)

        with _patch_env(db, user=None), patch(
            "app.services.property.get_property", new=AsyncMock(return_value=prop)
        ):
            result = await discovery_property_get(property_id=42)

        assert isinstance(result, AppsSDKToolResult)
        assert result.structured_content["property"]["id"] == 42
        assert result.structured_content["property"]["title"] == prop.title

    async def test_get_nonexistent_returns_error(self):
        db = AsyncMock()

        with _patch_env(db, user=None), patch(
            "app.services.property.get_property",
            new=AsyncMock(side_effect=Exception("Property 999 not found")),
        ):
            result = await discovery_property_get(property_id=999)

        assert result.structured_content["error"] is True
        assert result.structured_content["code"] == "NOT_FOUND"
        assert result.structured_content["property_id"] == 999

    async def test_get_property_guest_no_liked_field(self):
        db = AsyncMock()
        prop = _make_property()

        with _patch_env(db, user=None), patch(
            "app.services.property.get_property", new=AsyncMock(return_value=prop)
        ):
            result = await discovery_property_get(property_id=1)

        assert "user_liked" not in result.structured_content["property"]

    async def test_get_property_auth_user_has_liked_field(self):
        db = AsyncMock()
        user = _make_user()
        prop = _make_property()

        with (
            _patch_env(db, user=user),
            patch("app.services.property.get_property", new=AsyncMock(return_value=prop)),
            patch(
                "app.services.swipe.get_user_like_for_property",
                new=AsyncMock(return_value=True),
            ),
        ):
            result = await discovery_property_get(property_id=1)

        assert result.structured_content["property"]["user_liked"] is True


# ===========================================================================
# Discovery Feed
# ===========================================================================


class TestDiscoveryFeed:
    """Tests for the discovery_feed MCP tool."""

    async def test_feed_returns_properties(self):
        db = AsyncMock()
        props = [_make_property(property_id=1), _make_property(property_id=2)]
        mock_search = AsyncMock(return_value=(props, None, None))

        with _patch_env(db, user=None), patch(
            "app.services.property.get_unified_properties_optimized", new=mock_search
        ):
            result = await discovery_feed(limit=2)

        assert isinstance(result, AppsSDKToolResult)
        assert result.structured_content["count"] == 2
        assert len(result.structured_content["properties"]) == 2

    async def test_feed_with_purpose_filter(self):
        db = AsyncMock()
        mock_search = AsyncMock(return_value=([], None, None))

        with _patch_env(db, user=None), patch(
            "app.services.property.get_unified_properties_optimized", new=mock_search
        ):
            await discovery_feed(purpose="rent")

        assert mock_search.call_args.kwargs["filters"].purpose == PropertyPurpose.rent

    async def test_feed_invalid_purpose(self):
        db = AsyncMock()
        mock_search = AsyncMock(return_value=([], None, None))

        with _patch_env(db, user=None), patch(
            "app.services.property.get_unified_properties_optimized", new=mock_search
        ):
            result = await discovery_feed(purpose="vacation")

        assert result.structured_content["error"] is True
        assert "Invalid purpose" in result.structured_content["message"]
        mock_search.assert_not_awaited()

    async def test_feed_limit_clamping(self):
        db = AsyncMock()
        mock_search = AsyncMock(return_value=([], None, None))

        with _patch_env(db, user=None), patch(
            "app.services.property.get_unified_properties_optimized", new=mock_search
        ):
            await discovery_feed(limit=0)
        assert mock_search.call_args.kwargs["limit"] == 1

        with _patch_env(db, user=None), patch(
            "app.services.property.get_unified_properties_optimized", new=mock_search
        ):
            await discovery_feed(limit=100)
        assert mock_search.call_args.kwargs["limit"] == 20


# ===========================================================================
# Discovery Amenities
# ===========================================================================


class TestDiscoveryAmenities:
    """Tests for the discovery_amenities MCP tool."""

    async def test_amenities_list(self):
        db = AsyncMock()
        amenities = [
            SimpleNamespace(id=1, title="WiFi", icon="wifi"),
            SimpleNamespace(id=2, title="Swimming Pool", icon="pool"),
        ]
        # Use MagicMock so the sync ``result.scalars().all()`` chain resolves
        # synchronously (AsyncMock would make ``scalars()`` return a coroutine).
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = amenities
        db.execute = AsyncMock(return_value=mock_result)

        with _patch_env(db, user=None):
            result = await discovery_amenities()

        assert isinstance(result, AppsSDKToolResult)
        assert result.structured_content["count"] == 2
        assert result.structured_content["amenities"][0]["name"] == "WiFi"
        assert result.structured_content["amenities"][1]["icon"] == "pool"

    async def test_amenities_empty_db(self):
        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        db.execute = AsyncMock(return_value=mock_result)

        with _patch_env(db, user=None):
            result = await discovery_amenities()

        assert result.structured_content["count"] == 0
        assert result.structured_content["amenities"] == []


# ===========================================================================
# Discovery Swipe
# ===========================================================================


class TestDiscoverySwipe:
    """Tests for the discovery_swipe MCP tool."""

    async def test_swipe_requires_auth(self):
        db = AsyncMock()

        with _patch_env(db, user=None):
            with pytest.raises(AuthRequiredError):
                await discovery_swipe(property_id=1, is_liked=True)

    async def test_swipe_like_success(self):
        db = AsyncMock()
        user = _make_user()

        with _patch_env(db, user=user), patch(
            "app.services.swipe.record_swipe", new=AsyncMock(return_value=True)
        ):
            result = await discovery_swipe(property_id=1, is_liked=True)

        assert isinstance(result, AppsSDKToolResult)
        assert result.structured_content["success"] is True
        assert result.structured_content["is_liked"] is True
        assert result.structured_content["property_id"] == 1
        db.commit.assert_awaited_once()

    async def test_swipe_pass_success(self):
        db = AsyncMock()
        user = _make_user()

        with _patch_env(db, user=user), patch(
            "app.services.swipe.record_swipe", new=AsyncMock(return_value=True)
        ):
            result = await discovery_swipe(property_id=5, is_liked=False)

        assert result.structured_content["is_liked"] is False
        assert result.structured_content["property_id"] == 5
        db.commit.assert_awaited_once()


# ===========================================================================
# Discovery Shortlist
# ===========================================================================


class TestDiscoveryShortlist:
    """Tests for the discovery_shortlist MCP tool."""

    async def test_shortlist_requires_auth(self):
        db = AsyncMock()

        with _patch_env(db, user=None):
            with pytest.raises(AuthRequiredError):
                await discovery_shortlist()

    async def test_shortlist_returns_liked(self):
        db = AsyncMock()
        user = _make_user()
        now = datetime.now(timezone.utc)
        swipes = [
            SimpleNamespace(property=_make_property(property_id=1), created_at=now),
            SimpleNamespace(property=_make_property(property_id=2), created_at=now),
        ]
        mock_history = AsyncMock(return_value=(swipes, None, 2))

        with _patch_env(db, user=user), patch(
            "app.services.swipe.get_swipe_history", new=mock_history
        ):
            result = await discovery_shortlist()

        assert isinstance(result, AppsSDKToolResult)
        assert result.structured_content["total"] == 2
        assert len(result.structured_content["properties"]) == 2
        assert result.structured_content["properties"][0]["swiped_at"] is not None

    async def test_shortlist_empty(self):
        db = AsyncMock()
        user = _make_user()
        mock_history = AsyncMock(return_value=([], None, 0))

        with _patch_env(db, user=user), patch(
            "app.services.swipe.get_swipe_history", new=mock_history
        ):
            result = await discovery_shortlist()

        assert result.structured_content["total"] == 0
        assert result.structured_content["properties"] == []


# ===========================================================================
# Discovery Recommendations
# ===========================================================================


class TestDiscoveryRecommendations:
    """Tests for the discovery_recommendations MCP tool."""

    async def test_recommendations_requires_auth(self):
        db = AsyncMock()

        with _patch_env(db, user=None):
            with pytest.raises(AuthRequiredError):
                await discovery_recommendations()

    async def test_recommendations_returns_list(self):
        db = AsyncMock()
        user = _make_user()
        props = [_make_property(property_id=1), _make_property(property_id=2)]
        mock_recs = AsyncMock(return_value=(props, None, None))

        with _patch_env(db, user=user), patch(
            "app.services.property.get_property_recommendations", new=mock_recs
        ):
            result = await discovery_recommendations(limit=2)

        assert isinstance(result, AppsSDKToolResult)
        assert result.structured_content["count"] == 2
        assert len(result.structured_content["properties"]) == 2
        assert result.structured_content["personalized"] is True
