"""Contract fixes for the users, auth and core domains (BE-users, review round 1).

Each test pins one reviewer finding. Service tests use the local test database.
The writer read-back tests commit through their own sessions, so a new session
sees the committed row. Those rows are removed at the end of each test.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from fastapi.routing import APIRoute
from pydantic import ValidationError
from sqlalchemy import CheckConstraint, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.api_v1.endpoints.users import router as users_router
from app.core.exceptions import ForbiddenException
from app.models.core import AppVersion
from app.models.enums import AuthMethod, UserRole
from app.models.users import User
from app.schemas.common import NotificationSettings, NotificationSettingsWrite
from app.schemas.core import AppVersionCheckRequest, FAQResponse
from app.schemas.user import (
    AdminUser,
    AdminUserUpdate,
    UserPreferences,
    UserPreferencesPatch,
    UserUpdate,
)
from app.schemas.user import User as UserSchema
from app.services.core import CoreService
from app.services.user import (
    complete_app_onboarding,
    delete_user_account,
    set_last_auth_method,
    update_user,
    update_user_location,
    update_user_notification_settings,
    update_user_preferences,
    update_user_privacy_settings,
)

# ── Email linking: an unconfirmed stored email never repoints a row (blocker) ──


@pytest.mark.asyncio
async def test_confirmed_email_does_not_repoint_unconfirmed_row(db_session) -> None:
    """A confirmed incoming email must not take over a row whose stored email is unconfirmed.

    The row keeps its identity. Its unconfirmed email is released, so the real owner of
    the address gets a new row with that email.
    """
    from app.services.user import get_or_create_user_from_supabase

    legacy_identity = str(uuid.uuid4())
    legacy = User(
        supabase_user_id=legacy_identity,
        email="legacy-linking@example.com",
        phone=None,
        full_name="Legacy Row",
        role=UserRole.user.value,
        is_active=True,
        # Aggregate flag set by a confirmed phone. It says nothing about the email.
        email_verified=True,
        phone_verified=True,
        is_verified=True,
    )
    db_session.add(legacy)
    await db_session.flush()
    legacy_id = legacy.id

    new_identity = str(uuid.uuid4())
    with patch(
        "app.services.user._supabase_confirms_email", new=AsyncMock(return_value=False)
    ) as confirms:
        result = await get_or_create_user_from_supabase(
            db_session,
            {
                "id": new_identity,
                "email": "legacy-linking@example.com",
                "phone": None,
                "email_verified": True,
                "email_confirmed_at": "2025-01-01T00:00:00Z",
                "user_metadata": {},
            },
        )

    confirms.assert_awaited_once_with(db_session, legacy_identity, "legacy-linking@example.com")
    # New row for the confirmed identity, not the legacy row.
    assert result.id != legacy_id
    assert result.supabase_user_id == new_identity
    assert result.email == "legacy-linking@example.com"
    # The legacy row keeps its identity and loses the unconfirmed email.
    refreshed = await db_session.get(User, legacy_id)
    assert refreshed.supabase_user_id == legacy_identity
    assert refreshed.email is None
    assert refreshed.email_verified is False
    assert refreshed.is_verified is True  # phone is still confirmed


@pytest.mark.asyncio
async def test_supabase_confirms_email_skips_non_uuid_identity() -> None:
    """A tombstone or seed identity cannot confirm an address, so no query runs."""
    from app.services.user import _supabase_confirms_email

    db = AsyncMock(spec=AsyncSession)
    assert await _supabase_confirms_email(db, "__migrated__12", "a@example.com") is False
    assert await _supabase_confirms_email(db, None, "a@example.com") is False
    db.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_supabase_confirms_email_reads_auth_users() -> None:
    """The check reads auth.users for the row's identity, not the local flags."""
    from app.services.user import _supabase_confirms_email

    identity = str(uuid.uuid4())
    db = AsyncMock(spec=AsyncSession)
    result = MagicMock()
    result.first.return_value = (1,)
    db.execute.return_value = result
    assert await _supabase_confirms_email(db, identity, "A@Example.com") is True
    statement = str(db.execute.await_args.args[0])
    assert "auth.users" in statement and "email_confirmed_at IS NOT NULL" in statement

    result.first.return_value = None
    assert await _supabase_confirms_email(db, identity, "a@example.com") is False


# ── App-core-3: inactive users get the USER_INACTIVE envelope ───────────────


