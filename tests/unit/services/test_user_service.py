"""
Tests for user service module.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BaseAPIException
from app.models.enums import UserRole
from app.models.users import User


class TestGetUserByPhone:
    """Tests for get_user_by_phone function."""

    @pytest.mark.asyncio
    async def test_get_user_by_phone_found(self, db_session: AsyncSession, test_user):
        """Test finding user by phone number."""
        from app.services.user import get_user_by_phone

        result = await get_user_by_phone(db_session, test_user.phone)

        assert result is not None
        assert result.id == test_user.id
        assert result.phone == test_user.phone

    @pytest.mark.asyncio
    async def test_get_user_by_phone_not_found(self, db_session: AsyncSession):
        """Test when user not found by phone."""
        from app.services.user import get_user_by_phone

        result = await get_user_by_phone(db_session, "+919999999999")

        assert result is None


class TestGetUserByEmail:
    """Tests for get_user_by_email function."""

    @pytest.mark.asyncio
    async def test_get_user_by_email_found(self, db_session: AsyncSession, test_user):
        """Test finding user by email."""
        from app.services.user import get_user_by_email

        result = await get_user_by_email(db_session, test_user.email)

        assert result is not None
        assert result.id == test_user.id
        assert result.email == test_user.email

    @pytest.mark.asyncio
    async def test_get_user_by_email_not_found(self, db_session: AsyncSession):
        """Test when user not found by email."""
        from app.services.user import get_user_by_email

        result = await get_user_by_email(db_session, "nonexistent@example.com")

        assert result is None


class TestGetUserBySupabaseId:
    """Tests for get_user_by_supabase_id function."""

    @pytest.mark.asyncio
    async def test_get_user_by_supabase_id_found(self, db_session: AsyncSession, test_user):
        """Test finding user by Supabase ID."""
        from app.services.user import get_user_by_supabase_id

        result = await get_user_by_supabase_id(db_session, test_user.supabase_user_id)

        assert result is not None
        assert result.id == test_user.id

    @pytest.mark.asyncio
    async def test_get_user_by_supabase_id_not_found(self, db_session: AsyncSession):
        """Test when user not found by Supabase ID."""
        from app.services.user import get_user_by_supabase_id

        result = await get_user_by_supabase_id(db_session, str(uuid.uuid4()))

        assert result is None


class TestGetOrCreateUserFromSupabase:
    """Tests for get_or_create_user_from_supabase function."""

    @pytest.mark.asyncio
    async def test_get_existing_user_by_supabase_id(self, db_session: AsyncSession, test_user):
        """Test getting existing user by Supabase ID."""
        from app.services.user import get_or_create_user_from_supabase

        supabase_data = {
            "id": test_user.supabase_user_id,
            "phone": test_user.phone,
            "email": test_user.email,
            "email_verified": True,
            "user_metadata": {"full_name": test_user.full_name},
        }

        result = await get_or_create_user_from_supabase(db_session, supabase_data)

        assert result is not None
        assert result.id == test_user.id

    @pytest.mark.asyncio
    async def test_create_new_user(self, db_session: AsyncSession):
        """Test creating new user from Supabase data."""
        from app.services.user import get_or_create_user_from_supabase

        new_supabase_id = str(uuid.uuid4())
        supabase_data = {
            "id": new_supabase_id,
            "phone": "+919111222333",
            "email": "newuser@example.com",
            "email_verified": True,
            # A confirmed email always carries email_confirmed_at from
            # /auth/v1/user; only then is it persisted to the unique column.
            "email_confirmed_at": "2025-01-01T00:00:00Z",
            "user_metadata": {"full_name": "New User"},
        }

        result = await get_or_create_user_from_supabase(db_session, supabase_data)

        assert result is not None
        assert result.supabase_user_id == new_supabase_id
        assert result.phone == "+919111222333"
        assert result.email == "newuser@example.com"

    @pytest.mark.asyncio
    async def test_link_existing_user_by_phone(self, db_session: AsyncSession, test_user):
        """Test linking existing user by phone to new Supabase ID."""
        from app.services.user import get_or_create_user_from_supabase

        # Create user without Supabase ID
        user_without_supabase = User(
            supabase_user_id=str(uuid.uuid4()),
            phone="+919444555666",
            email="existing@example.com",
            full_name="Existing User",
            role=UserRole.user.value,
            is_active=True,
        )
        db_session.add(user_without_supabase)
        await db_session.flush()

        new_supabase_id = str(uuid.uuid4())
        supabase_data = {
            "id": new_supabase_id,
            "phone": "+919444555666",
            "email": "existing@example.com",
            "email_verified": True,
            "user_metadata": {},
        }

        result = await get_or_create_user_from_supabase(db_session, supabase_data)

        assert result is not None
        assert result.phone == "+919444555666"


class TestEmailLinkedIdentity:
    """Tests for the email-linked, multi-method identity model."""

    @pytest.mark.asyncio
    async def test_link_by_verified_email(self, db_session: AsyncSession):
        """Verified email in the token links to the existing local row."""
        from app.services.user import get_or_create_user_from_supabase

        existing = User(
            supabase_user_id=str(uuid.uuid4()),
            email="linkme@example.com",
            phone=None,
            full_name="Link Me",
            role=UserRole.user.value,
            is_active=True,
            email_verified=True,
        )
        db_session.add(existing)
        await db_session.flush()
        existing_id = existing.id

        new_supabase_id = str(uuid.uuid4())
        supabase_data = {
            "id": new_supabase_id,
            "email": "linkme@example.com",
            "phone": None,
            "email_verified": True,
            "email_confirmed_at": "2025-01-01T00:00:00Z",
            "user_metadata": {},
        }

        result = await get_or_create_user_from_supabase(db_session, supabase_data)

        # Same local row, repointed to the new supabase id.
        assert result.id == existing_id
        assert result.supabase_user_id == new_supabase_id

    @pytest.mark.asyncio
    async def test_refuse_link_on_unverified_email(self, db_session: AsyncSession):
        """Unverified email must NOT link; a new row is created instead."""
        from app.services.user import get_or_create_user_from_supabase

        existing = User(
            supabase_user_id=str(uuid.uuid4()),
            email="noverify@example.com",
            phone=None,
            full_name="No Verify",
            role=UserRole.user.value,
            is_active=True,
            email_verified=True,
        )
        db_session.add(existing)
        await db_session.flush()
        existing_id = existing.id
        existing_supabase_id = existing.supabase_user_id

        new_supabase_id = str(uuid.uuid4())
        supabase_data = {
            "id": new_supabase_id,
            "email": "noverify@example.com",
            "phone": None,
            # Email present but NOT confirmed → must not link by email.
            "email_verified": False,
            "email_confirmed_at": None,
            "user_metadata": {},
        }

        result = await get_or_create_user_from_supabase(db_session, supabase_data)

        # A new row keyed on the new supabase id; the existing row is untouched.
        assert result.supabase_user_id == new_supabase_id
        assert result.id != existing_id
        # Unverified incoming email is NOT persisted (would collide with unique key).
        assert result.email is None

        refreshed = await db_session.get(User, existing_id)
        assert refreshed.supabase_user_id == existing_supabase_id

    @pytest.mark.asyncio
    async def test_phone_verified_unconfirmed_email_not_persisted(self, db_session: AsyncSession):
        """A phone-verified user with an UNCONFIRMED email must NOT have that
        email persisted/linked.

        Regression guard: the aggregate ``email_verified`` flag is True when
        EITHER channel is confirmed. For a phone-verified user carrying an
        unconfirmed email, the email-linking decision must be driven SOLELY by
        ``email_confirmed_at`` (here None), so the unconfirmed email is never
        written to the unique email column.
        """
        from app.services.user import get_or_create_user_from_supabase

        new_supabase_id = str(uuid.uuid4())
        supabase_data = {
            "id": new_supabase_id,
            "email": "unconfirmed@example.com",
            "phone": "+919000000099",
            # Aggregate flag is True (phone is confirmed), but the EMAIL itself
            # is NOT confirmed → email must not be persisted.
            "email_verified": True,
            "phone_verified": True,
            "email_confirmed_at": None,
            "phone_confirmed_at": "2025-01-01T00:00:00Z",
            "user_metadata": {},
        }

        result = await get_or_create_user_from_supabase(db_session, supabase_data)

        assert result.supabase_user_id == new_supabase_id
        assert result.phone == "+919000000099"
        assert result.phone_verified is True
        # The unconfirmed email is NOT persisted into the unique email column.
        assert result.email is None

    @pytest.mark.asyncio
    async def test_verified_google_over_unverified_local(self, db_session: AsyncSession):
        """A verified-email Google login links to a local row that has the email."""
        from app.services.user import get_or_create_user_from_supabase

        existing = User(
            supabase_user_id=str(uuid.uuid4()),
            email="google@example.com",
            phone="+919000000001",
            full_name="Google User",
            role=UserRole.user.value,
            is_active=True,
            email_verified=False,
        )
        db_session.add(existing)
        await db_session.flush()
        existing_id = existing.id

        new_supabase_id = str(uuid.uuid4())
        supabase_data = {
            "id": new_supabase_id,
            "email": "google@example.com",
            "phone": None,
            "email_verified": True,
            "email_confirmed_at": "2025-01-01T00:00:00Z",
            "user_metadata": {"full_name": "Google User"},
        }

        result = await get_or_create_user_from_supabase(db_session, supabase_data)

        assert result.id == existing_id
        assert result.supabase_user_id == new_supabase_id
        # Verification mirrored from the verified token.
        assert result.email_verified is True

    @pytest.mark.asyncio
    async def test_phone_backfill_conflict_skip(self, db_session: AsyncSession):
        """When linking by email, an incoming phone that already belongs to a
        DIFFERENT user is not force-written (no duplicate-phone violation)."""
        from app.services.user import get_or_create_user_from_supabase

        # User A owns the phone.
        owner_phone = "+919000000010"
        user_a = User(
            supabase_user_id=str(uuid.uuid4()),
            email="a@example.com",
            phone=owner_phone,
            role=UserRole.user.value,
            is_active=True,
            email_verified=True,
        )
        # User B has the email we will link by, and no phone.
        user_b = User(
            supabase_user_id=str(uuid.uuid4()),
            email="b@example.com",
            phone=None,
            role=UserRole.user.value,
            is_active=True,
            email_verified=True,
        )
        db_session.add_all([user_a, user_b])
        await db_session.flush()
        user_b_id = user_b.id

        new_supabase_id = str(uuid.uuid4())
        supabase_data = {
            "id": new_supabase_id,
            "email": "b@example.com",
            # Phone collides with user A — backfill onto B would violate unique.
            "phone": owner_phone,
            "email_verified": True,
            "email_confirmed_at": "2025-01-01T00:00:00Z",
            "user_metadata": {},
        }

        # Linking by verified email finds B first (B has no phone, so it would
        # try to backfill the colliding phone). We assert it does NOT corrupt
        # the data: B keeps no phone or the flush reconciles without raising.
        result = await get_or_create_user_from_supabase(db_session, supabase_data)

        assert result.id == user_b_id
        assert result.supabase_user_id == new_supabase_id
        # B did not steal A's phone.
        refreshed_a = await db_session.get(User, user_a.id)
        assert refreshed_a.phone == owner_phone

    @pytest.mark.asyncio
    async def test_legacy_duplicate_repoint(self, db_session: AsyncSession):
        """A legacy row found by phone is repointed, not duplicated."""
        from app.services.user import get_or_create_user_from_supabase

        legacy = User(
            supabase_user_id=str(uuid.uuid4()),
            email=None,
            phone="+919000000020",
            full_name="Legacy",
            role=UserRole.user.value,
            is_active=True,
        )
        db_session.add(legacy)
        await db_session.flush()
        legacy_id = legacy.id

        new_supabase_id = str(uuid.uuid4())
        supabase_data = {
            "id": new_supabase_id,
            "email": None,
            "phone": "+919000000020",
            "phone_verified": True,
            "user_metadata": {},
        }

        result = await get_or_create_user_from_supabase(db_session, supabase_data)

        assert result.id == legacy_id
        assert result.supabase_user_id == new_supabase_id
        assert result.phone_verified is True

    @pytest.mark.asyncio
    async def test_integrity_error_reconciles_by_supabase_id(self):
        """IntegrityError on flush reconciles by supabase_user_id."""
        from app.services.user import get_or_create_user_from_supabase

        supabase_id = str(uuid.uuid4())
        reconciled = User(
            id=99,
            supabase_user_id=supabase_id,
            email="recon@example.com",
            phone="+919000000030",
            role=UserRole.user.value,
            is_active=True,
        )

        db = AsyncMock(spec=AsyncSession)
        # First lookup by supabase id (pre-flush) returns None → create path.
        # After IntegrityError + rollback, lookup by supabase id returns the row.
        db.flush.side_effect = [IntegrityError("dup", None, Exception("dup")), None]

        with patch(
            "app.services.user.get_user_by_supabase_id", new_callable=AsyncMock
        ) as mock_by_sb, patch(
            "app.services.user.get_user_by_email", new_callable=AsyncMock
        ) as mock_by_email, patch(
            "app.services.user.get_user_by_phone", new_callable=AsyncMock
        ) as mock_by_phone:
            mock_by_sb.side_effect = [None, reconciled]
            mock_by_email.return_value = None
            mock_by_phone.return_value = None

            supabase_data = {
                "id": supabase_id,
                "email": "recon@example.com",
                "phone": "+919000000030",
                "email_verified": True,
                "email_confirmed_at": "2025-01-01T00:00:00Z",
                "user_metadata": {},
            }

            result = await get_or_create_user_from_supabase(db, supabase_data)

        assert result is reconciled
        db.rollback.assert_awaited()


class TestSetLastAuthMethod:
    """Tests for set_last_auth_method helper."""

    @pytest.mark.asyncio
    async def test_records_method_and_timestamp(self, db_session: AsyncSession, test_user):
        from app.models.enums import AuthMethod
        from app.services.user import set_last_auth_method

        result = await set_last_auth_method(db_session, test_user, AuthMethod.google)

        assert result.last_auth_method == AuthMethod.google.value
        assert result.last_auth_method_at is not None

    @pytest.mark.asyncio
    async def test_records_apple_method(self, db_session: AsyncSession, test_user):
        """Sign in with Apple is a valid last_auth_method (DB CHECK allows it)."""
        from app.models.enums import AuthMethod
        from app.services.user import set_last_auth_method

        result = await set_last_auth_method(db_session, test_user, AuthMethod.apple)

        assert result.last_auth_method == AuthMethod.apple.value
        assert result.last_auth_method_at is not None


class TestGetIdentifierStatus:
    """Tests for get_identifier_status (direct auth.users query).

    The service now reads Supabase's auth.users directly. We mock the DB
    session's execute() so result.mappings().first() returns the desired row
    (or None), and assert the derived status + the bound params.
    """

    def _fake_db(self, row=None, *, execute_exc=None) -> AsyncMock:
        """Build an AsyncSession mock whose execute().mappings().first() returns row."""
        db = AsyncMock(spec=AsyncSession)
        result_mock = MagicMock()
        mappings_mock = MagicMock()
        mappings_mock.first.return_value = row
        result_mock.mappings.return_value = mappings_mock
        if execute_exc is not None:
            db.execute = AsyncMock(side_effect=execute_exc)
        else:
            db.execute = AsyncMock(return_value=result_mock)
        return db

    @pytest.mark.asyncio
    async def test_verified_email_with_password_yields_password(self):
        from app.services.user import get_identifier_status

        db = self._fake_db({
            "id": str(uuid.uuid4()),
            "email": "known@example.com",
            "phone": None,
            "email_confirmed_at": "2025-01-01T00:00:00Z",
            "phone_confirmed_at": None,
            "has_password": True,
        })
        result = await get_identifier_status(db, "known@example.com")

        assert result == {
            "exists": True,
            "verified": True,
            "has_password": True,
            "channel": "email",
            "next_step": "password",
        }

    @pytest.mark.asyncio
    async def test_verified_phone_with_password_yields_password(self):
        from app.services.user import get_identifier_status

        db = self._fake_db({
            "id": str(uuid.uuid4()),
            "email": None,
            "phone": "+919876543210",
            "email_confirmed_at": None,
            "phone_confirmed_at": "2025-01-01T00:00:00Z",
            "has_password": True,
        })
        result = await get_identifier_status(db, "+919876543210")

        assert result == {
            "exists": True,
            "verified": True,
            "has_password": True,
            "channel": "phone",
            "next_step": "password",
        }

    @pytest.mark.asyncio
    async def test_verified_email_without_password_yields_otp(self):
        """OAuth/magic-link user: verified email but no encrypted_password."""
        from app.services.user import get_identifier_status

        db = self._fake_db({
            "id": str(uuid.uuid4()),
            "email": "oauth@example.com",
            "phone": None,
            "email_confirmed_at": "2025-01-01T00:00:00Z",
            "phone_confirmed_at": None,
            "has_password": False,
        })
        result = await get_identifier_status(db, "oauth@example.com")

        assert result["exists"] is True
        assert result["verified"] is True
        assert result["has_password"] is False
        assert result["next_step"] == "otp"

    @pytest.mark.asyncio
    async def test_unverified_with_password_yields_otp(self):
        """Has a password but the matching channel is unconfirmed → otp."""
        from app.services.user import get_identifier_status

        db = self._fake_db({
            "id": str(uuid.uuid4()),
            "email": "unverified@example.com",
            "phone": None,
            "email_confirmed_at": None,
            "phone_confirmed_at": None,
            "has_password": True,
        })
        result = await get_identifier_status(db, "unverified@example.com")

        assert result["exists"] is True
        assert result["verified"] is False
        assert result["has_password"] is True
        assert result["next_step"] == "otp"

    @pytest.mark.asyncio
    async def test_unknown_email_yields_otp(self):
        from app.services.user import get_identifier_status

        db = self._fake_db(None)
        result = await get_identifier_status(db, "nobody@example.com")

        assert result == {
            "exists": False,
            "verified": False,
            "has_password": False,
            "channel": "email",
            "next_step": "otp",
        }

    @pytest.mark.asyncio
    async def test_unknown_phone_yields_otp(self):
        from app.services.user import get_identifier_status

        db = self._fake_db(None)
        result = await get_identifier_status(db, "+919999999999")

        assert result == {
            "exists": False,
            "verified": False,
            "has_password": False,
            "channel": "phone",
            "next_step": "otp",
        }

    @pytest.mark.asyncio
    async def test_db_error_raises_service_unavailable(self):
        """Any DB failure must surface as 503, never as exists=false."""
        from app.core.exceptions import ServiceUnavailableException
        from app.services.user import get_identifier_status

        db = self._fake_db(execute_exc=RuntimeError("connection refused"))
        with pytest.raises(ServiceUnavailableException):
            await get_identifier_status(db, "x@example.com")

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "raw,expected_e164",
        [
            ("9876543210", "+919876543210"),
            ("+91 987-654-3210", "+919876543210"),
            ("00919876543210", "+919876543210"),
            ("+919876543210", "+919876543210"),
        ],
    )
    async def test_phone_identifier_normalized_to_e164(self, raw, expected_e164):
        """Phone channel binds E.164 (with +) and digits-only (GoTrue storage) forms."""
        from app.services.user import get_identifier_status

        db = self._fake_db(None)
        await get_identifier_status(db, raw)

        db.execute.assert_awaited_once()
        bound_params = db.execute.call_args.args[1]
        assert bound_params["phone_e164"] == expected_e164
        assert bound_params["phone_noplus"] == expected_e164.lstrip("+")

    @pytest.mark.asyncio
    async def test_email_identifier_bound_stripped(self):
        from app.services.user import get_identifier_status

        db = self._fake_db(None)
        await get_identifier_status(db, "  Known@Example.com  ")

        db.execute.assert_awaited_once()
        bound_params = db.execute.call_args.args[1]
        assert bound_params["email"] == "Known@Example.com"


class TestUserRoles:
    """Tests for user role handling."""

    @pytest.mark.asyncio
    async def test_user_has_user_role(self, test_user):
        """Test user has correct role."""
        assert test_user.role == UserRole.user.value

    @pytest.mark.asyncio
    async def test_admin_user_has_admin_role(self, test_admin_user):
        """Test admin user has correct role."""
        assert test_admin_user.role == UserRole.admin.value

    @pytest.mark.asyncio
    async def test_agent_user_has_agent_role(self, test_agent_user):
        """Test agent user has correct role."""
        assert test_agent_user.role == UserRole.agent.value


class TestUpdateUser:
    """Tests for update_user function."""

    @pytest.mark.asyncio
    async def test_update_user_unexpected_error_is_wrapped(self):
        """Unexpected update errors should stay in the standard API envelope."""
        from app.schemas.user import UserUpdate
        from app.services.user import update_user

        db = AsyncMock(spec=AsyncSession)
        db.flush.side_effect = RuntimeError("boom")

        existing_user = User(
            id=1,
            supabase_user_id=str(uuid.uuid4()),
            phone="+919876543210",
            email="test@example.com",
            full_name="Test User",
            role=UserRole.user.value,
            is_active=True,
        )

        with patch("app.services.user.get_user_by_id", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = existing_user

            with pytest.raises(BaseAPIException) as exc_info:
                await update_user(
                    db,
                    1,
                    UserUpdate(full_name="Updated Name"),
                    actor=existing_user,
                )

        assert exc_info.value.status_code == 500
        assert exc_info.value.detail == "Internal server error occurred while updating user"
