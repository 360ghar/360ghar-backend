"""Contract fixes for the users, auth and core domains (BE-users, review round 2).

Each test pins one review finding. Schema and shim tests need no database.
The migration test runs the SQL inside a transaction on a scratch schema of the
local test database and rolls it back. The endpoint tests use the shared client
fixtures.
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.api_v1.dependencies.auth import get_current_active_user
from app.schemas.common import NotificationSettings, PrivacySettings
from app.schemas.user import User as UserSchema
from app.schemas.user import UserPreferences

REPO_ROOT = Path(__file__).resolve().parents[3]
MIGRATIONS = REPO_ROOT / "supabase" / "migrations"
SHIM = REPO_ROOT / ".github" / "schema_drift_shim.sql"


# ── Finding 3: stored blobs are typed on read ───────────────────────────────

_LEGACY_NOTIFICATIONS = {
    "push_notifications": False,
    "categories": {"promotions": True},
    "quietHours": {"start": "22:00", "end": "07:00"},
    "frequency": "daily",
}
_INVALID_PREFERENCES = {"purpose": "rent", "budget_min": "abc", "flatmates": {"age": 30}}


def test_stored_blobs_read_typed_and_drop_keys_outside_the_contract() -> None:
    """A stored blob is typed on the schema. Unknown keys and invalid values are not returned."""
    user = UserSchema(
        id=1,
        is_active=True,
        is_verified=False,
        created_at=datetime.now(UTC),
        preferences=_INVALID_PREFERENCES,
        notification_settings=_LEGACY_NOTIFICATIONS,
        privacy_settings={"show_phone": True, "legacy": 1, "profile_visibility": "nobody"},
    )
    dumped = user.model_dump(mode="json")

    assert dumped["preferences"]["purpose"] == "rent"
    assert dumped["preferences"]["budget_min"] is None
    assert "flatmates" not in dumped["preferences"]
    assert set(dumped["notification_settings"]) == set(NotificationSettings.model_fields)
    assert dumped["notification_settings"]["push_notifications"] is False
    assert dumped["privacy_settings"]["show_phone"] is True
    assert dumped["privacy_settings"]["profile_visibility"] == "public"
    assert "legacy" not in dumped["privacy_settings"]


def test_typed_blob_fields_are_typed_models() -> None:
    user = UserSchema(
        id=1,
        is_active=True,
        is_verified=False,
        created_at=datetime.now(UTC),
        preferences=None,
    )
    assert isinstance(user.preferences, UserPreferences)
    assert isinstance(user.notification_settings, NotificationSettings)
    assert isinstance(user.privacy_settings, PrivacySettings)


@pytest.mark.asyncio
async def test_get_me_drops_legacy_notification_keys_and_invalid_preferences(
    client, test_app, test_user
) -> None:
    """GET /users/me returns the typed blobs. categories, quietHours, frequency and bad values are gone."""
    test_user.notification_settings = dict(_LEGACY_NOTIFICATIONS)
    test_user.preferences = dict(_INVALID_PREFERENCES)

    async def override_current_user():
        return test_user

    test_app.dependency_overrides[get_current_active_user] = override_current_user
    try:
        response = await client.get("/api/v1/users/me")
    finally:
        test_app.dependency_overrides.pop(get_current_active_user, None)

    assert response.status_code == 200
    body = response.json()
    assert body["notification_settings"]["push_notifications"] is False
    for dead in ("categories", "quietHours", "quiet_hours", "frequency"):
        assert dead not in body["notification_settings"]
    assert body["preferences"]["purpose"] == "rent"
    assert body["preferences"]["budget_min"] is None
    assert "flatmates" not in body["preferences"]


# ── Finding 1: email and bio are not writable on the two profile saves ──────


@pytest.mark.parametrize("body", [{"email": "new@example.com"}, {"bio": "Hello"}])
@pytest.mark.asyncio
async def test_profile_put_rejects_email_and_bio(authenticated_client, body) -> None:
    """Email changes go through Supabase. The admin profile save sends these keys, so they must 422."""
    with patch("app.api.api_v1.endpoints.users.update_user", new_callable=AsyncMock) as m:
        response = await authenticated_client.put("/api/v1/users/profile", json=body)
    assert response.status_code == 422
    fields = response.json()["error"]["details"]["fields"]
    assert fields[0]["type"] == "extra_forbidden"
    m.assert_not_called()


@pytest.mark.parametrize("body", [{"email": "new@example.com"}, {"bio": "Hello"}])
@pytest.mark.asyncio
async def test_admin_user_put_rejects_email_and_bio(admin_authenticated_client, body) -> None:
    """PUT /users/{id} has no email or bio field. The admin user-detail save sends email."""
    with patch("app.api.api_v1.endpoints.users.update_user", new_callable=AsyncMock) as m:
        response = await admin_authenticated_client.put("/api/v1/users/1", json=body)
    assert response.status_code == 422
    assert response.json()["error"]["details"]["fields"][0]["type"] == "extra_forbidden"
    m.assert_not_called()


# ── Finding 9: a missing FAQ reports FAQ_NOT_FOUND on every route that loads it ──


@pytest.mark.asyncio
async def test_delete_missing_faq_has_faq_code(admin_authenticated_client) -> None:
    response = await admin_authenticated_client.delete("/api/v1/faqs/999999999")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "FAQ_NOT_FOUND"


@pytest.mark.asyncio
async def test_update_missing_faq_has_faq_code(admin_authenticated_client) -> None:
    response = await admin_authenticated_client.put(
        "/api/v1/faqs/999999999", json={"question": "Still a question?"}
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "FAQ_NOT_FOUND"


# ── Finding 5: the notification cleanup migration removes keys, it does not rename ──


_SEED_SQL = """
CREATE TABLE users (
    id int PRIMARY KEY,
    notification_settings jsonb,
    current_latitude real,
    current_longitude real
);
CREATE TABLE app_versions (id int PRIMARY KEY, app text, platform text);
CREATE TABLE faqs (id int PRIMARY KEY, display_order int);
CREATE TABLE bug_reports (id int PRIMARY KEY, status text);
INSERT INTO users (id, notification_settings) VALUES
    (1, '{"push_notifications": false, "categories": {"promotions": true},
          "quietHours": {"start": "22:00"}, "frequency": "daily"}'),
    (2, '{"quiet_hours": {"start": "23:00"}, "email_notifications": true}'),
    (3, '{"quietHours": {"start": "21:00"}, "quiet_hours": {"start": "07:00"}}'),
    (4, NULL);