@pytest.mark.asyncio
async def test_inactive_user_gets_user_inactive_envelope(client, test_app) -> None:
    """GET /users/me for an inactive user is 403 with error.code USER_INACTIVE."""
    from app.api.api_v1.dependencies.auth import get_current_user

    inactive = SimpleNamespace(id=7, is_active=False, role="user", agent_id=None)

    async def override_get_current_user():
        return inactive

    test_app.dependency_overrides[get_current_user] = override_get_current_user
    try:
        response = await client.get("/api/v1/users/me")
    finally:
        test_app.dependency_overrides.pop(get_current_user, None)

    assert response.status_code == 403
    body = response.json()
    assert body["error"]["code"] == "USER_INACTIVE"
    assert body["error"]["message"] == "Inactive user"


# ── R2-admin-core-a-1: an agent cannot change account status ────────────────


@pytest.mark.asyncio
async def test_agent_cannot_set_is_active(db_session, test_user, test_agent_user) -> None:
    """An agent actor sending is_active gets 403. The field is not dropped silently."""
    with pytest.raises(ForbiddenException) as exc_info:
        await update_user(
            db_session, test_user.id, AdminUserUpdate(is_active=False), actor=test_agent_user
        )
    assert exc_info.value.error_code == "ADMIN_REQUIRED"
    refreshed = await db_session.get(User, test_user.id)
    assert refreshed.is_active is True


# ── Timestamps: UTC with a Z suffix on every owned timestamp ────────────────


def test_response_timestamps_serialize_as_utc_with_z() -> None:
    """A timestamp in another zone is converted to UTC and ends in Z (wire contract)."""
    ist = timezone(timedelta(hours=5, minutes=30))
    faq = FAQResponse(
        id=1,
        question="Q",
        answer="A",
        category=None,
        tags=None,
        display_order=0,
        is_active=True,
        created_at=datetime(2026, 10, 14, 12, 0, tzinfo=ist),
        updated_at=None,
    )
    assert faq.model_dump(mode="json")["created_at"] == "2026-10-14T06:30:00Z"

    user = UserSchema(
        id=1,
        is_active=True,
        is_verified=False,
        created_at=datetime(2026, 1, 1, 0, 0),
        last_auth_method_at=datetime(2026, 1, 2, 3, 4, tzinfo=ist),
    )
    payload = user.model_dump(mode="json")
    assert payload["created_at"] == "2026-01-01T00:00:00Z"
    assert payload["last_auth_method_at"] == "2026-01-01T21:34:00Z"


# ── WriteModel: unknown body keys are 422 on every write route ──────────────


@pytest.mark.asyncio
async def test_last_method_unknown_key_is_422(authenticated_client) -> None:
    with patch("app.api.api_v1.endpoints.auth.set_last_auth_method", new_callable=AsyncMock) as m:
        response = await authenticated_client.post(
            "/api/v1/auth/last-method",
            json={"method": AuthMethod.google.value, "unexpected": True},
        )
    assert response.status_code == 422
    m.assert_not_called()


@pytest.mark.asyncio
async def test_delete_account_unknown_key_is_422(authenticated_client) -> None:
    with patch("app.api.api_v1.endpoints.auth.delete_user_account", new_callable=AsyncMock) as m:
        response = await authenticated_client.post(
            "/api/v1/auth/delete-account", json={"confirm": True, "unexpected": True}
        )
    assert response.status_code == 422
    m.assert_not_called()


@pytest.mark.asyncio
async def test_assign_agent_unknown_key_is_422(admin_authenticated_client) -> None:
    with patch("app.api.api_v1.endpoints.users.assign_agent_to_user", new_callable=AsyncMock) as m:
        response = await admin_authenticated_client.post(
            "/api/v1/users/1/assign-agent", json={"agent_id": 1, "unexpected": True}
        )
    assert response.status_code == 422
    m.assert_not_called()


@pytest.mark.asyncio
async def test_profile_put_with_preferences_is_422(authenticated_client) -> None:
    """be-user-1: preferences have one writer (PUT /users/preferences)."""
    with patch("app.api.api_v1.endpoints.users.update_user", new_callable=AsyncMock) as m:
        response = await authenticated_client.put(
            "/api/v1/users/profile", json={"preferences": {"purpose": "rent"}}
        )
    assert response.status_code == 422
    m.assert_not_called()


# ── Writers commit before returning: read back through a new session ────────


@pytest_asyncio.fixture
async def committed_user(test_engine):
    """A committed user row for the read-back tests. Removed after the test."""
    async with AsyncSession(test_engine, expire_on_commit=False) as session:
        user = User(
            supabase_user_id=str(uuid.uuid4()),
            full_name="Commit Check",
            role=UserRole.user.value,
            is_active=True,
        )
        session.add(user)
        await session.commit()
        user_id = user.id
    try:
        yield user_id
    finally:
        async with AsyncSession(test_engine, expire_on_commit=False) as session:
            await session.execute(text("DELETE FROM users WHERE id = :uid"), {"uid": user_id})
            await session.commit()


