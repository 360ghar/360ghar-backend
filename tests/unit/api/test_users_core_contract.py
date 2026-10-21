"""Contract fixes for the users, auth and core domains (BE-users pass A).

Each test pins one ledger fix. Service tests use the local test database.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.core.exceptions import ConflictException, ForbiddenException, ValidationException
from app.models.core import AppVersion
from app.models.enums import AppKey, BugSeverity, BugType, DevicePlatform
from app.schemas.core import (
    AppVersionCheckRequest,
    AppVersionCreate,
    AppVersionUpdate,
    BugReportCreate,
    BugReportUpdate,
    FAQCreate,
    FAQUpdate,
    PageCreate,
    PageUpdate,
)
from app.schemas.user import AdminUserUpdate, AuthGateState, UserUpdate
from app.services.core import CoreService
from app.services.user import (
    read_preferences,
    update_user,
    update_user_notification_settings,
    update_user_preferences,
    update_user_privacy_settings,
)

# ── Users: request bodies ──────────────────────────────────────────────────


def test_profile_update_has_no_email_or_unknown_keys() -> None:
    with pytest.raises(ValidationError):
        UserUpdate(email="new@example.com")
    for key in ("bio", "first_name", "last_name", "agent_id", "preferences"):
        with pytest.raises(ValidationError):
            UserUpdate.model_validate({key: "x"})


def test_blank_date_of_birth_becomes_none() -> None:
    assert UserUpdate(date_of_birth="").date_of_birth is None


def test_blank_phone_is_not_sent_and_null_phone_is_rejected() -> None:
    update = UserUpdate.model_validate({"phone": ""})
    assert "phone" not in update.model_fields_set
    with pytest.raises(ValidationError):
        UserUpdate.model_validate({"phone": None})


def test_admin_update_carries_is_active() -> None:
    assert AdminUserUpdate(is_active=False).is_active is False
    with pytest.raises(ValidationError):
        AdminUserUpdate(is_active=None)  # NotNullable: null is not a clear


def test_location_bounds_are_enforced() -> None:
    from app.schemas.user import LocationUpdate

    with pytest.raises(ValidationError):
        LocationUpdate(latitude=91, longitude=0)
    with pytest.raises(ValidationError):
        LocationUpdate(latitude=0, longitude=181)


def test_auth_gate_stage_is_typed() -> None:
    with pytest.raises(ValidationError):
        AuthGateState(stage="almost_done", next_action="grant_access")


def test_identifier_status_channel_and_next_step_are_literals() -> None:
    from app.api.api_v1.endpoints.auth import IdentifierStatusResponse

    with pytest.raises(ValidationError):
        IdentifierStatusResponse(
            exists=True, verified=True, has_password=True, channel="sms", next_step="otp"
        )


def test_stored_preferences_drop_invalid_keys() -> None:
    prefs = read_preferences({"purpose": "rent", "property_type": ["not-a-type"], "budget_min": 5})
    assert prefs.purpose is not None
    assert prefs.property_type is None
    assert prefs.budget_min == 5


# ── Users: service writers ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_non_admin_cannot_set_is_active(db_session, test_user) -> None:
    with pytest.raises(ForbiddenException):
        await update_user(
            db_session, test_user.id, AdminUserUpdate(is_active=False), actor=test_user
        )


@pytest.mark.asyncio
async def test_admin_can_set_is_active(db_session, test_user, test_admin_user) -> None:
    user = await update_user(
        db_session, test_user.id, AdminUserUpdate(is_active=False), actor=test_admin_user
    )
    assert user is not None and user.is_active is False


@pytest.mark.asyncio
async def test_phone_taken_is_409(db_session, test_user, test_user_2) -> None:
    with pytest.raises(ConflictException) as exc_info:
        await update_user(
            db_session, test_user_2.id, UserUpdate(phone=test_user.phone), actor=test_user_2
        )
    assert exc_info.value.error_code == "PHONE_TAKEN"


@pytest.mark.asyncio
async def test_preferences_null_removes_key_and_keeps_others(db_session, test_user) -> None:
    test_user.preferences = {"purpose": "rent", "budget_min": 1000.0}
    await db_session.commit()
    user = await update_user_preferences(
        db_session, test_user.id, {"budget_min": None, "purpose": "buy"}
    )
    assert user is not None
    assert user.preferences == {"purpose": "buy"}


@pytest.mark.asyncio
async def test_notification_settings_merge_keeps_unsent_keys(db_session, test_user) -> None:
    test_user.notification_settings = {
        "push_notifications": False,
        "promotional_emails": True,
        "categories": {"promotions": True},
    }
    await db_session.commit()
    user = await update_user_notification_settings(
        db_session, test_user.id, {"email_notifications": False}
    )
    assert user is not None
    assert user.notification_settings == {
        "push_notifications": False,
        "promotional_emails": True,
        "email_notifications": False,
    }


@pytest.mark.asyncio
async def test_privacy_settings_merge_keeps_unsent_keys(db_session, test_user) -> None:
    test_user.privacy_settings = {"location_sharing": False}
    await db_session.commit()
    user = await update_user_privacy_settings(db_session, test_user.id, {"hide_last_name": True})
    assert user is not None
    assert user.privacy_settings == {"location_sharing": False, "hide_last_name": True}


# ── Users: API ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_profile_put_with_email_is_422(authenticated_client) -> None:
    with patch("app.api.api_v1.endpoints.users.update_user", new_callable=AsyncMock) as mock_update:
        response = await authenticated_client.put(
            "/api/v1/users/profile/", json={"email": "a@example.com"}
        )
    assert response.status_code == 422
    mock_update.assert_not_called()


@pytest.mark.asyncio
async def test_profile_put_with_unknown_key_is_422(authenticated_client) -> None:
    response = await authenticated_client.put("/api/v1/users/profile/", json={"first_name": "A"})
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_privacy_put_rejects_unknown_profile_visibility(authenticated_client) -> None:
    response = await authenticated_client.put(
        "/api/v1/users/privacy-settings", json={"profile_visibility": "secret"}
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_privacy_put_rejects_null(authenticated_client) -> None:
    response = await authenticated_client.put(
        "/api/v1/users/privacy-settings", json={"hide_last_name": None}
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_retired_app_key_is_rejected_on_auth_state(authenticated_client) -> None:
    response = await authenticated_client.get(
        "/api/v1/users/me/auth-state", params={"app": "ghar360"}
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_auth_state_returns_typed_gate(authenticated_client) -> None:
    gate = {"stage": "active", "next_action": "grant_access", "missing_fields": []}
    with patch(
        "app.api.api_v1.endpoints.users.compute_auth_gate_state", new_callable=AsyncMock
    ) as mock_gate:
        mock_gate.return_value = gate
        response = await authenticated_client.get(
            "/api/v1/users/me/auth-state", params={"app": "flatmates"}
        )
    assert response.status_code == 200
    assert response.json() == gate


@pytest.mark.asyncio
async def test_identities_route_is_removed(authenticated_client) -> None:
    response = await authenticated_client.get("/api/v1/users/me/identities")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_link_identity_route_is_removed(authenticated_client) -> None:
    response = await authenticated_client.post(
        "/api/v1/auth/link-identity", json={"provider": "google", "id_token": "t"}
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_location_put_out_of_range_is_422(authenticated_client) -> None:
    response = await authenticated_client.put(
        "/api/v1/users/location", json={"latitude": 95, "longitude": 1}
    )
    assert response.status_code == 422


# ── Core: request bodies ───────────────────────────────────────────────────


def test_bug_report_source_and_app_version_lengths() -> None:
    base = {
        "bug_type": BugType.crash,
        "severity": BugSeverity.high,
        "title": "t",
        "description": "d",
    }
    with pytest.raises(ValidationError):
        BugReportCreate(source="x" * 51, **base)
    with pytest.raises(ValidationError):
        BugReportCreate(source="mobile", app_version="v" * 51, **base)


def test_bug_report_status_cannot_be_cleared() -> None:
    with pytest.raises(ValidationError):
        BugReportUpdate(status=None)


def test_page_update_rejects_null_required_fields() -> None:
    for key in ("title", "content", "is_private"):
        with pytest.raises(ValidationError):
            PageUpdate.model_validate({key: None})
    assert PageUpdate.model_validate({"custom_config": None}).custom_config is None


def test_faq_display_order_and_text_cannot_be_null() -> None:
    with pytest.raises(ValidationError):
        FAQCreate(question="q", answer="a", display_order=None)
    assert FAQCreate(question="q", answer="a").display_order == 0
    with pytest.raises(ValidationError):
        FAQUpdate(display_order=None)
    with pytest.raises(ValidationError):
        FAQUpdate(question=None)


def test_app_version_requires_known_app_and_bounded_fields() -> None:
    with pytest.raises(ValidationError):
        AppVersionCreate(platform="ios", version="1.0.0")  # app is required
    with pytest.raises(ValidationError):
        AppVersionCreate(app="ghar360", platform="ios", version="1.0.0")
    with pytest.raises(ValidationError):
        AppVersionCreate(app="ghar", platform="ios", version="1" * 21)
    update = AppVersionUpdate(version="1.2.0", build_number=5)
    assert update.model_fields_set == {"version", "build_number"}


def test_platform_is_lowercased_before_matching() -> None:
    check = AppVersionCheckRequest(app="ghar", platform="iOS", current_version="1.0.0")
    assert check.platform is DevicePlatform.ios
    assert (
        AppVersionCheckRequest(app=AppKey.stays.value, platform="android", current_version="1").app
        is AppKey.stays
    )


# ── Core: services ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_page_name_of_deleted_page_is_409(db_session, test_admin_user) -> None:
    service = CoreService(db_session)
    payload = {"unique_name": "terms", "title": "Terms", "content": "c", "is_private": False}
    await service.create_page(PageCreate(**payload), created_by=test_admin_user.id)
    await service.delete_page("terms")
    with pytest.raises(ConflictException):
        await service.create_page(PageCreate(**payload), created_by=test_admin_user.id)


@pytest.mark.asyncio
async def test_page_update_to_inactive_returns_the_page(db_session, test_admin_user) -> None:
    service = CoreService(db_session)
    await service.create_page(
        PageCreate(unique_name="faq-page", title="F", content="c"), created_by=test_admin_user.id
    )
    page = await service.update_page(
        "faq-page", PageUpdate(is_active=False), updated_by=test_admin_user.id
    )
    assert page.is_active is False


@pytest.mark.asyncio
async def test_bug_can_be_assigned_only_to_staff(db_session, test_user, test_admin_user) -> None:
    service = CoreService(db_session)
    bug = await service.create_bug_report(
        BugReportCreate(
            source="web",
            bug_type=BugType.crash,
            severity=BugSeverity.high,
            title="t",
            description="d",
        ),
        user_id=test_user.id,
    )
    with pytest.raises(ValidationException) as exc_info:
        await service.update_bug_report(bug.id, BugReportUpdate(assigned_to=test_user.id))
    assert exc_info.value.error_code == "INVALID_ASSIGNEE"
    updated = await service.update_bug_report(
        bug.id, BugReportUpdate(assigned_to=test_admin_user.id)
    )
    assert updated.assigned_to == test_admin_user.id


@pytest.mark.asyncio
async def test_version_compare_is_numeric(db_session) -> None:
    db_session.add(
        AppVersion(app="ghar", platform="ios", version="1.10.0", is_active=True, is_mandatory=False)
    )
    await db_session.commit()
    service = CoreService(db_session)

    def check(current: str) -> AppVersionCheckRequest:
        return AppVersionCheckRequest(app="ghar", platform="ios", current_version=current)

    assert (await service.check_for_updates(check("1.9.0"))).update_available is True
    assert (await service.check_for_updates(check("1.10.0"))).update_available is False
    assert (await service.check_for_updates(check("1.11.0"))).update_available is False


@pytest.mark.asyncio
async def test_version_below_minimum_is_mandatory(db_session) -> None:
    db_session.add(
        AppVersion(
            app="ghar",
            platform="android",
            version="2.0.0",
            is_active=True,
            min_supported_version="1.9.0",
        )
    )
    await db_session.commit()
    service = CoreService(db_session)
    too_old = await service.check_for_updates(
        AppVersionCheckRequest(app="ghar", platform="android", current_version="1.8.9")
    )
    assert too_old.is_mandatory is True
    ok = await service.check_for_updates(
        AppVersionCheckRequest(app="ghar", platform="android", current_version="1.10.0")
    )
    assert ok.is_mandatory is False


# ── Core: API ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_bug_create_requires_auth(client) -> None:
    response = await client.post(
        "/api/v1/bugs",
        json={
            "source": "web",
            "bug_type": "crash",
            "severity": "high",
            "title": "t",
            "description": "d",
        },
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_bug_update_null_status_is_422(admin_authenticated_client) -> None:
    response = await admin_authenticated_client.put("/api/v1/bugs/1", json={"status": None})
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_faq_delete_returns_204(admin_authenticated_client) -> None:
    with patch(
        "app.api.api_v1.endpoints.core.CoreService.delete_faq", new_callable=AsyncMock
    ) as mock_delete:
        mock_delete.return_value = True
        response = await admin_authenticated_client.delete("/api/v1/faqs/1")
    assert response.status_code == 204
    assert response.content == b""


@pytest.mark.asyncio
async def test_app_version_create_without_app_is_422(admin_authenticated_client) -> None:
    response = await admin_authenticated_client.post(
        "/api/v1/versions", json={"platform": "ios", "version": "1.0.0"}
    )
    assert response.status_code == 422


# ── Auth: shared dependency ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_short_session_uses_header_token_only() -> None:
    from app.api.api_v1.dependencies.auth import get_current_user_short_session

    verify = AsyncMock(side_effect=HTTPException(status_code=401, detail="stop"))
    with patch("app.api.api_v1.dependencies.auth.verify_supabase_token", verify):
        with pytest.raises(HTTPException):
            await get_current_user_short_session(MagicMock(), authorization="Bearer abc")
    verify.assert_awaited_once_with("abc")


def test_deeplink_domain_default_is_production_host() -> None:
    from app.core.config import Settings

    assert Settings.model_fields["DEEPLINK_DOMAIN"].default == "360ghar.com"


# ── Users: admin view carries the assigned agent ───────────────────────────


@pytest.mark.asyncio
async def test_admin_user_detail_returns_assigned_agent(
    db_session, test_user, admin_authenticated_client
) -> None:
    from app.models.agents import Agent
    from app.models.enums import AgentType, ExperienceLevel

    agent = Agent(
        name="Asha Rao",
        contact_number="+919800000001",
        agent_type=AgentType.general,
        experience_level=ExperienceLevel.beginner,
    )
    db_session.add(agent)
    await db_session.flush()
    test_user.agent_id = agent.id
    await db_session.flush()

    response = await admin_authenticated_client.get(f"/api/v1/users/{test_user.id}")
    assert response.status_code == 200
    assert response.json()["agent"] == {
        "id": agent.id,
        "name": "Asha Rao",
        "contact_number": "+919800000001",
    }


@pytest.mark.asyncio
async def test_admin_user_detail_agent_is_null_when_unassigned(
    db_session, test_user, admin_authenticated_client
) -> None:
    response = await admin_authenticated_client.get(f"/api/v1/users/{test_user.id}")
    assert response.status_code == 200
    assert response.json()["agent"] is None
