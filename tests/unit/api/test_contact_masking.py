"""Owner and counterparty contact masking in GET /swipes and in visit responses."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.api.api_v1.dependencies.auth import (
    get_current_active_user,
    get_current_cached_active_user,
)
from app.core.database import get_db
from app.factory import create_app
from app.schemas.visit import Visit
from app.services.visibility import mask_visit_contacts

NOW = datetime(2026, 9, 1, tzinfo=timezone.utc)
OWNER, VISITOR, COUNTERPARTY, ADMIN = 10, 20, 30, 99


def _viewer(user_id: int, role: str = "user"):
    return SimpleNamespace(id=user_id, role=role, agent_id=None, is_active=True)


def _property():
    return SimpleNamespace(
        id=1, title="2BHK", property_type="apartment", purpose="rent", base_price=25000,
        owner_id=OWNER, owner_contact="+919800000010", status="available", is_available=True,
        view_count=0, like_count=0, interest_count=0, created_at=NOW, updated_at=NOW,
    )


def _counterparty():
    return SimpleNamespace(
        id=COUNTERPARTY, supabase_user_id="u-30", is_active=True, is_verified=True, created_at=NOW, updated_at=NOW,
        full_name="Asha", profile_image_url="https://img/asha.png", email="asha@example.com",
        phone="+919800000030", current_latitude=28.6, current_longitude=77.2,
    )


def _visit_row():
    return SimpleNamespace(
        id=5, user_id=VISITOR, property_id=1, agent_id=None, agent=None,
        scheduled_date=NOW + timedelta(days=2), status="confirmed", visit_context="flatmate_meet",
        counterparty_user_id=COUNTERPARTY, created_at=NOW, updated_at=NOW, follow_up_required=False,
        property=_property(), counterparty_user=_counterparty(),
    )


PUBLIC_REF = {"id", "display_name", "avatar_url"}


# --- the helper ---------------------------------------------------------------------------


def test_helper_masks_for_non_owner_and_keeps_identity():
    visit = Visit.model_validate(_visit_row(), from_attributes=True)
    out = mask_visit_contacts(visit, _viewer(VISITOR))

    assert out.property.owner_contact is None
    cp = out.counterparty_user
    # The counterparty is a PublicUserRef: name and avatar only, never contact data.
    assert set(cp.model_dump()) == {"id", "display_name", "avatar_url"}
    assert (cp.id, cp.display_name, cp.avatar_url) == (COUNTERPARTY, "Asha", "https://img/asha.png")
    # Input is not changed.
    assert visit.property.owner_contact == "+919800000010"
    assert visit.counterparty_user.display_name == "Asha"


@pytest.mark.parametrize("viewer", [_viewer(OWNER), _viewer(ADMIN, "admin")])
def test_helper_keeps_everything_for_owner_and_admin(viewer):
    out = mask_visit_contacts(Visit.model_validate(_visit_row(), from_attributes=True), viewer)
    assert out.property.owner_contact == "+919800000010"
    assert set(out.counterparty_user.model_dump()) == PUBLIC_REF


def test_helper_counterparty_gets_name_and_avatar_only_and_not_owner_number():
    out = mask_visit_contacts(
        Visit.model_validate(_visit_row(), from_attributes=True), _viewer(COUNTERPARTY)
    )
    assert set(out.counterparty_user.model_dump()) == PUBLIC_REF
    assert out.property.owner_contact is None


def test_helper_masks_for_anonymous_viewer():
    out = mask_visit_contacts(Visit.model_validate(_visit_row(), from_attributes=True), None)
    assert out.property.owner_contact is None
    assert set(out.counterparty_user.model_dump()) == PUBLIC_REF


# --- the endpoints --------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _stub_agent_lookup():
    # The DB is a mock here. The agent lookup has a DB-backed test in tests/api/test_owner_agent_contact.py.
    with (
        patch("app.api.api_v1.endpoints.swipes.attach_owner_agents", new=AsyncMock()),
        patch("app.api.api_v1.endpoints.visits.attach_owner_agents", new=AsyncMock()),
    ):
        yield


def _client(viewer) -> TestClient:
    app = create_app(testing=True)
    app.dependency_overrides[get_current_cached_active_user] = lambda: viewer
    app.dependency_overrides[get_current_active_user] = lambda: viewer
    app.dependency_overrides[get_db] = lambda: AsyncMock()
    return TestClient(app, raise_server_exceptions=False)


@pytest.mark.parametrize(("viewer", "expected"), [
    (_viewer(VISITOR), None),
    (_viewer(OWNER), "+919800000010"),
    (_viewer(ADMIN, "admin"), "+919800000010"),
])
def test_swipe_history_masks_owner_contact(viewer, expected):
    swipes = [SimpleNamespace(is_liked=True, property=_property())]
    with patch(
        "app.api.api_v1.endpoints.swipes.get_swipe_history",
        new=AsyncMock(return_value=(swipes, None, None)),
    ):
        resp = _client(viewer).get("/api/v1/swipes")

    assert resp.status_code == 200, resp.text
    item = resp.json()["items"][0]
    assert item["owner_contact"] == expected
    assert item["liked"] is True


@pytest.mark.parametrize(("viewer", "masked"), [
    (_viewer(VISITOR), True),
    (_viewer(OWNER), False),
    (_viewer(ADMIN, "admin"), False),
])
def test_visit_list_detail_and_cancel_mask_contacts(viewer, masked):
    client = _client(viewer)
    with (
        patch(
            "app.api.api_v1.endpoints.visits.get_user_visits",
            new=AsyncMock(return_value=([_visit_row()], None, None)),
        ),
        patch("app.api.api_v1.endpoints.visits.get_visit", new=AsyncMock(return_value=_visit_row())),
        patch("app.api.api_v1.endpoints.visits.can_access_visit", new=AsyncMock(return_value=True)),
        patch("app.api.api_v1.endpoints.visits.cancel_visit", new=AsyncMock(return_value=_visit_row())),
    ):
        listed = client.get("/api/v1/visits")
        detail = client.get("/api/v1/visits/5")
        cancelled = client.post("/api/v1/visits/5/cancel", json={"reason": "busy"})

    bodies = [listed.json()["items"][0], detail.json(), cancelled.json()]
    for resp in (listed, detail, cancelled):
        assert resp.status_code == 200, resp.text
    for body in bodies:
        assert (body["property"]["owner_contact"] is None) is masked
        cp = body["counterparty_user"]
        assert set(cp) == {"id", "display_name", "avatar_url"}
        assert (cp["id"], cp["display_name"]) == (COUNTERPARTY, "Asha")