async def _read_back(test_engine, user_id: int) -> User:
    """Read the row through a new session, so only committed data is visible."""
    async with AsyncSession(test_engine, expire_on_commit=False) as session:
        return await session.get(User, user_id)


@pytest.mark.asyncio
async def test_set_last_auth_method_is_committed(test_engine, committed_user) -> None:
    async with AsyncSession(test_engine, expire_on_commit=False) as session:
        user = await session.get(User, committed_user)
        await set_last_auth_method(session, user, AuthMethod.google)
    row = await _read_back(test_engine, committed_user)
    assert row.last_auth_method == AuthMethod.google.value
    assert row.last_auth_method_at is not None


@pytest.mark.asyncio
async def test_complete_app_onboarding_is_committed(test_engine, committed_user) -> None:
    """Fixes the race: the gate must not report app_onboarding after the response."""
    async with AsyncSession(test_engine, expire_on_commit=False) as session:
        user = await session.get(User, committed_user)
        await complete_app_onboarding(session, user, app="stays")
    row = await _read_back(test_engine, committed_user)
    assert row.stays_onboarding_completed is True


@pytest.mark.asyncio
async def test_update_user_preferences_is_committed(test_engine, committed_user) -> None:
    async with AsyncSession(test_engine, expire_on_commit=False) as session:
        await update_user_preferences(session, committed_user, {"budget_min": 1200.5})
    row = await _read_back(test_engine, committed_user)
    assert row.preferences == {"budget_min": 1200.5}


@pytest.mark.asyncio
async def test_update_user_location_is_committed(test_engine, committed_user) -> None:
    async with AsyncSession(test_engine, expire_on_commit=False) as session:
        await update_user_location(session, committed_user, 12.5, 77.25)
    row = await _read_back(test_engine, committed_user)
    assert row.current_latitude == 12.5
    assert row.current_longitude == 77.25


@pytest.mark.asyncio
async def test_update_user_notification_settings_is_committed(test_engine, committed_user) -> None:
    async with AsyncSession(test_engine, expire_on_commit=False) as session:
        await update_user_notification_settings(
            session, committed_user, {"push_notifications": False}
        )
    row = await _read_back(test_engine, committed_user)
    assert row.notification_settings["push_notifications"] is False


@pytest.mark.asyncio
async def test_update_user_privacy_settings_is_committed(test_engine, committed_user) -> None:
    async with AsyncSession(test_engine, expire_on_commit=False) as session:
        await update_user_privacy_settings(session, committed_user, {"show_phone": True})
    row = await _read_back(test_engine, committed_user)
    assert row.privacy_settings["show_phone"] is True


@pytest.mark.asyncio
async def test_delete_user_account_commits_before_cache_invalidation(
    test_engine, committed_user
) -> None:
    """The scrub is committed before the 204 and before the auth snapshot is dropped."""
    seen_before_invalidate: dict[str, object] = {}

    async def check_committed(_supabase_user_id: str) -> None:
        row = await _read_back(test_engine, committed_user)
        seen_before_invalidate["is_active"] = row.is_active
        seen_before_invalidate["supabase_user_id"] = row.supabase_user_id

    with (
        patch(
            "app.services.user.admin_delete_user",
            new=AsyncMock(return_value=True),
        ),
        patch(
            "app.services.user.invalidate_auth_user",
            new=AsyncMock(side_effect=check_committed),
        ),
    ):
        async with AsyncSession(test_engine, expire_on_commit=False) as session:
            user = await session.get(User, committed_user)
            await delete_user_account(session, user)

    assert seen_before_invalidate["is_active"] is False
    assert str(seen_before_invalidate["supabase_user_id"]).startswith("__deleted__")
    row = await _read_back(test_engine, committed_user)
    assert row.is_active is False
    assert row.full_name is None


# ── Schemas: money, names, notification keys ────────────────────────────────


def test_budget_fields_are_money() -> None:
    """Money: two decimals, a JSON number. The wire type of budgets changes to Money."""
    prefs = UserPreferences(budget_min=1234.567, budget_max=None)
    assert prefs.budget_min == 1234.57
    assert prefs.model_dump(mode="json")["budget_min"] == 1234.57
    assert UserPreferencesPatch(budget_max=None).budget_max is None