INSERT INTO app_versions VALUES (1, 'ghar360', 'IOS');
INSERT INTO faqs VALUES (1, NULL);
INSERT INTO bug_reports VALUES (1, NULL);
"""


@pytest.mark.asyncio
async def test_notification_cleanup_migration_removes_legacy_keys_on_seeded_rows(
    test_engine,
) -> None:
    """Seeded rows: categories, quietHours, quiet_hours and frequency are removed, not renamed."""
    sql = (MIGRATIONS / "20261014002000_users_core_contract_constraints.sql").read_text(
        encoding="utf-8"
    )
    async with test_engine.connect() as conn:
        trans = await conn.begin()
        try:
            await conn.exec_driver_sql("CREATE SCHEMA mig_users_round2")
            await conn.exec_driver_sql("SET LOCAL search_path TO mig_users_round2")
            await conn.exec_driver_sql(_SEED_SQL)
            await conn.exec_driver_sql(sql)
            # A second run changes nothing (re-run safe).
            await conn.exec_driver_sql(sql)
            rows = (
                await conn.exec_driver_sql(
                    "SELECT id, notification_settings FROM users ORDER BY id"
                )
            ).fetchall()
            app_row = (await conn.exec_driver_sql("SELECT app, platform FROM app_versions")).one()
            faq_row = (await conn.exec_driver_sql("SELECT display_order FROM faqs")).one()
            bug_row = (await conn.exec_driver_sql("SELECT status FROM bug_reports")).one()
        finally:
            await trans.rollback()

    settings = {row[0]: row[1] for row in rows}
    assert settings[1] == {"push_notifications": False}
    assert settings[2] == {"email_notifications": True}
    assert settings[3] == {}
    assert settings[4] is None
    assert app_row == ("ghar", "ios")
    assert faq_row[0] == 0
    assert bug_row[0] == "open"


# ── Finding 6: the drift shim has the auth.users columns the migrations read ──


def test_drift_shim_auth_users_has_the_columns_migrations_read() -> None:
    shim = SHIM.read_text(encoding="utf-8")
    start = shim.index("CREATE TABLE IF NOT EXISTS auth.users")
    stub = shim[start : shim.index(");", start) + 2]
    assert re.search(r"\bemail\s+text\b", stub)
    assert re.search(r"\bemail_confirmed_at\s+timestamptz\b", stub)

    migration = (MIGRATIONS / "20261014002002_users_email_release_unconfirmed.sql").read_text(
        encoding="utf-8"
    )
    referenced = set(re.findall(r"\bau\.(\w+)", migration))
    assert referenced == {"id", "email", "email_confirmed_at"}
    for column in referenced:
        assert re.search(rf"\b{column}\b", stub), column


# ── Finding 13: a failed local commit after the identity delete is logged for reconciliation ──


@pytest.mark.asyncio
async def test_local_commit_failure_after_identity_delete_is_logged() -> None:
    """The token cannot retry after the Supabase identity is deleted. The marker lets ops find the row."""
    from app.services.user import delete_user_account

    db = AsyncMock(spec=AsyncSession)
    # The unmapped-column lookup reads rows from db.execute(...).all(). None here.
    db.execute.return_value = MagicMock(all=MagicMock(return_value=[]))
    db.commit.side_effect = RuntimeError("database unavailable")
    user = SimpleNamespace(
        id=42,
        supabase_user_id=str(uuid.uuid4()),
        profile_image_url=None,
    )
    with (
        patch(
            "app.services.user.admin_delete_user", new=AsyncMock(return_value=True)
        ) as delete_identity,
        patch("app.services.user.invalidate_auth_user", new=AsyncMock()) as invalidate,
        patch("app.services.user.logger") as log,
        pytest.raises(RuntimeError),
    ):
        await delete_user_account(db, user)

    delete_identity.assert_awaited_once()
    invalidate.assert_not_awaited()
    log.error.assert_called_once()
    assert "ACCOUNT_DELETE_RECONCILE" in log.error.call_args.args[0]
    assert log.error.call_args.args[1] == 42
