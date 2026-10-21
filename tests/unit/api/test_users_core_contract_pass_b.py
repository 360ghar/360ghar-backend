"""Contract fixes for the users, auth and core domains (BE-users pass B).

Each test pins one ledger fix that pass B added. Service tests use the local
test database; schema tests need no database.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from pydantic import ValidationError

from app.models.core import AppVersion
from app.models.enums import DevicePlatform
from app.schemas.common import NotificationSettings, PrivacySettings
from app.schemas.core import (
    AppVersionCheckRequest,
    AppVersionResponse,
    AppVersionUpdate,
)
from app.schemas.user import AdminUser, SelfUser, User, UserPreferences, UserUpdate
from app.services.core import CoreService
from app.services.user import read_typed_blob

# ── Schemas: wire shape ─────────────────────────────────────────────────────


def test_supabase_user_id_is_only_on_the_self_shape() -> None:
    """be-user-57: the Supabase UUID is returned to the signed-in user only."""
    assert "supabase_user_id" in SelfUser.model_fields
    assert "supabase_user_id" not in User.model_fields
    assert "supabase_user_id" not in AdminUser.model_fields


def test_null_stored_blobs_read_as_empty_objects() -> None:
    """tours-web-32: a NULL blob column reads as its typed defaults, never null."""
    user = User(
        id=1,
        is_active=True,
        is_verified=False,
        created_at=datetime.now(UTC),
        preferences=None,
        notification_settings=None,
        privacy_settings=None,
    )
    assert user.preferences == UserPreferences()
    assert user.notification_settings == NotificationSettings()
    assert user.privacy_settings == PrivacySettings()
    dumped = user.model_dump(mode="json")
    assert dumped["preferences"]["max_distance_km"] == 5
    assert dumped["notification_settings"]["push_notifications"] is True


def test_profile_update_rejects_profile_image_url() -> None:
    """app-core-19: only the avatar endpoints write profile_image_url."""
    with pytest.raises(ValidationError) as exc_info:
        UserUpdate(profile_image_url="https://cdn.example.com/a.webp")
    assert exc_info.value.errors()[0]["type"] == "extra_forbidden"


def test_age_rule_error_carries_a_stable_code() -> None:
    """app-core-20: the rule code reaches details.fields[].type, not only the message."""
    too_young = date.today().replace(year=date.today().year - 10)
    with pytest.raises(ValidationError) as exc_info:
        UserUpdate(date_of_birth=too_young)
    error = exc_info.value.errors()[0]
    assert error["type"] == "AGE_RANGE"
    assert error["msg"] == "Must be at least 18 years old"


def test_app_version_update_takes_app_and_platform_but_never_null() -> None:
    """Must-include: the app field is the same AppKey on create and update."""
    assert AppVersionUpdate().app is None
    update = AppVersionUpdate(app="stays", platform="iOS", version="2.0.0", build_number=7)
    assert update.app.value == "stays"
    assert update.platform == DevicePlatform.ios
    assert update.version == "2.0.0"
    assert update.build_number == 7
    with pytest.raises(ValidationError):
        AppVersionUpdate(app=None)
    with pytest.raises(ValidationError):
        AppVersionUpdate(app="ghar360")


def test_app_version_response_uses_the_shared_enums() -> None:
    row = {
        "id": 1,
        "app": "ghar",
        "platform": "ios",
        "version": "1.0.0",
        "build_number": None,
        "release_notes": None,
        "download_url": None,
        "is_mandatory": False,
        "is_active": True,
        "min_supported_version": None,
        "created_at": datetime.now(UTC),
        "updated_at": None,
    }
    assert AppVersionResponse(**row).app.value == "ghar"
    with pytest.raises(ValidationError):
        AppVersionResponse(**{**row, "app": "ghar360"})


def test_version_check_body_rejects_unknown_keys() -> None:
    with pytest.raises(ValidationError) as exc_info:
        AppVersionCheckRequest(app="ghar", platform="ios", current_version="1.0.0", unexpected=True)
    assert exc_info.value.errors()[0]["type"] == "extra_forbidden"


# ── Stored settings: a wrong stored type never fails the read ───────────────


def test_read_typed_blob_drops_a_wrong_typed_key_and_unknown_keys() -> None:
    """be-user-5: a bad stored value falls back to its default. Unknown keys are ignored."""
    stored = {
        "push_notifications": "maybe",
        "email_notifications": False,
        "categories": {"promotions": True},
        "quietHours": {"start": "22:00"},
    }
    settings = read_typed_blob(NotificationSettings, stored)
    assert settings.push_notifications is True
    assert settings.email_notifications is False
    assert not hasattr(settings, "categories")


def test_read_typed_blob_of_a_non_dict_is_the_default_object() -> None:
    assert read_typed_blob(PrivacySettings, None) == PrivacySettings()
    assert read_typed_blob(PrivacySettings, ["x"]) == PrivacySettings()


# ── Routes removed: no client calls them ────────────────────────────────────


@pytest.mark.asyncio
async def test_get_user_preferences_is_gone_but_put_remains(authenticated_client) -> None:
    """be-user-0 / r2-route-matrix-24: GET /users/preferences had no caller. PUT stays.

    The path now matches GET /users/{user_id}, so "preferences" fails as an
    integer path parameter (422). It is not a 200 and not a stored-data read.
    """
    response = await authenticated_client.get("/api/v1/users/preferences")
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_get_faq_by_id_is_gone_but_update_remains(admin_authenticated_client) -> None:
    """r2-route-matrix-25: GET /faqs/{id} had no caller. PUT and DELETE stay."""
    response = await admin_authenticated_client.get("/api/v1/faqs/1")
    assert response.status_code == 405


@pytest.mark.asyncio
async def test_me_returns_the_supabase_id(authenticated_client) -> None:
    response = await authenticated_client.get("/api/v1/users/me")
    assert response.status_code == 200
    assert "supabase_user_id" in response.json()


@pytest.mark.asyncio
async def test_admin_user_detail_hides_the_supabase_id(
    test_user, admin_authenticated_client
) -> None:
    response = await admin_authenticated_client.get(f"/api/v1/users/{test_user.id}")
    assert response.status_code == 200
    body = response.json()
    assert "supabase_user_id" not in body
    assert body["id"] == test_user.id


# ── Bug report with media: field errors, not 500s ───────────────────────────


@pytest.mark.asyncio
async def test_bug_with_media_unknown_enum_is_a_field_error(authenticated_client) -> None:
    """be-user-38: enum form fields are typed. The 422 names the field in the envelope."""
    response = await authenticated_client.post(
        "/api/v1/bugs/with-media",
        data={
            "source": "web",
            "bug_type": "not_a_type",
            "severity": "low",
            "title": "t",
            "description": "d",
        },
    )
    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "VALIDATION_ERROR"
    fields = {f["field"]: f for f in body["error"]["details"]["fields"]}
    assert "body.bug_type" in fields


@pytest.mark.asyncio
async def test_bug_with_media_bad_device_info_json_is_422(authenticated_client) -> None:
    response = await authenticated_client.post(
        "/api/v1/bugs/with-media",
        data={
            "source": "web",
            "bug_type": "crash",
            "severity": "low",
            "title": "t",
            "description": "d",
            "device_info": "{not json",
        },
    )
    assert response.status_code == 422
    fields = response.json()["error"]["details"]["fields"]
    assert fields[0]["field"] == "body.device_info"
    assert fields[0]["type"] == "json_invalid"


@pytest.mark.asyncio
async def test_bug_with_media_device_info_must_be_an_object(authenticated_client) -> None:
    """The JSON parses but is a list. The shared schema rejects it as a field error."""
    response = await authenticated_client.post(
        "/api/v1/bugs/with-media",
        data={
            "source": "web",
            "bug_type": "crash",
            "severity": "low",
            "title": "t",
            "description": "d",
            "device_info": "[1, 2]",
        },
    )
    assert response.status_code == 422
    fields = response.json()["error"]["details"]["fields"]
    assert any(f["field"] == "body.device_info" for f in fields)


# ── Version check: build number breaks a tie on the same version name ───────


@pytest.mark.asyncio
async def test_newer_build_of_the_same_version_is_an_update(db_session) -> None:
    """be-user-39: the build number is used when the version names are equal."""
    db_session.add(
        AppVersion(
            app="flatmates",
            platform="android",
            version="2.4.0",
            build_number=30,
            is_active=True,
            is_mandatory=False,
        )
    )
    await db_session.commit()
    service = CoreService(db_session)

    def check(build: int | None) -> AppVersionCheckRequest:
        return AppVersionCheckRequest(
            app="flatmates", platform="android", current_version="2.4.0", build_number=build
        )

    assert (await service.check_for_updates(check(29))).update_available is True
    assert (await service.check_for_updates(check(30))).update_available is False
    assert (await service.check_for_updates(check(None))).update_available is False


@pytest.mark.asyncio
async def test_admin_update_returns_the_admin_shape_with_the_agent(
    db_session, test_user, admin_authenticated_client
) -> None:
    """PUT /users/{id} answers with AdminUser: the agent summary is loaded, the UUID is not returned."""
    from app.models.agents import Agent
    from app.models.enums import AgentType, ExperienceLevel

    agent = Agent(
        name="Ravi Iyer",
        contact_number="+919800000002",
        agent_type=AgentType.general,
        experience_level=ExperienceLevel.beginner,
    )
    db_session.add(agent)
    await db_session.flush()
    test_user.agent_id = agent.id
    await db_session.flush()

    response = await admin_authenticated_client.put(
        f"/api/v1/users/{test_user.id}", json={"full_name": "Renamed User"}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["full_name"] == "Renamed User"
    assert body["agent"]["name"] == "Ravi Iyer"
    assert "supabase_user_id" not in body