def test_blank_full_name_is_rejected() -> None:
    """A blank name is not stored as an empty string. It fails with NAME_LENGTH."""
    with pytest.raises(ValidationError) as exc_info:
        UserUpdate(full_name="")
    assert exc_info.value.errors()[0]["type"] == "NAME_LENGTH"
    with pytest.raises(ValidationError):
        UserUpdate(full_name="   ")
    assert UserUpdate(full_name=None).full_name is None


def test_notification_settings_have_no_dead_keys() -> None:
    """Keys with no implementation are gone. Writes with them fail with 422."""
    settings = NotificationSettings().model_dump()
    assert set(settings) == {
        "push_notifications",
        "email_notifications",
        "sms_notifications",
        "promotional_emails",
    }
    for dead in ("frequency", "quiet_hours", "categories", "visit_reminders", "digest"):
        with pytest.raises(ValidationError) as exc_info:
            NotificationSettingsWrite(**{dead: "x"})
        assert exc_info.value.errors()[0]["type"] == "extra_forbidden"


# ── Core service: versions compare numerically, equal versions are equal ────


@pytest.mark.asyncio
async def test_padded_version_is_not_an_update(db_session) -> None:
    """Latest 1.0.0 and current 1.0 are the same version, so no update is offered."""
    db_session.add(
        AppVersion(app="ghar", platform="ios", version="1.0.0", is_active=True, is_mandatory=False)
    )
    await db_session.commit()
    service = CoreService(db_session)
    result = await service.check_for_updates(
        AppVersionCheckRequest(app="ghar", platform="ios", current_version="1.0")
    )
    assert result.update_available is False


# ── Models: enum columns have CHECK constraints (13) ────────────────────────


def test_app_version_enum_columns_have_check_constraints() -> None:
    names = {c.name for c in AppVersion.__table__.constraints if isinstance(c, CheckConstraint)}
    assert {"app_versions_app_check", "app_versions_platform_check"} <= names
    app_check = next(
        str(c.sqltext)
        for c in AppVersion.__table__.constraints
        if getattr(c, "name", "") == "app_versions_app_check"
    )
    assert "ghar360" not in app_check and "'ghar'" in app_check


# ── Routes: response shapes are declared ────────────────────────────────────


def _route(path: str, method: str) -> APIRoute:
    return next(
        r
        for r in users_router.routes
        if isinstance(r, APIRoute) and r.path == path and method in r.methods
    )


def test_notification_compat_route_returns_the_notification_resource() -> None:
    """(14) PUT /users/notifications and PUT /users/notification-settings share one shape."""
    assert _route("/notifications", "PUT").response_model is NotificationSettings
    assert _route("/notification-settings", "PUT").response_model is NotificationSettings


def test_assign_agent_returns_the_updated_user() -> None:
    assert _route("/{user_id}/assign-agent", "POST").response_model is AdminUser


# ── Admin routes: domain codes instead of generic ones (12) ─────────────────


@pytest.mark.asyncio
async def test_admin_user_detail_missing_user_has_domain_code(admin_authenticated_client) -> None:
    response = await admin_authenticated_client.get("/api/v1/users/999999999")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "USER_NOT_FOUND"


@pytest.mark.asyncio
async def test_assign_agent_to_missing_user_has_domain_code(admin_authenticated_client) -> None:
    response = await admin_authenticated_client.post(
        "/api/v1/users/999999999/assign-agent", json={"agent_id": 1}
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "USER_NOT_FOUND"


# ── Onboarding: ghar is a no-op through the route (15) ──────────────────────


@pytest.mark.asyncio
async def test_onboarding_for_ghar_returns_the_user(authenticated_client) -> None:
    response = await authenticated_client.post("/api/v1/users/me/onboarding?app=ghar")
    assert response.status_code == 200
    assert response.json()["id"]


# ── Optional auth: infrastructure errors are anonymous, never 401 (must-include) ──


@pytest.mark.asyncio
async def test_optional_auth_maps_infrastructure_errors_to_anonymous() -> None:
    from app.api.api_v1.dependencies.auth import get_current_user_optional

    db = AsyncMock(spec=AsyncSession)
    with patch(
        "app.api.api_v1.dependencies.auth.verify_supabase_token",
        new=AsyncMock(side_effect=RuntimeError("auth provider down")),
    ):
        user = await get_current_user_optional(MagicMock(), authorization="Bearer abc", db=db)
    assert user is None


# ── Write bodies never accept the Supabase UUID ─────────────────────────────


def test_user_write_bodies_do_not_accept_supabase_user_id() -> None:
    """supabase_user_id is output only: no write body declares it."""
    assert "supabase_user_id" not in UserUpdate.model_fields
    assert "supabase_user_id" not in AdminUserUpdate.model_fields
