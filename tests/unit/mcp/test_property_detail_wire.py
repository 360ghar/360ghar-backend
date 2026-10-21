"""Property detail wire shape for MCP and agent tools (be-ai-7, branch-drift-2).

The detail tools receive a Pydantic PropertyDetail, not an ORM row. These tests
read the real Pydantic model, so they guard the path the ORM-shaped tests missed.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.mcp.chatgpt import discovery_tools
from app.mcp.utils import serialize_property_full
from app.schemas.property import PropertyDetail
from app.services.ai_agent.tools import discovery as agent_discovery

OWNER_NUMBER = "+91-9000000000"
AGENT_NUMBER = "9876543210"
NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)

BASE = {
    "id": 42,
    "owner_id": 2,
    "title": "2 BHK in Bandra",
    "property_type": "apartment",
    "purpose": "rent",
    "base_price": 6000000,
    "monthly_rent": 45000,
    "status": "available",
    "is_available": True,
    "view_count": 0,
    "like_count": 0,
    "interest_count": 0,
    "created_at": NOW,
    "updated_at": NOW,
    "furnishing_level": "semi_furnished",
    "age_of_property": 4,
    "owner_contact": OWNER_NUMBER,
    "property_amenities": [
        {"id": 5, "title": "Gym", "icon": "dumbbell", "category": "recreation"},
    ],
}


def _detail(**extra) -> PropertyDetail:
    return PropertyDetail.model_validate({**BASE, **extra})


def _viewer(user_id: int, role: str = "user") -> SimpleNamespace:
    return SimpleNamespace(id=user_id, role=role)


def _agent() -> dict:
    return {"id": 9, "name": "Asha", "contact_number": AGENT_NUMBER}


# ---------------------------------------------------------------- serializer


def test_detail_serializes_with_the_orm_wire_keys():
    out = serialize_property_full(_detail(), viewer=_viewer(2))

    assert out["owner_phone"] == OWNER_NUMBER
    assert out["furnished_status"] == "semi_furnished"
    assert out["age_years"] == 4
    assert out["amenities"] == [
        {"id": 5, "name": "Gym", "icon": "dumbbell", "category": "recreation"}
    ]
    assert "title" not in out["amenities"][0]


def test_detail_has_the_same_keys_as_the_orm_path():
    """The Pydantic and ORM inputs must give one key set, so no tool shows a different shape."""
    pydantic_keys = set(serialize_property_full(_detail(), viewer=_viewer(2)))
    orm_like = SimpleNamespace(
        id=42,
        title="2 BHK in Bandra",
        property_type=None,
        purpose=None,
        status=None,
        city="Mumbai",
        locality="Bandra",
        base_price=None,
        monthly_rent=45000,
        daily_rate=None,
        bedrooms=2,
        bathrooms=2,
        area_sqft=900,
        is_available=True,
        is_managed=False,
        management_status=None,
        latitude=19.0,
        longitude=72.0,
        main_image_url=None,
        created_at=NOW,
        description="d",
        owner_id=2,
        owner_contact=OWNER_NUMBER,
        furnishing_level=None,
        age_of_property=None,
        images=[],
        property_amenities=[],
        updated_at=NOW,
    )
    orm_keys = set(serialize_property_full(orm_like, viewer=_viewer(2)))
    assert pydantic_keys == orm_keys


@pytest.mark.parametrize(
    ("viewer", "expected"),
    [
        (None, AGENT_NUMBER),
        (_viewer(10), AGENT_NUMBER),
        (_viewer(2), OWNER_NUMBER),
        (_viewer(99, role="admin"), OWNER_NUMBER),
    ],
    ids=["anonymous", "stranger", "owner", "admin"],
)
def test_owner_phone_follows_the_viewer(viewer, expected):
    out = serialize_property_full(_detail(agent=_agent()), viewer=viewer)
    assert out["owner_phone"] == expected


def test_anonymous_detail_does_not_carry_the_owner_number():
    out = serialize_property_full(_detail(), viewer=None)
    assert OWNER_NUMBER not in json.dumps(out)


# ---------------------------------------------------------------- MCP discovery tool


def _ctx_db():
    return AsyncMock()


class _SessionContext:
    def __init__(self, db):
        self.db = db

    async def __aenter__(self):
        return self.db

    async def __aexit__(self, exc_type, exc, tb):
        return False


@pytest.mark.asyncio
@pytest.mark.parametrize("user", [None, _viewer(10)], ids=["anonymous", "stranger"])
async def test_discovery_property_get_hides_the_owner_number(user):
    with (
        patch.object(discovery_tools, "AsyncSessionLocal", return_value=_SessionContext(_ctx_db())),
        patch.object(discovery_tools, "_get_optional_user", new=AsyncMock(return_value=user)),
        patch.object(discovery_tools, "get_widget_for_tool", return_value="ui://w.html"),
        patch(
            "app.services.property.get_property",
            new=AsyncMock(return_value=_detail(agent=_agent())),
        ),
        patch(
            "app.services.swipe.get_user_like_for_property",
            new=AsyncMock(return_value=False),
        ),
    ):
        result = await discovery_tools.discovery_property_get(property_id=42)

    payload = json.dumps(result.structured_content)
    assert OWNER_NUMBER not in payload
    assert result.structured_content["property"]["owner_phone"] == AGENT_NUMBER
    assert result.structured_content["property"]["amenities"][0]["name"] == "Gym"


# ---------------------------------------------------------------- agent guest tool


def _agent_ctx(user=None):
    return SimpleNamespace(deps=SimpleNamespace(db=_ctx_db(), user=user))


@pytest.mark.asyncio
@pytest.mark.parametrize("user", [None, _viewer(10)], ids=["anonymous", "stranger"])
async def test_guest_property_details_hides_the_owner_number(user):
    with patch(
        "app.services.property.get_property",
        new=AsyncMock(return_value=_detail(agent=_agent())),
    ):
        out = await agent_discovery.guest_property_details(_agent_ctx(user), property_id=42)

    assert OWNER_NUMBER not in json.dumps(out)
    assert out["property"]["owner_phone"] == AGENT_NUMBER
    assert out["property"]["furnished_status"] == "semi_furnished"
    assert out["property"]["amenities"][0]["name"] == "Gym"
