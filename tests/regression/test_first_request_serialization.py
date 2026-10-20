"""First requests that UPDATE a row must still serialize ``updated_at`` (contract-audit M2, M4)."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from app.models.enums import TourStatus, TourVisibility
from app.models.tours import Scene, Tour
from app.models.users import User


def _token_payload(supabase_id: str, **extra) -> dict:
    return {
        "id": supabase_id,
        "email": None,
        "phone": None,
        "user_metadata": {},
        "app_metadata": {},
        "email_verified": False,
        "phone_verified": False,
        "email_confirmed_at": None,
        "phone_confirmed_at": None,
        "identities": [],
        **extra,
    }


async def _get_me(client, payload: dict):
    with patch(
        "app.api.api_v1.dependencies.auth.verify_supabase_token",
        new=AsyncMock(return_value=payload),
    ):
        return await client.get("/api/v1/users/me", headers={"Authorization": "Bearer t"})


@pytest.mark.asyncio
async def test_first_users_me_after_verification_upgrade_is_200(real_client, new_session):
    sid = str(uuid.uuid4())
    user = User(
        supabase_user_id=sid,
        email="first@example.com",
        full_name="First",
        role="user",
        is_active=True,
        is_verified=False,
        email_verified=False,
    )
    new_session.add(user)
    await new_session.commit()

    resp = await _get_me(
        real_client,
        _token_payload(
            sid,
            email="first@example.com",
            email_verified=True,
            email_confirmed_at="2026-01-01T00:00:00Z",
        ),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["updated_at"].endswith("Z")
    assert body["email_verified"] is True


@pytest.mark.asyncio
async def test_token_email_replaces_local_email(real_client, new_session):
    """Supabase is the only email writer (app-core-25)."""
    sid = str(uuid.uuid4())
    user = User(
        supabase_user_id=sid,
        email="old@example.com",
        full_name="Mover",
        role="user",
        is_active=True,
        is_verified=True,
        email_verified=True,
    )
    new_session.add(user)
    await new_session.commit()
    user_id = user.id

    resp = await _get_me(
        real_client,
        _token_payload(
            sid,
            email="new@example.com",
            email_verified=True,
            email_confirmed_at="2026-02-01T00:00:00Z",
        ),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["email"] == "new@example.com"

    new_session.expire_all()
    stored = (await new_session.execute(select(User).where(User.id == user_id))).scalar_one()
    assert stored.email == "new@example.com"


@pytest.mark.asyncio
async def test_unconfirmed_token_email_does_not_replace_local_email(real_client, new_session):
    sid = str(uuid.uuid4())
    user = User(
        supabase_user_id=sid,
        email="keep@example.com",
        full_name="Keeper",
        role="user",
        is_active=True,
        is_verified=True,
        email_verified=True,
    )
    new_session.add(user)
    await new_session.commit()

    resp = await _get_me(real_client, _token_payload(sid, email="other@example.com"))
    assert resp.status_code == 200, resp.text
    assert resp.json()["email"] == "keep@example.com"


@pytest.mark.asyncio
async def test_first_public_tour_view_is_200(real_client, new_session):
    owner = User(
        supabase_user_id=str(uuid.uuid4()),
        email="tour-owner@example.com",
        full_name="Owner",
        role="user",
        is_active=True,
        is_verified=True,
    )
    new_session.add(owner)
    await new_session.commit()

    tour = Tour(
        id=str(uuid.uuid4()),
        user_id=owner.id,
        title="Fresh Tour",
        status=TourStatus.published,
        is_public=True,
        visibility=TourVisibility.public,
    )
    new_session.add(tour)
    new_session.add(
        Scene(
            id=str(uuid.uuid4()),
            tour_id=tour.id,
            image_url="https://cdn.example.com/pano.jpg",
            order_index=0,
        )
    )
    await new_session.commit()

    first = await real_client.get(f"/api/v1/public/tours/{tour.id}")
    assert first.status_code == 200, first.text
    assert first.json()["updated_at"].endswith("Z")
    second = await real_client.get(f"/api/v1/public/tours/{tour.id}")
    assert second.status_code == 200, second.text
